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

from collections.abc import Callable, Iterable, Sequence
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

    **Deux sources, une seule phrase.** La recherche en direct connait ce que le
    BODACC a publie ; la lecture en base connait ce qu'elle a stocke. Les deux
    populations n'ont pas le meme nom, donc pas la meme condition d'obtention —
    et c'est precisement pour ca qu'elles ne doivent pas etre redigees a deux
    endroits. Les fragments changent, l'assemblage est unique.
    """
    en_direct = "annonces_publiees" in stats
    morceaux: list[str] = []
    reserves: list[str] = []

    # --- Ce que la source contenait
    #
    # Les reserves n'apparaissent que quand elles mordent : une mise en garde
    # affichee en permanence cesse d'etre lue.
    if en_direct:
        morceaux.append(f"{stats['annonces_publiees']} annonces publiees")
        if stats["plafond_atteint"]:
            morceaux.append(
                f"{stats['annonces_rapatriees']} rapatriees seulement "
                "(plafond de rapatriement atteint)"
            )
        if stats["sans_cedant_ou_illisibles"]:
            morceaux.append(f"{stats['sans_cedant_ou_illisibles']} sans cedant ou illisibles")
        morceaux.append(f"{stats['annonces_exploitables']} exploitables")
    else:
        morceaux.append(f"{stats['evenements_en_base']} evenements en base")
        # Une base ne sait pas, par elle-meme, ce qu'elle n'a pas recu. Le dire
        # est la seule facon de ne pas faire passer un stock pour un total.
        reserves.append(
            "l'etendue de la collecte n'est pas connue : aucun compteur de "
            "collecte enregistre pour cette recherche"
        )

    # --- Ce que la grille en a fait
    #
    # Le chiffre porte sa condition d'obtention DANS la meme phrase. Elle n'est
    # pas la meme des deux cotes : en direct la grille ne voit que les dossiers
    # ENRICHIS, en base elle voit tous les CANDIDATS.
    if en_direct:
        classables = stats["classables_parmi_les_enrichis"]
        morceaux.append(f"{classables} classables parmi les {stats['enrichis']} enrichis")
        portee = f"classables parmi les {stats['enrichis']} enrichis"
    else:
        classables = stats["classables"]
        morceaux.append(f"{classables} classables sur {stats['candidats']} candidats")
        portee = f"classables sur {stats['candidats']} candidats"

    morceaux += [f"{n} {motif}" for motif, n in stats["ecartes"].items()]
    resume = ", ".join(morceaux) + "."

    # --- Ce qui a ete tronque, jamais confondu avec un refus
    if stats["leads_rendus"] < classables:
        reserves.insert(
            0,
            f"{stats['leads_rendus']} rendus sur {classables} {portee} (limite atteinte)",
        )
    if stats.get("candidats_non_enrichis"):
        reserves.insert(
            1,
            f"{stats['candidats_non_enrichis']} candidats non enrichis donc non "
            "classes, faute de budget d'appels : relancer avec une limite plus "
            "haute pour les voir",
        )
    if reserves:
        resume += " " + " ; ".join(reserves) + "."
    return resume


# --- Filtrage ------------------------------------------------------------------
#
# Cette etape est partagee par les DEUX consommateurs du coeur : la recherche
# en direct, et le job de collecte qui alimentera la base. Elle est donc isolee
# ici plutot que recopiee dans chacun.
#
# Ce qui divergerait autrement n'est pas la boucle — trois `if`, personne ne se
# trompe dessus — c'est le **vocabulaire des motifs** et l'**ordre des tests**.
# Un motif ecrit « apport en nature » d'un cote et « apport » de l'autre casse
# tout comptage qui agrege les deux sources, sans qu'aucun test ne rougisse. Et
# l'ordre decide quel motif est compte quand une annonce en cumule plusieurs :
# un apport a 3 000 EUR est un apport, pas un montant insuffisant.
#
# Ce vocabulaire n'etait garde par AUCUN test avant l'extraction : une mutation
# remplacant le motif par un mot quelconque laissait les 436 tests verts. Voir
# `tests/test_pipeline.py`, ecrit en meme temps que cette section.


def motif_ecart_faits(
    *,
    retenu: bool,
    aberrant: bool,
    qualification: str,
    montant: float | None,
    montant_min: float = 0.0,
) -> str | None:
    """**Le seul endroit ou un motif de refus se decide.**

    Ne prend que des faits, pas un type porteur : le meme refus doit se nommer
    identiquement qu'on parte d'une `Annonce` fraiche du BODACC ou d'un
    `LiquidityEvent` relu en base. Ce sont deux types differents portant les
    memes faits, et deux fonctions qui les traiteraient separement finiraient
    par diverger sur un mot.

    L'ordre des tests est significatif : le premier motif rencontre est celui
    qui sera compte. Il va de la qualite de la donnee vers le critere
    commercial, du plus structurel au plus reglable.
    """
    if not retenu:
        return str(qualification).replace("_", " ")
    if aberrant:
        return "montant aberrant"
    if (montant or 0) < montant_min:
        # Seul motif de ce bloc qui depende d'un parametre et non du fait.
        # Le job de collecte appelle donc avec `montant_min=0` : le seuil est
        # un filtre de LECTURE, sinon le relever imposerait une recollecte.
        return "sous le montant minimum"
    return None


def motif_ecart(annonce: Annonce, montant_min: float = 0.0) -> str | None:
    """Adaptateur cote collecte : une `Annonce` fraiche du BODACC."""
    prix = annonce.prix
    return motif_ecart_faits(
        retenu=prix.retenu,
        aberrant=prix.aberrant,
        qualification=str(prix.qualification),
        montant=prix.montant,
        montant_min=montant_min,
    )


def motif_ecart_evenement(event: LiquidityEvent, montant_min: float = 0.0) -> str | None:
    """Adaptateur cote lecture : un `LiquidityEvent` relu en base."""
    return motif_ecart_faits(
        retenu=event.retenu,
        aberrant=event.aberrant,
        qualification=event.qualification,
        montant=event.montant_eur,
        montant_min=montant_min,
    )


def repartir(
    annonces: Sequence[Annonce], *, montant_min: float = 0.0
) -> tuple[list[Annonce], dict[str, int]]:
    """Separe les candidats des ecartes, et compte ces derniers par motif.

    Le decompte est rendu **modifiable** : l'appelant y ajoute les refus de ses
    propres etapes — statut de la societe cedante, provenance incomplete — qui
    n'existent qu'apres un appel reseau et ne sont donc pas partageables ici.
    """
    candidats: list[Annonce] = []
    ecartes: dict[str, int] = {}
    for annonce in annonces:
        motif = motif_ecart(annonce, montant_min)
        if motif is None:
            candidats.append(annonce)
        else:
            ecartes[motif] = ecartes.get(motif, 0) + 1
    return candidats, ecartes


# --- Classement : l'etape partagee par la recherche et la lecture --------------


def classer(
    evenements: Iterable[LiquidityEvent],
    *,
    grille: GrillePonderation,
    aujourdhui: date,
    limite: int,
    ecartes: dict[str, int],
    date_collecte_de: Callable[[LiquidityEvent], date],
) -> tuple[list[dict[str, Any]], int]:
    """Score, filtre sur le statut, trace, trie, tronque. Rend les leads rendus
    et le nombre de classables **avant** la coupe.

    Partage par les deux consommateurs, pour la meme raison que `motif_ecart` :
    ce qui divergerait n'est pas la boucle, ce sont les motifs de refus du
    statut, l'ordre de tri, et le fait que la sortie passe par
    `provenance.serialiser`. Trois choses qu'une seconde implementation
    retrouverait « presque » identiques.

    `date_collecte_de` n'est pas une commodite. A la collecte, la date de
    collecte est le jour meme ; en lecture, elle vient de la base. Coder
    `aujourdhui` en dur ici ferait mentir la provenance de tout lead relu — il
    annoncerait une consultation du BODACC qui n'a pas eu lieu.
    """

    def ecarter(motif: str) -> None:
        ecartes[motif] = ecartes.get(motif, 0) + 1

    leads: list[dict[str, Any]] = []
    for event in evenements:
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
            lead = provenance.assembler(
                event, evaluation, date_collecte=date_collecte_de(event)
            )
        except ValidationError:
            ecarter("provenance incomplete")
            continue
        leads.append(provenance.serialiser(lead))

    leads.sort(key=lambda lead: lead["score"], reverse=True)
    return leads[:limite], len(leads)


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

    # 1. Filtrage sans appel reseau : inutile d'enrichir ce qu'on jettera.
    candidats, ecartes = repartir(annonces, montant_min=montant_min)

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

    evenements = (
        LiquidityEvent.depuis_annonce(annonce, enrichir(annonce.cedant.siren))
        for annonce in a_enrichir
    )
    leads, classables = classer(
        evenements,
        grille=grille,
        aujourdhui=aujourdhui,
        limite=limite,
        ecartes=ecartes,
        # A la collecte, la date de collecte EST aujourd'hui : on vient
        # d'interroger le BODACC. En lecture ce n'est plus vrai, d'ou le
        # parametre.
        date_collecte_de=lambda _: aujourdhui,
    )

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
    classables_parmi_les_enrichis = classables

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


# --- La lecture ----------------------------------------------------------------


@dataclass(frozen=True)
class ResultatLecture:
    """Ce que la base contenait, ET ce que le classement en a fait.

    Meme principe que `ResultatPipeline` et `ResultatRecherche` : ne rendre que
    la liste obligerait le lecteur a presenter un sous-ensemble comme un total.
    """

    leads: list[dict[str, Any]]
    statistiques: dict[str, Any]
    montant_min: float


def lire(
    evenements: Sequence[Any],
    *,
    montant_min: float = 0.0,
    limite: int = LIMITE_DEFAUT,
    aujourdhui: date | None = None,
    grille: GrillePonderation | None = None,
    collecte: dict[str, Any] | None = None,
) -> ResultatLecture:
    """Classe des faits deja stockes. **Aucun appel reseau.**

    `evenements` sont des `entrepot.EvenementStocke` : un fait, et la date a
    laquelle il a ete constate. Ils arrivent en parametre plutot que par un
    import, comme `rechercher` et `enrichir` dans `executer` — le coeur ne
    connait pas SQLite.

    **Le score est recalcule ici, a chaque lecture.** La fraicheur decroit des
    le premier jour : deux lectures a deux dates rendent deux scores, et c'est
    la propriete qui justifie de ne rien figer en base.

    `collecte` porte, quand il est connu, ce que la source contenait — les
    compteurs ecrits par le job. Absent, le resume le dit au lieu d'inventer un
    total : une base ne sait pas, par elle-meme, ce qu'elle n'a pas recu.
    """
    aujourdhui = aujourdhui or date.today()
    grille = grille or GrillePonderation.defaut()

    # Meme fonction de vocabulaire qu'a la collecte : `motif_ecart_faits` via
    # son adaptateur. Un second endroit qui nommerait « sous le montant
    # minimum » autrement casserait tout comptage agregeant les deux sources.
    candidats: list[Any] = []
    ecartes: dict[str, int] = {}
    for stocke in evenements:
        motif = motif_ecart_evenement(stocke.event, montant_min)
        if motif is None:
            candidats.append(stocke)
        else:
            ecartes[motif] = ecartes.get(motif, 0) + 1

    dates = {stocke.event.id: stocke.date_collecte for stocke in candidats}
    leads, classables = classer(
        (stocke.event for stocke in candidats),
        grille=grille,
        aujourdhui=aujourdhui,
        limite=limite,
        ecartes=ecartes,
        # La provenance date de la COLLECTE, pas de la lecture.
        date_collecte_de=lambda event: dates[event.id],
    )

    statistiques: dict[str, Any] = {
        "evenements_en_base": len(evenements),
        "candidats": len(candidats),
        "classables": classables,
        "leads_rendus": len(leads),
        "ecartes": ecartes,
    }
    if collecte:
        statistiques.update(collecte)

    return ResultatLecture(
        leads=leads, statistiques=statistiques, montant_min=montant_min
    )
