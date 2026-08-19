"""La troisieme voie : Claude orchestre, il ne calcule jamais.

## Le test central est une assertion d'IMMOBILITE

Toutes les autres assertions de ce projet disent « la valeur est celle-ci ».
Celle-ci dit **« la valeur ne bouge pas »** — et c'est ce qui la rend
concluante. On substitue un client qui rend une prose deliberement fausse
(memes grandeurs, valeurs absurdes, memes identifiants) et on exige que `outil`
soit identique, octet pour octet, a la sortie du pipeline appelee directement.

Si un seul chiffre affiche venait de la prose, il aurait change. Une assertion
de presence — « `outil` existe », « `outil["leads"]` est non vide » — passerait
dans les deux cas.

**Et le garde a des dents dans les DEUX sens.** Un test contamine
volontairement `outil` avec un champ de la prose et exige que la comparaison
rougisse. Sans lui, une comparaison qui ne comparerait rien passerait le
premier test sans rien garantir — c'est exactement le mecanisme des six
visages, applique au controle lui-meme.

## Le double est construit sur les VRAIS types du SDK

`anthropic.types.Message`, `ToolUseBlock`, `TextBlock`, `Usage`. Un double monte
avec des dictionnaires maison validerait un contrat que le SDK n'honore pas —
« un test dont l'entree est fabriquee ne prouve rien sur la production », le
defaut qui a produit le 422 de l'etape precedente. Ici l'entree a la forme
exacte de ce que l'API rend.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from fundora_prospect import agent, pipeline
from fundora_prospect.agent import CHAMPS_TRANSMIS

# --- Le corpus ------------------------------------------------------------------
#
# Deux leads, choisis pour que chaque paire de grandeurs se separe : un cedant
# personne morale avec SIREN et un cedant personne physique sans SIREN. Les
# denominations sont des noms de FIXTURE, mais elles jouent ici le role d'un
# nom reel : c'est elles que le garde du prompt cherche.

DENOMINATIONS = ("LINGOREST", "MARTIN DUPONT")
SIRENS = ("479447658", "852872563")


def _lead(
    identifiant: str, denomination: str, siren: str | None, type_cedant: str
) -> dict[str, Any]:
    return {
        "id": identifiant,
        "score": 98.6348,
        "cedant": denomination,
        "siren": siren,
        "type_cedant": type_cedant,
        "type_cedant_libelle": "personne morale" if type_cedant == "pm" else "personne physique",
        "montant_eur": 6_350_000.0,
        "date_acte": None,
        "date_parution": "2026-08-11",
        "jours_ecoules": 8,
        "date_reference": "2026-08-11",
        "departement": "06",
        "statut_cedant": "active",
        "statut_motif": "societe active : tresorerie de cession au bilan",
        "code_ape": "56.10C",
        "section_ape": "I",
        "url_publication": "https://www.bodacc.fr/x/1",
        "breakdown": [{"critere": "montant", "points": 55.0, "poids": 55.0, "motif": "…"}],
        "provenance": {
            "source": "BODACC",
            "base_legale": "…",
            "date_collecte": "2026-08-19",
            "url_publication": "https://www.bodacc.fr/x/1",
        },
    }


LEADS = [
    _lead("A-PM", DENOMINATIONS[0], SIRENS[0], "pm"),
    _lead("A-PP", DENOMINATIONS[1], None, "pp"),
]


def executer_double(**options: Any) -> pipeline.ResultatPipeline:
    """Le pipeline, substitue. Il ignore les parametres : ce qui est teste ici
    est la boucle et la separation prose / donnees, pas le scoring."""
    return pipeline.ResultatPipeline(
        leads=[dict(lead) for lead in LEADS],
        statistiques={
            "evenements_en_base": 941,
            "candidats": 923,
            "classables": 788,
            "leads_rendus": 2,
            "ecartes": {"apport": 10},
        },
        departements=list(options.get("departements", ["06"])),
        debut=date(2025, 8, 1),
        fin=date(2026, 8, 19),
        montant_min=float(options.get("montant_min", 0.0)),
    )


# --- Le double du client, sur les vrais types du SDK -------------------------------


def message(contenu: list[Any], stop: str, entree: int = 100, sortie: int = 50) -> Message:
    return Message(
        id="msg_essai",
        type="message",
        role="assistant",
        model=agent.MODELE_DEFAUT,
        content=contenu,
        stop_reason=stop,
        usage=Usage(input_tokens=entree, output_tokens=sortie),
    )


def bloc_outil(arguments: dict[str, Any], identifiant: str = "toolu_1") -> ToolUseBlock:
    return ToolUseBlock(
        id=identifiant, type="tool_use", name="search_liquidity_events", input=arguments
    )


def bloc_texte(charge: dict[str, Any]) -> TextBlock:
    return TextBlock(type="text", text=json.dumps(charge, ensure_ascii=False))


class ClientDouble:
    """Rend les reponses qu'on lui donne, dans l'ordre, et RETIENT les appels.

    Retenir les appels est ce qui permet de lire le prompt complet — systeme,
    outils, messages, resultats d'outil — dans le test d'identite.
    """

    def __init__(self, reponses: list[Message]) -> None:
        self._reponses = list(reponses)
        self.appels: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> Message:
        self.appels.append(kwargs)
        if not self._reponses:
            raise AssertionError("le double n'a plus de reponse a rendre")
        return self._reponses.pop(0)


# La prose MENT : memes grandeurs que la sortie, valeurs absurdes, vrais ids.
# Un corpus dont la prose ne citerait aucun nombre ne departagerait rien.
PROSE_MENSONGERE = {
    "synthese": "3 leads rendus, score moyen 12, montant total 42 EUR, 0 ecarte.",
    "par_lead": [
        {"id": "A-PM", "analyse": "score 12 sur 100, cession de 42 EUR, 900 jours."},
        {"id": "A-PP", "analyse": "score 1, montant 7 EUR, 1 candidat en base."},
    ],
}


def client_nominal(arguments: dict[str, Any] | None = None) -> ClientDouble:
    return ClientDouble(
        [
            message([bloc_outil(arguments or {"departement": "06"})], "tool_use"),
            message([bloc_texte(PROSE_MENSONGERE)], "end_turn", entree=200, sortie=80),
        ]
    )


def lancer(client: ClientDouble, **options: Any) -> agent.ResultatAgent:
    parametres: dict[str, Any] = {
        "departements": ["06"],
        "mois": 12,
        "montant_min": 0.0,
        "limite": 25,
        "client": client,
        "executer": executer_double,
        "aujourdhui": date(2026, 8, 19),
    }
    parametres.update(options)
    return agent.analyser(**parametres)


# --- Le controle d'immobilite, extrait pour etre mis a l'epreuve ------------------


def ecarts_avec_la_voie_directe(outil: dict[str, Any]) -> list[str]:
    """Ce qui separe `outil` d'un appel direct au pipeline. Vide = intact.

    Extrait en fonction pour que le test de dents puisse l'appeler sur une
    sortie CONTAMINEE et exiger qu'elle rougisse. Un controle qu'on ne peut pas
    faire echouer ne garde rien.
    """
    reference = agent.executer_recherche(
        {"departement": "06", "mois": 12, "montant_min": 0.0, "limite": 25},
        aujourdhui=date(2026, 8, 19),
        executer=executer_double,
    )
    if outil == reference:
        return []
    return [
        f"{cle} : {outil.get(cle)!r} != {valeur!r}"
        for cle, valeur in reference.items()
        if outil.get(cle) != valeur
    ] or ["clefs en trop dans outil"]


# --- Le test central --------------------------------------------------------------


def test_la_prose_ment_et_outil_ne_bouge_pas() -> None:
    """**Le test du cycle.** La prose annonce 3 leads, un score de 12 et un
    montant de 42 EUR. La sortie doit rester celle du pipeline.

    Assertion d'immobilite, pas de presence : `assert resultat.outil` passerait
    meme si chaque champ venait du modele.
    """
    resultat = lancer(client_nominal())

    assert ecarts_avec_la_voie_directe(resultat.outil) == []
    # Les grandeurs citees a tort par la prose, verifiees une a une.
    assert resultat.outil["statistiques"]["leads_rendus"] == 2
    assert resultat.outil["leads"][0]["score"] == 98.6348
    assert resultat.outil["leads"][0]["montant_eur"] == 6_350_000.0
    assert resultat.outil["statistiques"]["ecartes"] == {"apport": 10}
    # Et la prose est conservee telle quelle, a sa place.
    assert "42 EUR" in resultat.analyse.synthese


def test_le_controle_d_immobilite_a_des_dents() -> None:
    """**L'autre sens.** On branche volontairement un champ de `outil` sur la
    prose, et on exige que le controle rougisse.

    Sans ce test, une comparaison qui ne comparerait rien passerait le test
    precedent sans rien garantir.
    """
    resultat = lancer(client_nominal())
    contamine = dict(resultat.outil)
    contamine["resume"] = resultat.analyse.synthese

    ecarts = ecarts_avec_la_voie_directe(contamine)
    assert ecarts, "un `resume` venu de la prose doit etre detecte"
    assert any("resume" in ecart for ecart in ecarts)


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("resume", "3 leads rendus"),
        ("montant_min_eur", 42.0),
        ("statistiques", {"leads_rendus": 3}),
        ("leads", []),
    ],
)
def test_le_controle_attrape_chaque_champ_contamine(champ: str, valeur: Any) -> None:
    """Un controle qui ne verrait qu'un champ laisserait passer les autres.

    Le corpus couvre les quatre familles de la sortie : la phrase, un scalaire,
    les compteurs, la liste.
    """
    resultat = lancer(client_nominal())
    contamine = dict(resultat.outil)
    contamine[champ] = valeur
    assert ecarts_avec_la_voie_directe(contamine), f"{champ} contamine doit etre detecte"


# --- L'identite ne quitte pas la machine -------------------------------------------


def prompt_complet(client: ClientDouble) -> str:
    """TOUT ce qui a ete emis : systeme, outils, messages, resultats d'outil.

    Se limiter au bloc de donnees laisserait fuir un nom par le texte systeme
    ou par une description d'outil — deux endroits que personne ne relit en
    cherchant une donnee personnelle.
    """
    return json.dumps(client.appels, ensure_ascii=False, default=str)


def test_le_prompt_complet_ne_porte_ni_denomination_ni_siren() -> None:
    client = client_nominal()
    lancer(client)
    emis = prompt_complet(client)

    for denomination in DENOMINATIONS:
        assert denomination not in emis, f"{denomination!r} est parti chez Anthropic"
    for siren in SIRENS:
        assert siren not in emis, f"SIREN {siren} est parti chez Anthropic"
    # Le corpus doit avoir voyage : sans ca, l'assertion passerait sur un
    # prompt vide. Les ids, eux, sont censes partir.
    assert "A-PM" in emis and "A-PP" in emis


def test_le_garde_du_prompt_ROUGIT_si_une_denomination_fuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**La mutation, gardee en permanence.** On inscrit `cedant` dans la liste
    blanche et on exige que le garde precedent echoue.

    C'est la seule facon de distinguer « aucun nom ne fuit » de « le garde ne
    regarde pas au bon endroit ».
    """
    monkeypatch.setattr(agent, "CHAMPS_TRANSMIS", (*CHAMPS_TRANSMIS, "cedant", "siren"))
    client = client_nominal()
    lancer(client)
    emis = prompt_complet(client)

    assert DENOMINATIONS[0] in emis, "la mutation n'a pas pris — le test ne prouve rien"
    assert SIRENS[0] in emis


def test_la_liste_blanche_ne_laisse_passer_que_ses_champs() -> None:
    """Le complement du garde : ce qui part est exactement ce qui est declare.

    Un test qui ne verifierait que l'absence des noms laisserait entrer
    n'importe quel autre champ ajoute au lead demain.
    """
    faits = agent.faits_pour_le_modele(
        agent.executer_recherche(
            {"departement": "06"}, aujourdhui=date(2026, 8, 19), executer=executer_double
        )
    )
    for lead in faits["leads"]:
        assert set(lead) <= set(CHAMPS_TRANSMIS)
    assert "cedant" not in faits["leads"][0]
    assert "provenance" not in faits["leads"][0]


# --- Ce que la mesure doit dire ----------------------------------------------------


def test_les_tokens_sont_sommes_sur_TOUS_les_tours() -> None:
    """Ne lire que la derniere reponse sous-estimerait le cout d'un facteur egal
    au nombre d'allers-retours — la grandeur meme que le comparatif mesure.

    Le corpus donne deux tours d'usage DIFFERENTS : avec deux tours identiques,
    la somme et le dernier ne se departageraient pas.
    """
    resultat = lancer(client_nominal())

    assert resultat.mesure.tours == 2
    assert resultat.mesure.tokens_entree == 300  # 100 + 200, pas 200
    assert resultat.mesure.tokens_sortie == 130  # 50 + 80, pas 80


def test_la_mesure_porte_les_arguments_QUE_LE_MODELE_a_passes() -> None:
    """« Un tri en amont est un filtre », applique a un modele.

    Le corpus fait demander au modele une limite differente de celle demandee
    par l'utilisateur : si `appels_outil` recopiait la demande initiale, l'ecart
    serait invisible.
    """
    client = client_nominal({"departement": "13", "limite": 3})
    resultat = lancer(client, limite=25)

    assert resultat.mesure.appels_outil == [{"departement": "13", "limite": 3}]
    assert resultat.mesure.ids_rendus == ["A-PM", "A-PP"]


# --- Degradation propre -------------------------------------------------------------


class ClientEnPanne:
    def __init__(self) -> None:
        self.messages = self

    def create(self, **kwargs: Any) -> Message:
        raise RuntimeError("api indisponible")


def test_une_panne_du_modele_perd_l_analyse_pas_les_leads() -> None:
    """Meme regle que pour l'enrichissement : la degradation est propre.

    L'API Anthropic qui tombe ne doit couter que le commentaire.
    """
    resultat = lancer(ClientEnPanne())

    assert ecarts_avec_la_voie_directe(resultat.outil) == []
    assert resultat.analyse.disponible is False
    assert "api indisponible" in (resultat.analyse.reserve or "")


def test_un_modele_qui_n_appelle_pas_l_outil_rend_quand_meme_les_leads() -> None:
    """L'autre panne, silencieuse : le modele repond sans appeler l'outil.

    Sans ce cas, `outil` serait absent et la route rendrait une reponse
    plausible mais vide — le mode degrade qui ressemble a un resultat.
    """
    charge = {"synthese": "je crois savoir", "par_lead": []}
    client = ClientDouble([message([bloc_texte(charge)], "end_turn")])
    resultat = lancer(client)

    assert ecarts_avec_la_voie_directe(resultat.outil) == []
    assert resultat.mesure.appels_outil == []
    assert "n'a pas appele l'outil" in (resultat.analyse.reserve or "")


def test_une_analyse_attachee_a_un_id_inconnu_est_ecartee() -> None:
    """Le seul endroit ou le modele pourrait faire entrer quelque chose qui ne
    vient pas du coeur. Une analyse collee a un lead inexistant serait une
    attribution fausse — pire qu'une absence dans une fiche d'audit."""
    charge = {
        "synthese": "…",
        "par_lead": [
            {"id": "A-PM", "analyse": "vraie"},
            {"id": "A-INVENTE", "analyse": "attachee a rien"},
        ],
    }
    client = ClientDouble(
        [
            message([bloc_outil({"departement": "06"})], "tool_use"),
            message([bloc_texte(charge)], "end_turn"),
        ]
    )
    resultat = lancer(client)

    assert set(resultat.analyse.par_lead) == {"A-PM"}
    assert "ecartee" in (resultat.analyse.reserve or "")


def test_un_argument_illisible_repart_au_modele_comme_erreur() -> None:
    """Le message de `borne` est ce qui permet au modele de se corriger seul.
    L'avaler en silence ferait boucler sans jamais rien produire."""
    client = ClientDouble(
        [
            message([bloc_outil({"departement": "06", "mois": 999})], "tool_use"),
            message([bloc_outil({"departement": "06", "mois": 6}, "toolu_2")], "tool_use"),
            message([bloc_texte(PROSE_MENSONGERE)], "end_turn"),
        ]
    )
    resultat = lancer(client)

    resultats_outil = [
        bloc
        for appel in client.appels
        for message_ in appel["messages"]
        if isinstance(message_.get("content"), list)
        for bloc in message_["content"]
        if isinstance(bloc, dict) and bloc.get("type") == "tool_result"
    ]
    premier = resultats_outil[0]
    assert premier["is_error"] is True
    assert "mois" in premier["content"] and "999" in premier["content"]
    assert resultat.analyse.disponible is True


def test_une_boucle_qui_ne_conclut_pas_s_arrete_et_le_dit() -> None:
    """Un modele qui rappelle l'outil sans fin coute des tokens sans rien
    apporter. La borne est declaree dans la reserve, pas subie en silence."""
    client = ClientDouble(
        [message([bloc_outil({"departement": "06"}, f"t{n}")], "tool_use") for n in range(3)]
    )
    resultat = lancer(client, tours_max=3)

    assert resultat.mesure.tours == 3
    assert resultat.analyse.disponible is False
    assert "3 tours" in (resultat.analyse.reserve or "")
    assert ecarts_avec_la_voie_directe(resultat.outil) == []


# --- La declaration d'outil n'est pas recopiee ---------------------------------------


def test_l_outil_declare_a_anthropic_porte_la_description_du_MCP() -> None:
    """Deux prompts pour un meme outil divergeraient sur un mot — et le mot qui
    derive serait celui qui oriente le modele vers `"06"` plutot que `6`."""
    from fundora_prospect.mcp_server import DESCRIPTION_RECHERCHE

    (declaration,) = agent.OUTILS
    assert declaration["name"] == "search_liquidity_events"
    assert declaration["description"] == DESCRIPTION_RECHERCHE
    assert declaration["input_schema"]["properties"]["limite"]["maximum"] == pipeline.LIMITE_MAX
