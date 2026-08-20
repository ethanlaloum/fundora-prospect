"""La troisieme voie : le meme coeur, orchestre par l'API Anthropic.

## Trois voies sur un seul coeur

    1. Claude Code + plugin MCP     mcp_server.py
    2. HTTP direct, sans IA          api.py  ->  GET /leads
    3. API Anthropic en tool use     ce module  ->  POST /recherche

Les trois appellent `pipeline.executer`. **Le comparatif est le livrable** : ce
module n'existe pas pour remplacer les deux autres mais pour qu'on puisse
mesurer ce qui les separe — latence, tokens, et surtout si l'ensemble des leads
rendus est le meme.

**Pas de MCP ici.** Le serveur MCP du projet parle en stdio ; l'API Anthropic ne
peut pas l'atteindre. Les outils sont donc declares en JSON dans l'appel, et
quand le modele en demande un, on appelle `pipeline.executer` dans ce processus.
Aucun plugin, aucun Claude Code sur ce chemin.

## Claude orchestre et commente, il ne calcule jamais

La reponse porte deux choses SEPAREES :

- `outil` — la sortie structuree du pipeline. C'est ce que le front affiche.
- `analyse` — le texte du modele. Affiche a part, jamais source d'un chiffre.

`outil` n'est pas reconstruit a partir de ce que le modele a dit : c'est
l'objet rendu par `pipeline.executer`, tel quel. Si un seul nombre affiche
venait de la prose, toute l'auditabilite du projet tomberait — un score
paraphrase par un modele n'est plus reproductible.

Le test central le prouve **par l'absurde** : on substitue un client qui rend
une prose deliberement fausse — memes grandeurs, valeurs absurdes — et on exige
que `outil` ne bouge pas d'un octet. Ce n'est pas une assertion de presence,
c'est une assertion d'immobilite.

## L'identite ne quitte jamais la machine

`cedant_denomination` **est** un nom de personne sur ~20 % des cedants
(contrainte 4). Le SQLite vit hors du depot et l'API ecoute sur 127.0.0.1 pour
cette raison ; envoyer les leads entiers a un tiers annulerait la decision.

Le modele recoit donc `id` + FAITS, jamais l'identite. Il rend `par_lead[id]`,
et le recollage se fait ici. La selection se fait par **liste blanche** de
champs — jamais par liste noire : un champ ajoute demain au lead ne partirait
pas par defaut, il faudrait l'inscrire. C'est la meme regle que l'anonymisation
des fixtures, et pour la meme raison.

Un test lit le prompt **COMPLET** — systeme, outils, messages, resultats
d'outil — et echoue si une denomination ou un SIREN du corpus y figure. Le
limiter au bloc de donnees laisserait fuir un nom par le texte systeme ou par
une description d'outil.

## Ce que le modele n'apporte pas encore

Sa vraie valeur ajoutee serait d'analyser le TEXTE LIBRE que le parser ignore
(`origineFonds`, `acte.descriptif`, `activite`). Ce n'est pas fait ici, et le
motif est ecrit dans CLAUDE.md : ces champs ne sont pas en base, et deux d'entre
eux portent des noms de personnes. L'analyse porte donc sur les faits deja
etablis. Le comparatif des trois voies est le livrable ; la profondeur de
l'analyse est la suite.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from fundora_prospect import pipeline
from fundora_prospect.bodacc import rechercher
from fundora_prospect.enrichment import enrichir
from fundora_prospect.mcp_server import DESCRIPTION_RECHERCHE
from fundora_prospect.pipeline import (
    LIMITE_DEFAUT,
    LIMITE_MAX,
    MOIS_MAX,
    borne,
    normaliser_departements,
)

# Le modele et l'effort sont des PARAMETRES, avec ces valeurs en defaut. Ils
# vivent ici et pas dans le code d'appel pour la meme raison que les poids de la
# grille vivent dans un fichier : ils se recalibrent, et ca ne doit pas etre une
# modification du pipeline.
MODELE_DEFAUT = "claude-opus-5"
EFFORT_DEFAUT = "low"

# Le thinking reste ADAPTATIF — c'est le defaut du modele, on ne le desactive
# pas. Thinking coupe, Claude ecrit parfois l'appel d'outil dans son texte au
# lieu d'emettre un bloc `tool_use` : le tour reussit, l'appel ne part jamais,
# aucune erreur ne remonte. Sur une boucle d'outil, c'est le pire mode de
# defaillance possible. Le cout se regle par l'effort, pas en coupant.
#
# `max_tokens` borne le thinking ET le texte ensemble : de la marge, sinon
# l'analyse est tronquee au milieu d'une phrase.
MAX_TOKENS = 16_000

# Au-dela, on arrete et on degrade. Un modele qui rappelle l'outil quatre fois
# n'a pas compris la question ; continuer coute des tokens sans rien apporter.
TOURS_MAX = 4

# --- Ce qui part chez Anthropic — LISTE BLANCHE ---------------------------------
#
# Ni `cedant`, ni `siren`, ni `provenance` (qui porte l'URL de publication).
# Ajouter un champ ici est une decision ; en ajouter un au lead ne l'y fait pas
# entrer. C'est ce sens-la qui compte.
CHAMPS_TRANSMIS = (
    "id",
    "score",
    "montant_eur",
    "jours_ecoules",
    "date_reference",
    "departement",
    "type_cedant",
    "statut_cedant",
    "code_ape",
    "section_ape",
)

SYSTEME = (
    "Tu analyses des cessions de fonds de commerce publiees au BODACC, pour un "
    "conseiller en investissement qui demarche les societes cedantes.\n\n"
    "REGLES ABSOLUES :\n"
    "1. Appelle l'outil `search_liquidity_events` pour obtenir les donnees. Ne "
    "reponds jamais de memoire.\n"
    "2. Ne recopie AUCUN chiffre dans ton texte : ni score, ni montant, ni "
    "compteur. Ils sont affiches a l'utilisateur a partir de la sortie de "
    "l'outil, et un chiffre recopie serait un chiffre qui peut diverger. "
    "Ecris ce que les chiffres SIGNIFIENT, pas les chiffres.\n"
    "3. Tu ne recois deliberement ni raison sociale ni SIREN. N'en invente "
    "aucun, et ne demande pas a les obtenir : designe chaque cas par son `id`.\n"
    "4. Pour chaque cas, deux lignes maximum : ce qui en fait un prospect, et "
    "la reserve a garder en tete. En francais, sans emphase commerciale."
)

SCHEMA_ANALYSE = {
    "type": "object",
    "properties": {
        "synthese": {
            "type": "string",
            "description": "Deux a quatre phrases sur l'ensemble des cas rendus.",
        },
        "par_lead": {
            "type": "array",
            "description": "Une entree par cas analyse, designe par son id.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "analyse": {"type": "string"},
                },
                "required": ["id", "analyse"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["synthese", "par_lead"],
    "additionalProperties": False,
}

OUTILS = [
    {
        # La description vient de `mcp_server`, elle n'est pas recopiee : deux
        # prompts pour un meme outil finiraient par diverger sur un mot.
        "name": "search_liquidity_events",
        "description": DESCRIPTION_RECHERCHE,
        "input_schema": {
            "type": "object",
            "properties": {
                "departement": {"type": "string"},
                "mois": {"type": "integer", "minimum": 1, "maximum": MOIS_MAX},
                "montant_min": {"type": "number", "minimum": 0},
                "limite": {"type": "integer", "minimum": 1, "maximum": LIMITE_MAX},
            },
            "required": ["departement"],
            "additionalProperties": False,
        },
    }
]


# --- Ce que le module rend -------------------------------------------------------


@dataclass(frozen=True)
class Mesure:
    """De quoi comparer cette voie a la voie directe.

    Aucun cout en euros : un tarif recopie dans le code est un chiffre qui
    survit a sa source — le defaut signature de ce projet. Les tokens sont
    mesures, le tarif est public.
    """

    modele: str
    duree_ms: int
    tokens_entree: int = 0
    tokens_sortie: int = 0
    tokens_cache_lus: int = 0
    tours: int = 0
    # Les parametres que le modele a REELLEMENT passes a l'outil. S'ils
    # different de ceux demandes, l'ensemble des leads change — « un tri en
    # amont est un filtre », applique cette fois a un modele.
    appels_outil: list[dict[str, Any]] = field(default_factory=list)
    ids_rendus: list[str] = field(default_factory=list)

    def en_dict(self) -> dict[str, Any]:
        return {
            "modele": self.modele,
            "duree_ms": self.duree_ms,
            "tokens_entree": self.tokens_entree,
            "tokens_sortie": self.tokens_sortie,
            "tokens_cache_lus": self.tokens_cache_lus,
            "tours": self.tours,
            "appels_outil": self.appels_outil,
            "ids_rendus": self.ids_rendus,
        }


@dataclass(frozen=True)
class Analyse:
    """Le texte du modele. `disponible` a faux n'est pas une erreur : c'est la
    degradation propre — on perd l'analyse, pas les leads ni le classement."""

    disponible: bool
    synthese: str = ""
    par_lead: dict[str, str] = field(default_factory=dict)
    reserve: str | None = None

    def en_dict(self) -> dict[str, Any]:
        return {
            "disponible": self.disponible,
            "synthese": self.synthese,
            "par_lead": self.par_lead,
            "reserve": self.reserve,
        }


@dataclass(frozen=True)
class ResultatAgent:
    outil: dict[str, Any]
    analyse: Analyse
    mesure: Mesure

    def en_dict(self) -> dict[str, Any]:
        return {
            "outil": self.outil,
            "analyse": self.analyse.en_dict(),
            "mesure": self.mesure.en_dict(),
        }


# --- Le port : le client Anthropic ------------------------------------------------


def client_par_defaut() -> Any:
    """Le vrai client, construit tard.

    L'import est dans la fonction pour que le module s'importe sans le SDK —
    `anthropic` est un extra, comme `fastapi`. Le plugin Claude Code n'en a pas
    besoin, et le coeur encore moins.

    La clef vient de `ANTHROPIC_API_KEY`, jamais du depot et jamais du front :
    le navigateur ne parle qu'a `/api`.
    """
    import anthropic

    return anthropic.Anthropic()


# --- L'outil, execute ici ----------------------------------------------------------


def executer_recherche(
    arguments: dict[str, Any],
    *,
    aujourdhui: date | None = None,
    executer: Callable[..., Any] = pipeline.executer,
) -> dict[str, Any]:
    """Ce que le modele appelle. Meme validation que la surface MCP.

    Les arguments viennent d'un modele : ils peuvent etre absents, hors bornes
    ou du mauvais type. `borne` et `normaliser_departements` levent un message
    lisible, et ce message repart au modele comme resultat d'outil en erreur —
    c'est ce qui lui permet de se corriger seul.
    """
    departements = normaliser_departements(arguments.get("departement", "PACA"))
    mois = borne(int(arguments.get("mois", 12)), "mois", 1, MOIS_MAX)
    limite = borne(int(arguments.get("limite", LIMITE_DEFAUT)), "limite", 1, LIMITE_MAX)
    montant_min = float(arguments.get("montant_min", 0.0))
    if montant_min < 0:
        raise ValueError(f"montant_min doit etre positif, recu {montant_min}")

    resultat = executer(
        departements=departements,
        mois=mois,
        montant_min=montant_min,
        limite=limite,
        aujourdhui=aujourdhui,
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


def faits_pour_le_modele(sortie: dict[str, Any]) -> dict[str, Any]:
    """La sortie de l'outil, reduite aux champs de la LISTE BLANCHE.

    Les statistiques passent entieres : ce sont des compteurs de population, ils
    ne designent personne. Les leads, eux, sont filtres champ par champ.
    """
    return {
        "resume": sortie["resume"],
        "statistiques": sortie["statistiques"],
        "leads": [
            {cle: lead[cle] for cle in CHAMPS_TRANSMIS if cle in lead}
            for lead in sortie["leads"]
        ],
    }


# --- La boucle -----------------------------------------------------------------------


def _cumuler(compteurs: dict[str, int], usage: Any) -> None:
    """Les tokens s'additionnent sur TOUS les tours, pas seulement le dernier.

    Ne lire que la derniere reponse sous-estimerait le cout de la voie d'un
    facteur egal au nombre d'allers-retours — c'est-a-dire exactement ce que le
    comparatif doit mesurer.
    """
    compteurs["entree"] += getattr(usage, "input_tokens", 0) or 0
    compteurs["sortie"] += getattr(usage, "output_tokens", 0) or 0
    compteurs["cache"] += getattr(usage, "cache_read_input_tokens", 0) or 0


def _demande(departements: Sequence[str], mois: int, montant_min: float, limite: int) -> str:
    return (
        f"Cherche les cessions dans le ou les departements {','.join(departements)}, "
        f"sur {mois} mois, avec un prix de cession d'au moins {montant_min:.0f} euros, "
        f"et rends-en au plus {limite}. Analyse ensuite chaque cas rendu."
    )


def _analyse_depuis(
    charge: dict[str, Any], ids_connus: set[str]
) -> tuple[dict[str, str], str | None]:
    """Recolle `par_lead` sur les ids REELLEMENT rendus par l'outil.

    Un id que l'outil n'a pas rendu est ecarte : c'est le seul endroit ou le
    modele pourrait faire entrer quelque chose qui ne vient pas du coeur, et une
    analyse attachee a un lead inexistant serait une attribution fausse — pire
    qu'une absence dans une fiche d'audit.
    """
    retenus: dict[str, str] = {}
    inconnus = 0
    for entree in charge.get("par_lead", []):
        identifiant = str(entree.get("id", ""))
        if identifiant in ids_connus:
            retenus[identifiant] = str(entree.get("analyse", ""))
        else:
            inconnus += 1
    reserve = (
        f"{inconnus} analyse(s) ecartee(s) : le modele a designe des cas que l'outil "
        "n'a pas rendus"
        if inconnus
        else None
    )
    return retenus, reserve


def analyser(
    *,
    departements: Sequence[str],
    mois: int = 12,
    montant_min: float = 0.0,
    limite: int = LIMITE_DEFAUT,
    aujourdhui: date | None = None,
    client: Any = None,
    executer: Callable[..., Any] = pipeline.executer,
    modele: str = MODELE_DEFAUT,
    effort: str = EFFORT_DEFAUT,
    tours_max: int = TOURS_MAX,
) -> ResultatAgent:
    """Le pipeline, orchestre par le modele — avec repli si le modele manque.

    `client` et `executer` sont des PARAMETRES, comme `rechercher` et `enrichir`
    partout ailleurs dans ce coeur. C'est ce qui rend cette voie testable sans
    reseau, et c'est la meme raison qu'ailleurs : une racine de composition par
    surface.
    """
    depart = time.perf_counter()
    compteurs = {"entree": 0, "sortie": 0, "cache": 0}
    appels: list[dict[str, Any]] = []
    sortie_outil: dict[str, Any] | None = None
    charge: dict[str, Any] | None = None
    reserve: str | None = None
    tours = 0

    try:
        client = client or client_par_defaut()
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": _demande(departements, mois, montant_min, limite)}
        ]
        while tours < tours_max:
            tours += 1
            reponse = client.messages.create(
                model=modele,
                max_tokens=MAX_TOKENS,
                system=SYSTEME,
                tools=OUTILS,
                output_config={
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": SCHEMA_ANALYSE},
                },
                messages=messages,
            )
            _cumuler(compteurs, reponse.usage)

            demandes = [bloc for bloc in reponse.content if bloc.type == "tool_use"]
            if not demandes:
                textes = [bloc.text for bloc in reponse.content if bloc.type == "text"]
                charge = json.loads("".join(textes)) if textes else None
                break

            messages.append({"role": "assistant", "content": reponse.content})
            resultats = []
            for demande in demandes:
                arguments = dict(demande.input)
                appels.append(arguments)
                try:
                    sortie_outil = executer_recherche(
                        arguments, aujourdhui=aujourdhui, executer=executer
                    )
                    contenu = json.dumps(faits_pour_le_modele(sortie_outil), ensure_ascii=False)
                    erreur = False
                except ValueError as exc:
                    # Le message repart au modele : c'est ce qui lui permet de
                    # corriger son appel plutot que d'abandonner.
                    contenu, erreur = str(exc), True
                resultats.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": demande.id,
                        "content": contenu,
                        "is_error": erreur,
                    }
                )
            messages.append({"role": "user", "content": resultats})
        else:
            reserve = f"le modele n'a pas conclu en {tours_max} tours"
    except Exception as exc:  # noqa: BLE001 — toute panne du modele degrade, aucune ne casse
        reserve = f"{type(exc).__name__} : {exc}"

    # `outil` est TOUJOURS rendu. Si le modele n'a jamais appele l'outil — panne,
    # clef absente, ou refus — on execute le pipeline avec les parametres
    # demandes. On perd l'analyse, pas les leads ni le classement : meme regle
    # que pour l'enrichissement.
    if sortie_outil is None:
        sortie_outil = executer_recherche(
            {
                "departement": ",".join(departements),
                "mois": mois,
                "montant_min": montant_min,
                "limite": limite,
            },
            aujourdhui=aujourdhui,
            executer=executer,
        )
        reserve = reserve or "le modele n'a pas appele l'outil"

    ids = [lead["id"] for lead in sortie_outil["leads"]]
    if charge is None:
        analyse = Analyse(disponible=False, reserve=reserve or "aucune analyse produite")
    else:
        par_lead, ecart = _analyse_depuis(charge, set(ids))
        analyse = Analyse(
            disponible=True,
            synthese=str(charge.get("synthese", "")),
            par_lead=par_lead,
            reserve=reserve or ecart,
        )

    return ResultatAgent(
        outil=sortie_outil,
        analyse=analyse,
        mesure=Mesure(
            modele=modele,
            duree_ms=round((time.perf_counter() - depart) * 1000),
            tokens_entree=compteurs["entree"],
            tokens_sortie=compteurs["sortie"],
            tokens_cache_lus=compteurs["cache"],
            tours=tours,
            appels_outil=appels,
            ids_rendus=ids,
        ),
    )


# --- Le comparatif ------------------------------------------------------------------
#
# **Deux ecarts, deux causes, deux noms.** Si les deux portaient le meme nom,
# quelqu'un lirait le second comme le premier — c'est la regle 1 des lecons de ce
# projet, appliquee a un identifiant.
#
#   effet_du_modele        voie 3 contre un APPEL DIRECT au pipeline, memes
#                          parametres. Vrai par construction : les deux cotes
#                          appellent la meme fonction. C'est la preuve que le
#                          modele n'a pas touche a l'ensemble des leads.
#
#   fraicheur_de_la_base   voie 3 contre la lecture de la base. Mesure l'age de
#                          la derniere collecte, PAS l'effet du modele. Les deux
#                          populations different par construction — plafond de
#                          rapatriement et budget d'enrichissement d'un cote,
#                          tout de l'autre.
#
# Un ecart sans cause attribuee est pire qu'un ecart non mesure : il se lit comme
# une explication.


def ecart(reference: Sequence[str], comparee: Sequence[str]) -> dict[str, Any]:
    """Ce qui separe deux ensembles d'identifiants, avec l'ordre a part.

    Fonction pure, et c'est delibere : le front n'a pas le droit de calculer, et
    une comparaison de listes en JavaScript vivrait dans le seul fichier que les
    tests ne couvrent pas.

    `meme_ordre` est distinct d'`identiques` parce que les deux repondent a des
    questions differentes : le modele a-t-il retire des leads, ou les a-t-il
    reordonnes ? Un classement reordonne est un classement que le coeur n'a pas
    decide, meme si l'ensemble est intact.
    """
    gauche, droite = list(reference), list(comparee)
    manquants = [identifiant for identifiant in gauche if identifiant not in set(droite)]
    ajoutes = [identifiant for identifiant in droite if identifiant not in set(gauche)]
    return {
        "identiques": not manquants and not ajoutes,
        "meme_ordre": gauche == droite,
        "seulement_reference": manquants,
        "seulement_comparee": ajoutes,
    }


def comparer(
    *,
    departements: Sequence[str],
    mois: int = 12,
    montant_min: float = 0.0,
    limite: int = LIMITE_DEFAUT,
    aujourdhui: date | None = None,
    client: Any = None,
    executer: Callable[..., Any] = pipeline.executer,
    lire_la_base: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Les trois voies sur les memes filtres, et ce qui les separe.

    `lire_la_base` est un port comme les autres : la lecture de la base a besoin
    d'une connexion, que seule la surface sait ouvrir. Absent, la voie « base »
    est declaree indisponible plutot que silencieusement omise — une voie
    manquante qui ne se declare pas se lit comme une voie identique.
    """
    agent_resultat = analyser(
        departements=departements,
        mois=mois,
        montant_min=montant_min,
        limite=limite,
        aujourdhui=aujourdhui,
        client=client,
        executer=executer,
    )

    depart = time.perf_counter()
    demande = {
        "departement": ",".join(departements),
        "mois": mois,
        "montant_min": montant_min,
        "limite": limite,
    }
    direct = executer_recherche(demande, aujourdhui=aujourdhui, executer=executer)
    duree_directe = round((time.perf_counter() - depart) * 1000)
    ids_directs = [lead["id"] for lead in direct["leads"]]

    # Le modele a-t-il appele l'outil avec ce qu'on lui demandait ? C'est la
    # seule chose qui puisse expliquer un ecart, et sans elle un ecart resterait
    # mysterieux — donc attribue au hasard, donc au modele.
    respectes = all(
        all(appel.get(cle, valeur) == valeur for cle, valeur in demande.items())
        for appel in agent_resultat.mesure.appels_outil
    )

    voies: dict[str, Any] = {
        "agent": {
            "mesure": agent_resultat.mesure.en_dict(),
            "ids": agent_resultat.mesure.ids_rendus,
        },
        "direct": {"mesure": {"duree_ms": duree_directe}, "ids": ids_directs},
    }

    effet = ecart(ids_directs, agent_resultat.mesure.ids_rendus)
    effet["arguments_respectes"] = respectes

    # Pas de valeur initiale pour `fraicheur_de_la_base` : les deux branches
    # ci-dessous l'ecrivent toutes les deux, donc un repli serait inatteignable.
    # Une mutation l'a montre en survivant — et une mutation qui survit n'est pas
    # toujours un trou de test, elle peut porter sur du code que rien n'atteint.
    comparaison: dict[str, Any] = {
        "parametres": demande,
        "voies": voies,
        "effet_du_modele": effet,
    }

    if lire_la_base is None:
        comparaison["fraicheur_de_la_base"] = {
            "disponible": False,
            "reserve": "la base n'a pas ete interrogee",
        }
        return comparaison

    depart = time.perf_counter()
    lecture = lire_la_base()
    duree_base = round((time.perf_counter() - depart) * 1000)
    ids_base = [lead["id"] for lead in lecture.leads]
    voies["base"] = {"mesure": {"duree_ms": duree_base}, "ids": ids_base}

    comparaison["fraicheur_de_la_base"] = {
        "disponible": True,
        **ecart(ids_directs, ids_base),
        # Le nom du champ dit deja ce qu'il mesure ; la phrase le redit pour le
        # lecteur qui tombe sur la reponse sans avoir lu la documentation.
        "reserve": (
            "mesure l'age de la derniere collecte, pas l'effet du modele : "
            "la voie directe interroge la source, la base relit ce qu'un "
            "balayage anterieur y a ecrit"
        ),
    }
    return comparaison
