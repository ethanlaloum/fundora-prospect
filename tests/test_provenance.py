"""Tracabilite — contrainte 3.

La contrainte dit : « Un lead sans provenance complete ne doit pas pouvoir etre
serialise. » « Ne doit pas pouvoir » est plus fort que « ne devrait pas » : il
ne suffit pas que le chemin nominal remplisse les quatre champs, il faut qu'il
n'existe **aucun** chemin qui les contourne.

Ces tests verifient donc deux choses distinctes :
1. la `Provenance` refuse d'exister incomplete — champ vide compris, parce
   qu'un champ obligatoire rempli par `""` satisfait le type et trahit la
   contrainte ;
2. la serialisation n'accepte qu'un `Lead`, donc qu'une `Provenance` valide.
   Un dict assemble a la main a cote serait le second chemin qui vide la
   contrainte de sa force.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from fundora_prospect import provenance as prov
from fundora_prospect.models import (
    ContributionCritere,
    Evaluation,
    Lead,
    LiquidityEvent,
    Provenance,
    StatutEntreprise,
    TypeCedant,
)

URL = "https://www.bodacc.fr/pages/annonces-commerciales-detail/?q.id=id:A20260153319"

PROVENANCE_VALIDE = {
    "source": prov.SOURCE,
    "base_legale": prov.base_legale(TypeCedant.PERSONNE_MORALE),
    "date_collecte": date(2026, 8, 16),
    "url_publication": URL,
}


def fabriquer_event(
    type_cedant: TypeCedant = TypeCedant.PERSONNE_MORALE,
    url: str = URL,
) -> LiquidityEvent:
    return LiquidityEvent(
        id="A20260153319",
        date_parution=date(2026, 8, 13),
        date_acte=date(2026, 7, 25),
        departement="13",
        url_publication=url,
        montant_eur=185_000.0,
        devise="EUR",
        qualification="achat",
        retenu=True,
        cedant_denomination="LE FOURNIL D ORNELLA",
        cedant_type=type_cedant,
        cedant_siren="852872563",
        statut_cedant=StatutEntreprise.ACTIVE,
        motif_enrichissement="fixture",
        code_ape="10.71C",
        section_ape="C",
    )


def fabriquer_evaluation(event: LiquidityEvent) -> Evaluation:
    return Evaluation(
        event_id=event.id,
        classable=True,
        score=73.2,
        contributions=[
            ContributionCritere(
                critere="montant",
                poids=55.0,
                valeur_normalisee=0.576,
                points=31.7,
                motif="185 000 EUR, echelle log",
            )
        ],
    )


# --- La provenance refuse d'exister incomplete --------------------------------


@pytest.mark.parametrize("champ", ["source", "base_legale", "date_collecte", "url_publication"])
def test_un_champ_de_provenance_absent_leve(champ: str) -> None:
    """Le test a des dents : on retire un champ a la fois et chacun doit faire
    echouer la construction. Sans ce parametrage, un test qui ne verifie que le
    cas nominal passerait meme si trois des quatre champs devenaient
    optionnels."""
    ampute = {k: v for k, v in PROVENANCE_VALIDE.items() if k != champ}
    with pytest.raises(ValidationError):
        Provenance(**ampute)


@pytest.mark.parametrize("champ", ["source", "base_legale", "url_publication"])
def test_un_champ_de_provenance_vide_leve(champ: str) -> None:
    """`""` satisfait le type `str` et passerait le controle d'obligation.
    C'est le trou par lequel une tracabilite declarative se glisse : le champ
    est la, il ne dit rien."""
    with pytest.raises(ValidationError):
        Provenance(**{**PROVENANCE_VALIDE, champ: "   "})


def test_une_url_de_publication_non_absolue_leve() -> None:
    """Une provenance doit etre verifiable par un tiers : un fragment d'URL ne
    permet pas de remonter a l'annonce."""
    with pytest.raises(ValidationError):
        Provenance(**{**PROVENANCE_VALIDE, "url_publication": "annonces/A20260153319"})


def test_un_lead_sans_provenance_ne_peut_pas_etre_construit() -> None:
    event = fabriquer_event()
    with pytest.raises(ValidationError):
        Lead(event=event, evaluation=fabriquer_evaluation(event))  # type: ignore[call-arg]


# --- La serialisation est la porte unique -------------------------------------


def test_la_serialisation_refuse_ce_qui_n_est_pas_un_lead() -> None:
    """Le gate de la phase : un lead sans provenance ne doit pas POUVOIR etre
    exporte. Si `serialiser` acceptait un dict, il suffirait d'en assembler un
    a cote pour contourner tout le controle."""
    event = fabriquer_event()
    with pytest.raises(TypeError):
        prov.serialiser({"score": 73.2, "cedant": "LE FOURNIL D ORNELLA"})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        prov.serialiser(event)  # type: ignore[arg-type]


def test_la_serialisation_porte_les_quatre_champs() -> None:
    event = fabriquer_event()
    lead = prov.assembler(event, fabriquer_evaluation(event), date_collecte=date(2026, 8, 16))
    charge = prov.serialiser(lead)

    assert set(charge["provenance"]) == {
        "source",
        "base_legale",
        "date_collecte",
        "url_publication",
    }
    assert charge["provenance"]["url_publication"] == URL
    assert charge["provenance"]["date_collecte"] == "2026-08-16"
    assert "BODACC" in charge["provenance"]["source"]


def test_la_serialisation_conserve_le_lead_et_son_breakdown() -> None:
    """La provenance s'ajoute au lead, elle ne le remplace pas : le breakdown
    de la contrainte 5 doit survivre au passage par la porte unique."""
    event = fabriquer_event()
    charge = prov.serialiser(prov.assembler(event, fabriquer_evaluation(event)))

    assert charge["score"] == 73.2
    assert charge["cedant"] == "LE FOURNIL D ORNELLA"
    assert charge["siren"] == "852872563"
    assert charge["montant_eur"] == 185_000.0
    assert charge["breakdown"][0]["critere"] == "montant"
    assert charge["breakdown"][0]["motif"]


def test_la_serialisation_ne_confond_aucun_champ_du_breakdown() -> None:
    """Le test precedent verifie que le motif EXISTE. Il ne verifie pas qu'il
    porte le motif : remplacer `c.motif` par `c.critere` dans `serialiser`
    laisse les 446 tests verts — le champ reste present, non vide, et faux.

    `serialiser` est un mappeur, et un mappeur se garde champ par champ. Une
    permutation de deux champs de meme type est invisible a toute assertion de
    presence, et c'est la seule erreur qu'un mappeur commet vraiment.
    """
    event = fabriquer_event()
    evaluation = fabriquer_evaluation(event)
    charge = prov.serialiser(prov.assembler(event, evaluation))

    assert len(charge["breakdown"]) == len(evaluation.contributions)
    for rendu, source in zip(charge["breakdown"], evaluation.contributions, strict=True):
        assert rendu["critere"] == source.critere
        assert rendu["motif"] == source.motif
        assert rendu["points"] == source.points
        assert rendu["poids"] == source.poids
        # Le motif explique le critere, il ne le repete pas : si les deux sont
        # egaux, c'est le symptome exact de la permutation.
        assert rendu["motif"] != rendu["critere"]


def test_une_annonce_sans_url_ne_peut_pas_devenir_un_lead() -> None:
    """`url_complete` est renseigne nativement par BODACC, mais le client le
    replie sur `""` s'il manque. Ce cas doit buter sur la provenance, pas
    produire un lead intracable."""
    with pytest.raises(ValidationError):
        prov.assembler(
            fabriquer_event(url=""),
            fabriquer_evaluation(fabriquer_event()),
        )


def test_la_date_de_collecte_vaut_aujourd_hui_par_defaut() -> None:
    event = fabriquer_event()
    lead = prov.assembler(event, fabriquer_evaluation(event))
    assert lead.provenance.date_collecte == date.today()


# --- La base legale est descriptive, pas une qualification juridique ----------


def test_les_deux_segments_ne_portent_pas_la_meme_base_legale() -> None:
    """CLAUDE.md : « Ne pas melanger les deux segments dans un meme export sans
    le champ qui les distingue. » Ce champ, c'est celui-la."""
    pm = prov.base_legale(TypeCedant.PERSONNE_MORALE)
    pp = prov.base_legale(TypeCedant.PERSONNE_PHYSIQUE)
    assert pm != pp
    assert "morale" in pm.lower()
    assert "physique" in pp.lower()


def test_le_segment_personne_physique_est_signale_a_qualifier() -> None:
    """Le segment secondaire ne doit pas pouvoir etre exploite par inadvertance
    au meme titre que le B2B."""
    pp = prov.base_legale(TypeCedant.PERSONNE_PHYSIQUE)
    assert "qualification" in pp.lower()


def test_un_type_de_cedant_inconnu_est_traite_comme_a_qualifier() -> None:
    """La prudence par defaut : un segment qu'on ne sait pas nommer n'est pas
    du B2B etabli."""
    inconnu = prov.base_legale(TypeCedant.INCONNU)
    assert inconnu != prov.base_legale(TypeCedant.PERSONNE_MORALE)
    assert "qualification" in inconnu.lower()


@pytest.mark.parametrize("type_cedant", list(TypeCedant))
@pytest.mark.parametrize("interdit", ["rgpd", "article", "interet legitime", "intérêt légitime"])
def test_la_base_legale_ne_qualifie_pas_juridiquement(
    type_cedant: TypeCedant, interdit: str
) -> None:
    """**Decision explicite du projet.** Le champ dit d'ou vient la donnee et
    quel segment elle concerne — c'est verifiable. Nommer la base de traitement
    ou citer un article ne l'est pas : cela releve du DPO de l'exploitant, et
    une formulation assuree ecrite ici serait un risque pour lui, pas une
    garantie.

    Le test verrouille la decision. Sans lui, la premiere relecture qui trouve
    le champ « trop vague » y remettrait une citation d'article."""
    assert interdit not in prov.base_legale(type_cedant).lower()
