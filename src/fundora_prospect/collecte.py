"""Le job de collecte : il balaye, il enrichit, il ecrit. Personne ne l'attend.

## Ce qu'il change

Le chemin direct paie une recherche BODACC plus un appel d'enrichissement par
lead, dans le temps de reponse d'une requete. D'ou ses plafonds : 600 annonces
rapatriees, `CANDIDATS_PAR_LEAD x limite` enrichissements. Ce ne sont pas des
choix, ce sont des renoncements — annonces jamais lues, candidats jamais
examines.

Ici, rien n'attend. Le balayage lit TOUT ce que la fenetre contient et enrichit
TOUS les cedants qui le meritent. Les plafonds cessent d'etre subis.

## Les deux economies d'appels, et ce qu'elles ne sont pas

L'enrichissement coute un appel API par SIREN. Deux regles le reduisent, et
aucune des deux ne perd d'information :

- **Un SIREN, un appel.** Plusieurs annonces partagent un cedant : le statut
  est une propriete de la SOCIETE, pas de l'annonce. Interroger deux fois le
  meme SIREN dans un balayage rendrait deux fois la meme reponse.
- **Un statut frais n'est pas resonde** (`TTL_ENRICHISSEMENT_JOURS`), et une
  societe CESSEE ne l'est jamais — elle ne redevient pas active.

A distinguer d'un plafond : un plafond renonce a une information, ces deux
regles evitent de redemander une information qu'on a deja.

## Interruption

La ligne de `collecte` est ecrite AVANT le travail, avec `terminee_a` a NULL.
Un balayage coupe laisse donc une trace qui **se declare incomplete**, et la
lecture le repercute dans son resume. S'il n'ecrivait qu'a la fin, une
interruption serait indistinguable d'un balayage jamais lance — et les
compteurs du passage precedent seraient servis comme s'ils etaient a jour.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from fundora_prospect import entrepot, provenance
from fundora_prospect.bodacc import DEPARTEMENTS_PACA, ResultatRecherche
from fundora_prospect.bodacc import rechercher as _rechercher_bodacc
from fundora_prospect.enrichment import Enrichissement
from fundora_prospect.enrichment import enrichir as _enrichir_entreprise
from fundora_prospect.models import Evaluation, LiquidityEvent, StatutEntreprise
from fundora_prospect.pipeline import _fenetre, repartir

journal = logging.getLogger(__name__)

# Le plafond du chemin direct n'a pas de raison d'exister ici, mais un balayage
# sans borne du tout est un incident silencieux : si la fenetre demandee est
# absurde, mieux vaut buter et le dire. Ce nombre est un garde-fou, pas un
# arbitrage — d'ou l'ecart d'un ordre de grandeur avec `PLAFOND_ANNONCES`.
PLAFOND_BALAYAGE = 20_000


@dataclass(frozen=True)
class ResultatCollecte:
    """Ce qu'un balayage a fait, departement par departement additionne.

    `enrichissements_evites` est le gain mesure du design : le nombre d'appels
    API qu'un « un appel par evenement » aurait emis en plus.
    """

    lot: str
    departements: list[str]
    debut: date
    fin: date
    annonces_publiees: int = 0
    annonces_rapatriees: int = 0
    annonces_exploitables: int = 0
    sans_cedant_ou_illisibles: int = 0
    evenements_ecrits: int = 0
    evenements_nouveaux: int = 0
    cedants_distincts: int = 0
    enrichissements: int = 0
    enrichissements_evites: int = 0
    plafond_atteint: bool = False
    incidents: list[str] = field(default_factory=list)

    # Relus depuis les journaux, pas accumules en memoire. Un compteur tenu au
    # vol dirait ce que le code CROIT avoir ecrit ; ces deux listes disent ce
    # que la base contient reellement. C'est la meme regle que « un test
    # alimente a la main ne prouve rien sur la production » : le seul controle
    # qui vaille rebranche sur la vraie source.
    transitions: list[entrepot.Transition] = field(default_factory=list)
    revisions: list[entrepot.Revision] = field(default_factory=list)

    @property
    def sorties_du_flux(self) -> list[entrepot.Transition]:
        """Les societes qui ont cesse pendant ce balayage.

        Le signal metier du journal : ces leads ne disparaissent pas du
        classement sans raison, ils en SORTENT, et on sait quel jour.
        """
        return [t for t in self.transitions if t.sortie_du_flux]

    @property
    def economie(self) -> float:
        """Part des appels evites sur ceux qu'un appel par cedant aurait couts."""
        total = self.enrichissements + self.enrichissements_evites
        return 0.0 if total == 0 else self.enrichissements_evites / total


def _en_enrichissement(ligne: sqlite3.Row) -> Enrichissement:
    """Reconstitue ce que la base sait deja, pour un SIREN qu'on ne resonde
    pas. Sans ca, la reecriture de la ligne `cedant` effacerait son statut."""
    return Enrichissement(
        siren=ligne["siren"],
        statut=StatutEntreprise(ligne["statut"]),
        code_ape=ligne["code_ape"],
        section_ape=ligne["section_ape"],
        motif=ligne["motif"],
    )


def balayer(
    connexion: sqlite3.Connection,
    *,
    departements: Sequence[str] = DEPARTEMENTS_PACA,
    mois: int = 12,
    aujourdhui: date | None = None,
    lot: str | None = None,
    rechercher: Callable[..., ResultatRecherche] = _rechercher_bodacc,
    enrichir: Callable[..., Enrichissement] = _enrichir_entreprise,
) -> ResultatCollecte:
    """Balaye les departements demandes sur la fenetre, et ecrit en base.

    `departements` est un parametre des maintenant, avec PACA en defaut : le
    cout est nul et l'elargissement du perimetre debloquera le critere
    departement, laisse a poids nul avec la mention « pret a servir si le
    perimetre s'elargit ».

    **Aucun `montant_min`.** Le job ramasse tout ; le seuil est un filtre de
    LECTURE. L'appliquer ici obligerait a recollecter pour le relever.

    Idempotent : relancer sur la meme fenetre met a jour, n'empile pas.
    """
    aujourdhui = aujourdhui or date.today()
    debut = _fenetre(mois, aujourdhui)
    lot = lot or f"{aujourdhui.isoformat()}-{'-'.join(departements)}"

    totaux = {
        "annonces_publiees": 0,
        "annonces_rapatriees": 0,
        "annonces_exploitables": 0,
        "sans_cedant_ou_illisibles": 0,
        "evenements_ecrits": 0,
        "evenements_nouveaux": 0,
        "cedants_distincts": 0,
        "enrichissements": 0,
        "enrichissements_evites": 0,
    }
    plafond_atteint = False
    incidents: list[str] = []

    for departement in departements:
        identifiant = entrepot.demarrer_collecte(
            connexion,
            lot=lot,
            departement=departement,
            fenetre_debut=debut,
            fenetre_fin=aujourdhui,
            lancee_a=aujourdhui,
        )

        recherche = rechercher(
            departements=[departement],
            depuis=debut,
            jusqu_a=aujourdhui,
            limite=PLAFOND_BALAYAGE,
        )
        annonces = recherche.annonces

        # `montant_min=0` : le seuil est un filtre de lecture. On ne garde ici
        # que les candidats — mais les ecartes sont ECRITS eux aussi, plus bas,
        # sinon leur decompte ne serait plus recalculable a la lecture.
        candidats, _ = repartir(annonces, montant_min=0.0)

        # --- Les deux economies d'appels
        #
        # `sirens` compte les CITATIONS (une par annonce), `distincts` les
        # SOCIETES. L'ecart entre les deux est la premiere economie ; le TTL est
        # la seconde, et c'est `sirens_a_enrichir` qui l'applique.
        #
        # Le dedoublonnage ci-dessous ne protege PAS des appels en double :
        # `sirens_a_enrichir` dedoublonne aussi. Il sert a nommer une grandeur —
        # le nombre de societes citees — et sans lui `cedants_distincts`
        # compterait des citations sous un nom qui promet des societes. Deux
        # lignes qui se ressemblent, deux roles differents : ne pas en
        # « simplifier » une.
        sirens = [a.cedant.siren for a in annonces if a.cedant.siren]
        distincts = list(dict.fromkeys(sirens))
        a_enrichir = entrepot.sirens_a_enrichir(connexion, distincts, aujourdhui=aujourdhui)
        deja_connus = entrepot.enrichissements_connus(
            connexion, [s for s in distincts if s not in set(a_enrichir)]
        )

        par_siren: dict[str, Enrichissement] = {
            siren: _en_enrichissement(ligne) for siren, ligne in deja_connus.items()
        }
        for siren in a_enrichir:
            par_siren[siren] = enrichir(siren)

        # --- Ecriture
        #
        # TOUTES les annonces exploitables sont ecrites, candidates ou non.
        # Sans les ecartees, leur decompte par motif cesserait d'etre
        # recalculable et il faudrait une table pour le figer — qui deriverait.
        ecrits = 0
        nouveaux = 0
        for annonce in annonces:
            event = LiquidityEvent.depuis_annonce(
                annonce, par_siren.get(annonce.cedant.siren or "")
            )
            try:
                lead = provenance.assembler(
                    event,
                    # Le job ne CLASSE pas : le score est recalcule a la lecture,
                    # et rien n'en est stocke. Cette evaluation vide n'existe que
                    # parce que la porte d'ecriture n'accepte qu'un `Lead` —
                    # c'est le prix du verrou, et il est volontaire.
                    Evaluation(event_id=event.id, classable=False, motif_refus="non classe"),
                    date_collecte=aujourdhui,
                )
            except Exception as exc:  # provenance incomplete : URL absente
                incidents.append(f"{annonce.id} : {type(exc).__name__}")
                continue
            ecriture = entrepot.enregistrer(connexion, lead)
            ecrits += 1
            nouveaux += ecriture.nouveau

        entrepot.terminer_collecte(
            connexion,
            identifiant,
            terminee_a=aujourdhui,
            annonces_publiees=recherche.publiees,
            annonces_rapatriees=recherche.rapatriees,
            annonces_exploitables=len(annonces),
            sans_cedant_ou_illisibles=recherche.non_exploitables,
            plafond_atteint=recherche.plafond_atteint,
        )

        totaux["annonces_publiees"] += recherche.publiees
        totaux["annonces_rapatriees"] += recherche.rapatriees
        totaux["annonces_exploitables"] += len(annonces)
        totaux["sans_cedant_ou_illisibles"] += recherche.non_exploitables
        totaux["evenements_ecrits"] += ecrits
        totaux["evenements_nouveaux"] += nouveaux
        totaux["cedants_distincts"] += len(distincts)
        totaux["enrichissements"] += len(a_enrichir)
        # Ce qu'un « un appel par evenement » aurait emis en plus : la
        # difference entre le nombre de cedants cites et le nombre d'appels
        # reellement passes.
        totaux["enrichissements_evites"] += len(sirens) - len(a_enrichir)
        plafond_atteint = plafond_atteint or recherche.plafond_atteint

        journal.info(
            "collecte %s : %d annonces, %d candidats, %d appels pour %d cedants cites",
            departement,
            len(annonces),
            len(candidats),
            len(a_enrichir),
            len(sirens),
        )

    return ResultatCollecte(
        lot=lot,
        departements=list(departements),
        debut=debut,
        fin=aujourdhui,
        plafond_atteint=plafond_atteint,
        incidents=incidents,
        # Relus depuis la base, et non accumules pendant la boucle : ce qui est
        # rapporte est ce que la base contient, pas ce que le code pense y avoir
        # mis. Les deux devraient coincider — c'est justement pour ca qu'il faut
        # lire, sinon on ne le saurait jamais.
        transitions=entrepot.transitions(connexion, depuis=aujourdhui),
        revisions=entrepot.revisions(connexion, depuis=aujourdhui),
        **totaux,
    )
