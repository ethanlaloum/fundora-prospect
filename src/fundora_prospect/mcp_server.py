"""Serveur MCP en stdio — la surface Claude Code du pipeline.

C'est ce serveur que Claude Code appelle quand on ecrit en langage naturel
« trouve-moi les cessions de plus de 300 k EUR dans le 06 sur 6 mois ».

**Ce module ne fait que de la traduction MCP.** Le pipeline lui-meme vit dans
`fundora_prospect.pipeline` : il a une seconde surface a alimenter (une API
web), et un pipeline recopie dans deux transports finit toujours par diverger.
Restent ici les trois choses qui appartiennent vraiment au protocole : la
declaration des outils, la normalisation des arguments qu'un modele ecrit, et
la mise en forme de la reponse.

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

**`rechercher` et `enrichir` sont importes ici pour etre PASSES au pipeline.**
Ce module est la racine de composition de la surface MCP : c'est lui qui
choisit les deux ports par lesquels le pipeline sort de la machine. C'est aussi
ce qui permet a `tests/test_mcp_server.py` de les substituer sans toucher au
transport.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from mcp.server import MCPServer

from fundora_prospect import __version__, pipeline
from fundora_prospect.bodacc import rechercher
from fundora_prospect.enrichment import enrichir, siren_valide
from fundora_prospect.models import StatutEntreprise, presenter_evaluation
from fundora_prospect.pipeline import (
    LIMITE_DEFAUT,
    LIMITE_MAX,
    MOIS_MAX,
    borne,
    normaliser_departements,
)

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
#
# Ce qui reste ici est propre au transport : un modele ecrit `6` la ou le
# schema JSON attend `"06"`, et un message d'erreur lisible est un message qui
# lui permet de se corriger seul. Le vocabulaire du domaine — codes de
# departement, alias « PACA » — est descendu dans le pipeline.


def _date(brut: str | None, nom: str) -> date | None:
    if brut in (None, ""):
        return None
    try:
        return date.fromisoformat(str(brut))
    except ValueError as exc:
        raise ValueError(
            f"{nom} illisible : {brut!r}. Format attendu AAAA-MM-JJ, par exemple 2026-07-01."
        ) from exc


# --- Outils --------------------------------------------------------------------
#
# Les descriptions sont des CONSTANTES DE MODULE, pas des litteraux dans le
# decorateur. Elles sont du prompt, et une seconde surface les consomme :
# `agent.py` declare le meme outil a l'API Anthropic, qui ne sait rien du MCP.
# Les recopier la-bas ferait deux prompts qui divergent sur un mot — et le mot
# qui derive serait, ici, celui qui oriente le modele vers `"06"` plutot que
# `6`. Un test compare les deux declarations.

DESCRIPTION_RECHERCHE = (
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


@serveur.tool(description=DESCRIPTION_RECHERCHE)
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
    mois = borne(mois, "mois", 1, MOIS_MAX)
    limite = borne(limite, "limite", 1, LIMITE_MAX)
    if montant_min < 0:
        raise ValueError(f"montant_min doit etre positif, recu {montant_min}")

    resultat = pipeline.executer(
        departements=departements,
        mois=mois,
        montant_min=montant_min,
        limite=limite,
        # Les deux ports, choisis par cette surface. Voir l'entete du module.
        rechercher=rechercher,
        enrichir=enrichir,
    )

    return {
        "resume": pipeline.resumer(resultat.statistiques),
        "departements": resultat.departements,
        "periode": {"debut": resultat.debut.isoformat(), "fin": resultat.fin.isoformat()},
        "montant_min_eur": resultat.montant_min,
        "statistiques": resultat.statistiques,
        "leads": resultat.leads,
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
    try:
        statut = StatutEntreprise(statut_cedant)
    except ValueError as exc:
        attendus = ", ".join(s.value for s in StatutEntreprise)
        raise ValueError(
            f"statut_cedant invalide : {statut_cedant!r}. Attendu l'un de : {attendus}."
        ) from exc

    return presenter_evaluation(
        pipeline.evaluer_hypothese(
            montant_eur=montant_eur,
            date_acte=_date(date_acte, "date_acte"),
            date_parution=_date(date_parution, "date_parution"),
            departement=departement,
            statut_cedant=statut,
            code_ape=code_ape,
        )
    )


def main() -> None:
    """Point d'entree stdio, appele par `.mcp.json`."""
    serveur.run(transport="stdio")


if __name__ == "__main__":
    main()
