"""Le pipeline de detection, extrait du serveur MCP.

## Pourquoi ce module existe

Le pipeline complet — recherche, filtrage, pre-classement, enrichissement,
scoring, tri, comptage des motifs de refus — vivait dans le corps de l'outil
MCP `search_liquidity_events`. Il y etait au chaud tant qu'il n'y avait qu'une
surface. Une seconde surface (une API web) aurait du le **recopier**, et deux
implementations d'un meme pipeline divergent toujours : c'est exactement la
famille de defaut que ce projet a passe cinq phases a traquer — un tri en
amont qui n'obeit pas aux regles du classement final, un compteur calcule sous
une coupe, un exemple recopie a la main dans un prompt.

Le coeur est donc ici, et chaque surface se reduit a de la traduction :

    coeur Python  ─┬─  mcp_server.py   ->  Claude Code
                   └─  api.py          ->  navigateur

## Les deux fonctions reseau sont des parametres, pas des imports

`executer` recoit `rechercher` et `enrichir` en arguments, avec les vraies
fonctions en valeur par defaut. Deux raisons, et les deux sont vraies :

- **de conception** : ce sont les deux seuls points ou le pipeline sort de la
  machine. Les prendre en parametre fait de chaque surface une racine de
  composition, libre de substituer ses ports ;
- **de fait** : `tests/test_mcp_server.py` substitue `mcp_server.rechercher` et
  `mcp_server.enrichir` sur douze cas. Si ce module les importait pour son
  propre compte, ces substitutions deviendraient inertes et la suite partirait
  sur le reseau. Le serveur MCP les passe donc explicitement.

## Ce qui n'est PAS ici

La normalisation des arguments propres a un transport : tolerer l'entier `6`
la ou un schema JSON attend `"06"`, rendre un message d'erreur qu'un modele
peut lire pour se corriger seul. Ca appartient a la surface. Le vocabulaire du
domaine — les codes de departement, l'alias « PACA » — est en revanche
descendu ici : un formulaire web ecrit « PACA » exactement comme un modele.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ValidationError

from fundora_prospect import provenance
from fundora_prospect.bodacc import DEPARTEMENTS_PACA, Annonce, ResultatRecherche
from fundora_prospect.bodacc import rechercher as _rechercher_bodacc
from fundora_prospect.enrichment import Enrichissement
from fundora_prospect.enrichment import enrichir as _enrichir_entreprise
from fundora_prospect.models import LiquidityEvent, StatutEntreprise
from fundora_prospect.scoring import Evaluation, GrillePonderation, evaluer

# --- Bornes des parametres ----------------------------------------------------
#
# Elles vivent ici et non dans une surface : sinon la seconde surface les
# reinventerait, et deux bornes qui devraient etre egales finiraient par ne plus
# l'etre.

MOIS_MAX = 120
LIMITE_MAX = 100
LIMITE_DEFAUT = 25

# --- Plafonds de budget -------------------------------------------------------

# Annonces rapatriees avant filtrage. Au-dela, on paierait des appels API pour
# des annonces qu'on ecarterait de toute facon.
PLAFOND_ANNONCES = 600

# L'enrichissement coute un appel API par candidat : on n'enrichit que le haut
# du panier, `CANDIDATS_PAR_LEAD` fois la limite demandee.
CANDIDATS_PAR_LEAD = 2

# Plafond dur d'enrichissements par recherche.
#
# Ce nombre valait `LIMITE_MAX * 2` — le meme symbole servait donc a DEUX
# choses : borner l'argument `limite` d'un outil, et borner un budget d'appels
# API. Deux usages sous un seul nom, c'est encore un nom qui promet une chose
# et en decrit une autre ; le jour ou l'un des deux bouge, l'autre suit sans
# qu'on l'ait voulu.
#
# Les deux valent 200 aujourd'hui, et par la voie MCP ce plafond ne mord jamais
# (`limite <= LIMITE_MAX` implique `limite * 2 <= 200`). Il cesse d'etre
# decoratif des que `executer` est appele directement — par une API web, par un
# script — sans la borne d'argument du transport devant lui.
PLAFOND_ENRICHISSEMENTS = 200


# --- Vocabulaire du domaine ---------------------------------------------------


def normaliser_departements(brut: Any) -> list[str]:
    """Accepte `"06"`, `"6"`, `6`, `"06,13"` et l'alias `"PACA"`.

    Un modele ecrit indifferemment l'une de ces formes. Le zero initial se perd
    des qu'un entier passe : `6` doit redevenir `"06"`.
    """
    if brut is None:
        raise ValueError("departement manquant")
    texte = str(brut).strip()
    if texte.upper() == "PACA":
        return list(DEPARTEMENTS_PACA)

    codes: list[str] = []
    for morceau in texte.split(","):
        code = morceau.strip().upper()
        if not code:
            continue
        if code.isdigit():
            code = code.zfill(2)
        if not (
            (len(code) == 2 and code.isdigit())
            or (len(code) == 3 and code.isdigit())
            or code in {"2A", "2B"}
        ):
            raise ValueError(
                f"departement invalide : {morceau.strip()!r}. Attendu un code "
                'numerique a deux chiffres, par exemple "06" pour les '
                'Alpes-Maritimes, "13" pour les Bouches-du-Rhone. Plusieurs '
                'codes se separent par une virgule ("06,13"), et "PACA" '
                "designe toute la region."
            )
        if code not in codes:
            codes.append(code)
    if not codes:
        raise ValueError('departement vide. Exemple : "06", "06,13" ou "PACA".')
    return codes


def _fenetre(mois: int, aujourdhui: date) -> date:
    """Premier jour du mois situe `mois` mois en arriere."""
    return date(
        aujourdhui.year - (mois // 12) - (1 if aujourdhui.month <= mois % 12 else 0),
        ((aujourdhui.month - mois - 1) % 12) + 1,
        1,
    )


# --- Mise en forme -------------------------------------------------------------


def resumer(stats: dict[str, Any]) -> str:
    """Le resume est lu par un modele, puis recopie tel quel a l'utilisateur.
    Il doit donc separer ce qui a ete ECARTE — un jugement, avec son motif — de
    ce qui a seulement ete TRONQUE ou jamais examine. Sans cette separation, la
    sortie parait exhaustive alors qu'elle est amputee, et le lecteur attribue
    a la grille des refus qu'elle n'a pas prononces.

    Cette phrase est dans le coeur et non dans une surface : c'est elle qui
    porte le sens des compteurs. Une seconde surface qui ecrirait la sienne
    rouvrirait, mot pour mot, le defaut que ces compteurs ont mis trois phases
    a fermer.
    """
    morceaux = [f"{stats['annonces_publiees']} annonces publiees"]
    # Les reserves n'apparaissent que quand elles mordent : une mise en garde
    # affichee en permanence cesse d'etre lue.
    if stats["plafond_atteint"]:
        morceaux.append(
            f"{stats['annonces_rapatriees']} rapatriees seulement "
            "(plafond de rapatriement atteint)"
        )
    if stats["sans_cedant_ou_illisibles"]:
        morceaux.append(f"{stats['sans_cedant_ou_illisibles']} sans cedant ou illisibles")
    morceaux += [
        f"{stats['annonces_exploitables']} exploitables",
        # Le chiffre porte sa condition d'obtention DANS la meme phrase : il ne
        # decrit que les dossiers enrichis, pas la population exploitable.
        f"{stats['classables_parmi_les_enrichis']} classables "
        f"parmi les {stats['enrichis']} enrichis",
    ]
    morceaux += [f"{n} {motif}" for motif, n in stats["ecartes"].items()]
    resume = ", ".join(morceaux) + "."

    reserves = []
    if stats["leads_rendus"] < stats["classables_parmi_les_enrichis"]:
        reserves.append(
            f"{stats['leads_rendus']} rendus sur "
            f"{stats['classables_parmi_les_enrichis']} classables parmi les "
            f"{stats['enrichis']} enrichis (limite atteinte)"
        )
    if stats["candidats_non_enrichis"]:
        reserves.append(
            f"{stats['candidats_non_enrichis']} candidats non enrichis donc non "
            "classes, faute de budget d'appels : relancer avec une limite plus "
            "haute pour les voir"
        )
    if reserves:
        resume += " " + " ; ".join(reserves) + "."
    return resume


# --- Le pipeline ---------------------------------------------------------------


@dataclass(frozen=True)
class ResultatPipeline:
    """Les leads retenus, ET ce que la recherche n'a pas regarde.

    Meme principe que `ResultatRecherche` un etage plus bas : ne rendre que la
    liste obligerait chaque surface a presenter un sous-ensemble comme un
    total. Les compteurs voyagent donc a cote des leads, et la phrase qui leur
    donne leur sens se fabrique par `resumer`.
    """

    leads: list[dict[str, Any]]
    statistiques: dict[str, Any]
    departements: list[str]
    debut: date
    fin: date
    montant_min: float


def executer(
    *,
    departements: Sequence[str],
    mois: int = 12,
    montant_min: float = 0.0,
    limite: int = LIMITE_DEFAUT,
    aujourdhui: date | None = None,
    rechercher: Callable[..., ResultatRecherche] = _rechercher_bodacc,
    enrichir: Callable[..., Enrichissement] = _enrichir_entreprise,
) -> ResultatPipeline:
    """Le pipeline complet : des parametres de recherche a des leads scores.

    `departements` arrive deja normalise — `normaliser_departements` peut
    echouer avec un message, et c'est a la surface de decider comment ce
    message remonte a son appelant.

    `aujourdhui` est un parametre pour la meme raison que dans `evaluer` : sans
    lui, ni le pipeline ni ses tests ne seraient reproductibles.
    """
    aujourdhui = aujourdhui or date.today()
    debut = _fenetre(mois, aujourdhui)

    recherche = rechercher(
        departements=list(departements),
        depuis=debut,
        jusqu_a=aujourdhui,
        limite=PLAFOND_ANNONCES,
    )
    annonces = recherche.annonces

    ecartes: dict[str, int] = {}

    def ecarter(motif: str) -> None:
        ecartes[motif] = ecartes.get(motif, 0) + 1

    # 1. Filtrage sans appel reseau : inutile d'enrichir ce qu'on jettera.
    candidats: list[Annonce] = []
    for annonce in annonces:
        prix = annonce.prix
        if not prix.retenu:
            ecarter(str(prix.qualification).replace("_", " "))
            continue
        if prix.aberrant:
            ecarter("montant aberrant")
            continue
        if (prix.montant or 0) < montant_min:
            ecarter("sous le montant minimum")
            continue
        candidats.append(annonce)

    # 2. Pre-classement sans enrichissement, pour n'enrichir que le haut du
    #    panier : l'enrichissement coute un appel API par lead.
    #
    #    Le pre-classement utilise le SCORE PROVISOIRE, pas le montant seul.
    #    Trier sur le montant reintroduirait exactement le biais que la grille
    #    a corrige : une cession fraiche mais modeste passerait derriere une
    #    grosse cession ancienne et ne serait jamais enrichie, donc jamais
    #    rendue. Le score provisoire ignore le statut et le secteur, qui
    #    demandent l'enrichissement — mais il porte deja la fraicheur.
    grille = GrillePonderation.defaut()

    def score_provisoire(annonce: Annonce) -> float:
        provisoire = evaluer(LiquidityEvent.depuis_annonce(annonce), grille, aujourdhui=aujourdhui)
        return provisoire.score or 0.0

    candidats.sort(key=score_provisoire, reverse=True)
    a_enrichir = candidats[: min(limite * CANDIDATS_PAR_LEAD, PLAFOND_ENRICHISSEMENTS)]

    leads: list[dict[str, Any]] = []
    for annonce in a_enrichir:
        enrichissement = enrichir(annonce.cedant.siren)
        event = LiquidityEvent.depuis_annonce(annonce, enrichissement)
        evaluation = evaluer(event, grille, aujourdhui=aujourdhui)
        if not evaluation.classable:
            if event.statut_cedant is StatutEntreprise.CESSEE:
                ecarter("societe cedante cessee")
            elif event.statut_cedant is StatutEntreprise.NON_DIFFUSIBLE:
                ecarter("entreprise non diffusible INSEE")
            else:
                ecarter("non classable")
            continue

        # Porte unique de sortie : `assembler` leve si la provenance est
        # incomplete (contrainte 3). Un lead intracable sort du flux avec son
        # motif, comme n'importe quel autre refus — il n'est ni rendu sans
        # provenance, ni perdu en silence.
        try:
            lead = provenance.assembler(event, evaluation, date_collecte=aujourdhui)
        except ValidationError:
            ecarter("provenance incomplete")
            continue
        leads.append(provenance.serialiser(lead))

    leads.sort(key=lambda lead: lead["score"], reverse=True)

    # Ce compteur se prend AVANT la coupe finale — sinon une troncature se lit
    # comme un jugement de la grille : sur 115 candidats, « 25 classables » se
    # lit comme 90 refus, alors que la grille n'en a jamais vu que 50 et n'en a
    # refuse aucun.
    #
    # Mais il reste borne par la coupe AMONT `a_enrichir`, donc plafonne a
    # `CANDIDATS_PAR_LEAD * limite`. Il sature en silence des que la population
    # depasse ce budget — mesure du 2026-08-17 sur le 06, six mois, > 300 k EUR,
    # meme population : limite=5 -> 10 classables (plafond touche), limite=25 ->
    # 49, limite=50 -> 96. C'est pourquoi il s'appelle desormais
    # `classables_parmi_les_enrichis` : le nom porte sa condition d'obtention.
    # Sans elle, « classables » promet un jugement sur toute la population alors
    # qu'il compte ce que la grille a eu le DROIT de regarder.
    classables_parmi_les_enrichis = len(leads)
    leads = leads[:limite]

    statistiques = {
        # Trois populations, trois noms. `annonces_examinees` les confondait :
        # il valait `annonces_exploitables` sous un nom qui promet le total.
        # Mesure du 2026-08-16 sur le 06 : 662 / 600 / 458.
        "annonces_publiees": recherche.publiees,
        "annonces_rapatriees": recherche.rapatriees,
        "annonces_exploitables": len(annonces),
        "sans_cedant_ou_illisibles": recherche.non_exploitables,
        "plafond_atteint": recherche.plafond_atteint,
        "candidats_avant_enrichissement": len(candidats),
        "enrichis": len(a_enrichir),
        "candidats_non_enrichis": len(candidats) - len(a_enrichir),
        "classables_parmi_les_enrichis": classables_parmi_les_enrichis,
        "leads_rendus": len(leads),
        "ecartes": ecartes,
    }
    return ResultatPipeline(
        leads=leads,
        statistiques=statistiques,
        departements=list(departements),
        debut=debut,
        fin=aujourdhui,
        montant_min=montant_min,
    )


def evaluer_hypothese(
    *,
    montant_eur: float,
    date_acte: date | None = None,
    date_parution: date | None = None,
    departement: Any = "13",
    statut_cedant: StatutEntreprise = StatutEntreprise.INCONNU,
    code_ape: str | None = None,
    aujourdhui: date | None = None,
) -> Evaluation:
    """Applique la grille a une cession decrite a la main, sans recherche.

    Repond a « combien vaudrait une cession de 400 k EUR faite il y a deux
    mois ? ». L'evenement est monte ici et non dans une surface : c'est de la
    construction de domaine, et un endpoint web de simulation la recopierait
    telle quelle sinon.

    L'evenement est **hypothetique** — d'ou son identifiant. Il ne vient
    d'aucune annonce, il n'a donc pas d'URL de publication, et il ne doit
    jamais etre serialise en lead : la contrainte 3 l'interdit, et
    `provenance.assembler` le refuserait.
    """
    aujourdhui = aujourdhui or date.today()
    event = LiquidityEvent(
        id="hypothese",
        date_parution=date_parution or date_acte or aujourdhui,
        date_acte=date_acte,
        departement=normaliser_departements(departement)[0],
        url_publication="",
        montant_eur=montant_eur,
        devise="EUR",
        qualification="achat",
        retenu=True,
        code_ape=code_ape,
        statut_cedant=statut_cedant,
    )
    return evaluer(event, GrillePonderation.defaut(), aujourdhui=aujourdhui)
