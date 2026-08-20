"""Tracabilite (contrainte 3), appliquee a la serialisation.

**Ce module est une porte, pas une bibliotheque d'aide.** Un lead ne quitte le
pipeline que par `serialiser`, et `serialiser` n'accepte qu'un `Lead` — donc une
`Provenance` complete et validee. C'est la seule construction qui rende la
contrainte 3 opposable plutot que declarative : tant qu'un second chemin de
sortie existe — un dict assemble a la main a cote — la garantie ne vaut que
par la discipline de celui qui ecrit le prochain appel.

Le defaut corrige ici etait exactement celui-la. `Provenance` et `Lead`
existaient depuis la Phase 2 mais n'etaient construits nulle part : le serveur
MCP serialisait un dict a la main, qui portait `url_publication` et **aucun**
des trois autres champs. La contrainte etait ecrite, testee nulle part, et
fausse en production.

## Le champ `base_legale` est descriptif, pas une qualification juridique

Il dit **d'ou vient la donnee** et **quel segment elle concerne**. Ces deux
choses sont verifiables : la source est une publication legale obligatoire, et
le segment se lit dans `typePersonne`.

Il ne nomme pas la base de traitement et ne cite aucun article. Qualifier un
traitement releve du DPO de l'exploitant, qui seul connait la finalite reelle,
les durees de conservation et l'information des personnes. Une formulation
juridique assuree, ecrite ici par un outil de detection, serait un risque pour
l'exploitant — elle donnerait l'apparence d'une analyse qui n'a pas eu lieu —
et non une garantie. Un test verrouille cette decision, sans quoi la premiere
relecture qui trouve le champ « trop vague » y remettrait une citation.

La distinction des deux segments, elle, est structurante : CLAUDE.md interdit
de melanger personne morale et personne physique dans un meme export sans le
champ qui les separe. Ce champ est celui-la.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fundora_prospect.models import (
    Evaluation,
    Lead,
    LiquidityEvent,
    Provenance,
    TypeCedant,
    presenter_contributions,
)

SOURCE = (
    "BODACC — Bulletin officiel des annonces civiles et commerciales (DILA), "
    "consulte via l'API publique bodacc-datadila.opendatasoft.com"
)

# Descriptif et factuel : la source, le segment, et pour le segment secondaire
# le fait qu'il reste a qualifier. Rien qui prejuge de la qualification.
_PUBLICATION = "Donnee issue d'une publication legale obligatoire au BODACC (DILA)"

BASES_LEGALES: dict[TypeCedant, str] = {
    TypeCedant.PERSONNE_MORALE: (
        f"{_PUBLICATION}, concernant une personne morale, exploitee dans un "
        "contexte de prospection B2B."
    ),
    TypeCedant.PERSONNE_PHYSIQUE: (
        f"{_PUBLICATION}, concernant une personne physique. Segment distinct de "
        "la prospection B2B : sa qualification est a etablir par l'exploitant "
        "avant toute utilisation."
    ),
    TypeCedant.INCONNU: (
        f"{_PUBLICATION}. Type de cedant non renseigne par l'annonce : segment "
        "non qualifie, sa qualification est a etablir par l'exploitant avant "
        "toute utilisation."
    ),
}


def base_legale(type_cedant: TypeCedant) -> str:
    """Le texte descriptif associe au segment.

    Le repli sur `INCONNU` est deliberement le cas prudent : un segment qu'on
    ne sait pas nommer n'est pas du B2B etabli.
    """
    return BASES_LEGALES.get(type_cedant, BASES_LEGALES[TypeCedant.INCONNU])


def construire(event: LiquidityEvent, date_collecte: date | None = None) -> Provenance:
    """La provenance d'un evenement. Leve si elle est incomplete.

    `url_publication` vient de `url_complete`, fourni nativement par l'annonce
    BODACC — mais le client le replie sur `""` quand il manque. Ce cas doit
    buter ici : un lead intracable n'est pas un lead degrade, c'est un lead
    qu'on ne peut pas justifier.
    """
    return Provenance(
        source=SOURCE,
        base_legale=base_legale(event.cedant_type),
        date_collecte=date_collecte or date.today(),
        url_publication=event.url_publication,
    )


def assembler(
    event: LiquidityEvent,
    evaluation: Evaluation,
    date_collecte: date | None = None,
) -> Lead:
    """Reunit le fait, ce que la grille en dit, et d'ou il vient."""
    return Lead(
        event=event,
        evaluation=evaluation,
        provenance=construire(event, date_collecte),
    )


def serialiser(lead: Lead) -> dict[str, Any]:
    """**La porte de sortie unique.**

    Le controle de type n'est pas defensif au sens habituel : c'est lui qui
    ferme le contournement. Accepter un dict, ou un `LiquidityEvent` nu,
    rouvrirait le chemin par lequel un lead sans provenance sortait jusqu'ici.
    """
    if not isinstance(lead, Lead):
        raise TypeError(
            f"serialiser n'accepte qu'un Lead, recu {type(lead).__name__}. "
            "Un lead sans provenance complete ne doit pas pouvoir etre "
            "serialise (contrainte 3) : assembler le dict a la main "
            "contournerait ce controle."
        )

    event = lead.event
    return {
        # L'identifiant de l'annonce, c'est-a-dire la clef de la fiche
        # `/evenements/{id}`. Un lead n'en portait pas alors qu'un ecarte en
        # portait un (`models.presenter_ecarte`) : un refus etait donc
        # consultable en detail, un lead retenu ne l'etait pas. L'asymetrie
        # etait un oubli, pas une decision — le front l'a revelee en cherchant
        # quoi mettre dans un lien.
        #
        # Ce n'est pas une donnee personnelle : c'est la reference de la
        # publication au BODACC, celle qui figure deja dans `url_publication`.
        "id": event.id,
        "score": lead.evaluation.score,
        "cedant": event.cedant_denomination,
        "siren": event.cedant_siren,
        "type_cedant": str(event.cedant_type),
        # Le libelle vient de l'enum, jamais d'une table recopiee par une
        # surface : le segment personne physique releve d'une base legale
        # distincte, et c'est le moment ou cette distinction doit rester lisible.
        "type_cedant_libelle": event.cedant_type.libelle,
        "montant_eur": event.montant_eur,
        "date_acte": event.date_acte.isoformat() if event.date_acte else None,
        "date_parution": event.date_parution.isoformat(),
        # Recopies de l'evaluation, jamais recalcules ici : `serialiser` n'a pas
        # de notion d'aujourd'hui, et s'en donner une ferait un second calcul de
        # fraicheur a cote du premier.
        "jours_ecoules": lead.evaluation.jours_ecoules,
        "date_reference": (
            lead.evaluation.date_reference.isoformat()
            if lead.evaluation.date_reference
            else None
        ),
        "departement": event.departement,
        "statut_cedant": str(event.statut_cedant),
        "statut_motif": event.motif_enrichissement,
        "code_ape": event.code_ape,
        "section_ape": event.section_ape,
        "url_publication": event.url_publication,
        "breakdown": presenter_contributions(lead.evaluation),
        "provenance": {
            "source": lead.provenance.source,
            "base_legale": lead.provenance.base_legale,
            "date_collecte": lead.provenance.date_collecte.isoformat(),
            "url_publication": lead.provenance.url_publication,
        },
    }
