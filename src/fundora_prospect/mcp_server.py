"""Serveur MCP en stdio — le point d'entree du plugin.

C'est ce serveur que Claude Code appelle quand on ecrit en langage naturel
« trouve-moi les cessions de plus de 300 k EUR dans le 06 sur 6 mois ».

**Decoupage assume.** La specification listait trois outils granulaires
(`search`, `enrich`, `score`). Pris a la lettre, il faudrait que le modele
appelle `search`, puis `enrich` pour chaque SIREN, puis `score` pour chaque
evenement : des dizaines d'allers-retours, lents et indemontrables en direct.
`search_liquidity_events` execute donc **le pipeline complet** et rend des
leads deja scores. Les deux autres outils restent exposes pour inspecter un
cas isole — ce qui rend la demo scenarisable en deux temps.

**Les descriptions d'outils sont du prompt, pas de la documentation.** C'est ce
que le modele lit pour decider quoi appeler et avec quoi. Elles disent le
format attendu (`"06"` et non `6`, le zero initial se perd sur un entier), les
unites, et le fait que les resultats sortent deja tries.

**La sortie porte les motifs de refus**, pas seulement les leads retenus.
L'auditabilite construite depuis la Phase 1 doit etre visible dans le transport
MCP, sinon elle n'existe que dans les tests.

**Les leads sortent par `provenance.serialiser`, jamais par un dict monte a la
main.** Ce module a longtemps construit lui-meme la charge utile, et elle ne
portait qu'un des quatre champs de tracabilite exiges par la contrainte 3. La
porte unique est ce qui rend la contrainte verifiable ici.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from mcp.server import MCPServer
from pydantic import ValidationError

from fundora_prospect import __version__, provenance
from fundora_prospect.bodacc import DEPARTEMENTS_PACA, Annonce, rechercher
from fundora_prospect.enrichment import enrichir, siren_valide
from fundora_prospect.models import LiquidityEvent, StatutEntreprise
from fundora_prospect.scoring import GrillePonderation, evaluer

MOIS_MAX = 120
LIMITE_MAX = 100
LIMITE_DEFAUT = 25

# Plafond d'annonces rapatriees avant filtrage. Au-dela, on paierait des appels
# API pour des annonces qu'on ecarterait de toute facon.
PLAFOND_ANNONCES = 600

serveur = MCPServer(
    name="fundora-prospect",
    version=__version__,
    instructions=(
        "Detecte des prospects investisseurs a partir des publications legales "
        "du BODACC : cessions de fonds de commerce avec prix de vente. "
        "Le prospect est la SOCIETE CEDANTE, celle qui encaisse — pas "
        "l'acquereur, et pas les dirigeants. Aucune donnee n'est collectee "
        "ailleurs que sur deux APIs publiques francaises."
    ),
)


# --- Normalisation des parametres --------------------------------------------


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


def _borne(valeur: int, nom: str, minimum: int, maximum: int) -> int:
    if not isinstance(valeur, int) or isinstance(valeur, bool):
        raise ValueError(f"{nom} doit etre un entier, recu {valeur!r}")
    if not (minimum <= valeur <= maximum):
        raise ValueError(f"{nom} doit etre compris entre {minimum} et {maximum}, recu {valeur}")
    return valeur


def _date(brut: str | None, nom: str) -> date | None:
    if brut in (None, ""):
        return None
    try:
        return date.fromisoformat(str(brut))
    except ValueError as exc:
        raise ValueError(
            f"{nom} illisible : {brut!r}. Format attendu AAAA-MM-JJ, par exemple 2026-07-01."
        ) from exc


# --- Mise en forme -------------------------------------------------------------


def _resume(stats: dict[str, Any]) -> str:
    """Le resume est lu par un modele, puis recopie tel quel a l'utilisateur.
    Il doit donc separer ce qui a ete ECARTE — un jugement, avec son motif — de
    ce qui a seulement ete TRONQUE ou jamais examine. Sans cette separation, la
    sortie parait exhaustive alors qu'elle est amputee, et le lecteur attribue
    a la grille des refus qu'elle n'a pas prononces.
    """
    morceaux = [
        f"{stats['annonces_examinees']} annonces examinees",
        f"{stats['leads_classables']} classables",
    ]
    morceaux += [f"{n} {motif}" for motif, n in stats["ecartes"].items()]
    resume = ", ".join(morceaux) + "."

    reserves = []
    if stats["leads_rendus"] < stats["leads_classables"]:
        reserves.append(
            f"{stats['leads_rendus']} rendus sur {stats['leads_classables']} "
            "classables (limite atteinte)"
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


# --- Outils --------------------------------------------------------------------


@serveur.tool(
    description=(
        "Recherche les cessions de fonds de commerce publiees au BODACC et rend "
        "des leads DEJA SCORES et tries, du meilleur au moins bon. Execute tout "
        "le pipeline : recherche, extraction du prix, identification du cedant, "
        "verification que la societe cedante est toujours active, et scoring "
        "explicable.\n\n"
        "Le prospect rendu est la SOCIETE CEDANTE — celle qui vient d'encaisser "
        "le produit de la vente.\n\n"
        "Parametres :\n"
        '- departement : code a deux chiffres entre guillemets, par exemple "06" '
        'pour les Alpes-Maritimes ou "13" pour les Bouches-du-Rhone. Ecrire "6" '
        "fonctionne aussi. Plusieurs departements se separent par une virgule "
        '("06,13"). L\'alias "PACA" couvre toute la region.\n'
        "- mois : profondeur de la recherche en mois glissants (defaut 12).\n"
        "- montant_min : prix de cession minimum en euros (defaut 0).\n"
        "- limite : nombre maximum de leads rendus (defaut 25, maximum 100).\n\n"
        "La reponse contient aussi le decompte des annonces ecartees AVEC LEUR "
        "MOTIF : apport en nature, devise obsolete, societe cedante radiee, acte "
        "trop ancien. Ces refus font partie du resultat.\n\n"
        "Chaque lead porte un bloc `provenance` : source, date de collecte, URL "
        "de l'annonce publiee, et le segment concerne. Les cedants personne "
        "physique relevent d'un segment distinct de la prospection B2B — le "
        "bloc le dit, et cette distinction doit etre conservee si les leads "
        "sont recopies ou resumes."
    )
)
def search_liquidity_events(
    # `str | int` et non `str` : le schema JSON refuserait un entier AVANT
    # d'atteindre la normalisation, et un modele ecrit parfois `6` pour le
    # departement. La description l'oriente vers la forme "06" ; le type le
    # rattrape s'il ne suit pas.
    departement: str | int,
    mois: int = 12,
    montant_min: float = 0.0,
    limite: int = LIMITE_DEFAUT,
) -> dict[str, Any]:
    departements = normaliser_departements(departement)
    mois = _borne(mois, "mois", 1, MOIS_MAX)
    limite = _borne(limite, "limite", 1, LIMITE_MAX)
    if montant_min < 0:
        raise ValueError(f"montant_min doit etre positif, recu {montant_min}")

    aujourdhui = date.today()
    debut = date(
        aujourdhui.year - (mois // 12) - (1 if aujourdhui.month <= mois % 12 else 0),
        ((aujourdhui.month - mois - 1) % 12) + 1,
        1,
    )

    annonces = rechercher(
        departements=departements,
        depuis=debut,
        jusqu_a=aujourdhui,
        limite=PLAFOND_ANNONCES,
    )

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
    a_enrichir = candidats[: min(limite * 2, LIMITE_MAX * 2)]

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

    # `classables` se compte AVANT la coupe. Compter apres ferait passer une
    # troncature pour un jugement de la grille : sur 115 candidats, « 25
    # classables » se lit comme 90 refus, alors que la grille n'en a jamais vu
    # que 50 et n'en a refuse aucun.
    classables = len(leads)
    leads = leads[:limite]

    statistiques = {
        "annonces_examinees": len(annonces),
        "candidats_avant_enrichissement": len(candidats),
        "enrichis": len(a_enrichir),
        "candidats_non_enrichis": len(candidats) - len(a_enrichir),
        "leads_classables": classables,
        "leads_rendus": len(leads),
        "ecartes": ecartes,
    }
    return {
        "resume": _resume(statistiques),
        "departements": departements,
        "periode": {"debut": debut.isoformat(), "fin": aujourdhui.isoformat()},
        "montant_min_eur": montant_min,
        "statistiques": statistiques,
        "leads": leads,
    }


@serveur.tool(
    description=(
        "Verifie l'etat d'une entreprise par son SIREN aupres de "
        "recherche-entreprises.api.gouv.fr. Rend son statut administratif et "
        "son code APE.\n\n"
        "Le statut est le signal le plus decisif du projet : une societe ACTIVE "
        "a encore la tresorerie de cession a son bilan, c'est le prospect. Une "
        "societe CESSEE a distribue ce cash a ses associes, ce n'est plus un "
        "prospect.\n\n"
        "SIREN : neuf chiffres, avec ou sans espaces.\n"
        "Utiliser cet outil pour inspecter un cas isole ; "
        "search_liquidity_events le fait deja pour chaque lead qu'il rend."
    )
)
def enrich_company(siren: str) -> dict[str, Any]:
    compact = "".join(str(siren or "").split())
    if not siren_valide(compact):
        raise ValueError(
            f"SIREN invalide : {siren!r}. Attendu neuf chiffres, "
            'par exemple "852872563" ou "852 872 563".'
        )
    enrichissement = enrichir(compact)
    return {
        "siren": enrichissement.siren,
        "statut": str(enrichissement.statut),
        "exploitable": enrichissement.exploitable,
        "code_ape": enrichissement.code_ape,
        "section_ape": enrichissement.section_ape,
        "code_ape_naf25": enrichissement.code_ape_naf25,
        "motif": enrichissement.motif,
    }


@serveur.tool(
    description=(
        "Applique la grille de ponderation a une cession decrite explicitement, "
        "et rend le score sur 100 AVEC le detail de chaque point attribue.\n\n"
        "Utile pour repondre a « combien vaudrait une cession de 400 k EUR faite "
        "il y a deux mois ? » sans lancer de recherche.\n\n"
        "Attention : ce n'est PAS un modele predictif. Les poids sont des "
        "hypotheses commerciales a dire d'expert, sans donnee de conversion "
        "pour les calibrer.\n\n"
        "Parametres :\n"
        "- montant_eur : prix de cession en euros.\n"
        "- date_acte : date de l'acte au format AAAA-MM-JJ. C'est de cette date "
        "que part la fraicheur, pas de la date de publication.\n"
        '- departement : code a deux chiffres, par exemple "06".\n'
        "- statut_cedant : active, cessee, non_diffusible ou inconnu "
        "(defaut inconnu, ce qui n'empeche pas le scoring)."
    )
)
def score_lead(
    montant_eur: float,
    date_acte: str | None = None,
    date_parution: str | None = None,
    departement: str | int = "13",
    statut_cedant: str = "inconnu",
    code_ape: str | None = None,
) -> dict[str, Any]:
    acte = _date(date_acte, "date_acte")
    parution = _date(date_parution, "date_parution") or acte or date.today()
    try:
        statut = StatutEntreprise(statut_cedant)
    except ValueError as exc:
        attendus = ", ".join(s.value for s in StatutEntreprise)
        raise ValueError(
            f"statut_cedant invalide : {statut_cedant!r}. Attendu l'un de : {attendus}."
        ) from exc

    event = LiquidityEvent(
        id="score_lead",
        date_parution=parution,
        date_acte=acte,
        departement=normaliser_departements(departement)[0],
        url_publication="",
        montant_eur=montant_eur,
        devise="EUR",
        qualification="achat",
        retenu=True,
        code_ape=code_ape,
        statut_cedant=statut,
    )
    evaluation = evaluer(event, GrillePonderation.defaut(), aujourdhui=date.today())
    return {
        "classable": evaluation.classable,
        "score": evaluation.score,
        "motif_refus": evaluation.motif_refus,
        "breakdown": [
            {"critere": c.critere, "points": c.points, "poids": c.poids, "motif": c.motif}
            for c in evaluation.contributions
        ],
    }


def main() -> None:
    """Point d'entree stdio, appele par `.mcp.json`."""
    serveur.run(transport="stdio")


if __name__ == "__main__":
    main()
