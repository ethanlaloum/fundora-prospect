"""Serveur MCP — test d'integration avec un client in-process.

Le serveur est le point d'entree du plugin : c'est lui que Claude Code appelle
quand on ecrit « trouve-moi les cessions de plus de 300 k EUR dans le 06 ».
Ces tests passent par un vrai `ClientSession` sur des flux en memoire, pas par
un appel direct aux fonctions Python — sinon on ne testerait pas la couche qui
casse en production : schema des outils, validation des arguments, forme de la
reponse.

Aucun appel reseau : la recherche et l'enrichissement sont substitues par des
donnees issues des fixtures figees.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from fundora_prospect import mcp_server
from fundora_prospect.bodacc import Annonce, Cedant, ResultatRecherche, construire_annonce
from fundora_prospect.enrichment import Enrichissement
from fundora_prospect.models import StatutEntreprise
from fundora_prospect.prix import Confiance, PrixCession, Qualification

FIXTURES = Path(__file__).parent / "fixtures"


def annonces_de(nom: str) -> list:
    charge = json.loads((FIXTURES / f"{nom}.json").read_text(encoding="utf-8"))
    return [a for brut in charge if (a := construire_annonce(brut)) is not None]


def recherche_de(
    corpus: list,
    publiees: int | None = None,
    rapatriees: int | None = None,
) -> ResultatRecherche:
    """Par defaut, une recherche exhaustive : rien perdu au plafond, rien
    d'illisible. Les tests qui mesurent l'incompletude passent les deux autres
    nombres explicitement."""
    return ResultatRecherche(
        annonces=list(corpus),
        publiees=len(corpus) if publiees is None else publiees,
        rapatriees=len(corpus) if rapatriees is None else rapatriees,
    )


def fabriquer_annonce(
    identifiant: str,
    montant: float,
    jours: int,
    type_personne: str = "pm",
    url: str | None = None,
) -> Annonce:
    """Annonce synthetique, pour les cas que les fixtures ne contiennent pas :
    un couple montant/fraicheur choisi, ou une provenance amputee."""
    acte = date.today() - timedelta(days=jours)
    return Annonce(
        id=identifiant,
        date_parution=acte,
        date_acte=acte,
        departement="06",
        url_publication=f"https://www.bodacc.fr/x/{identifiant}" if url is None else url,
        categorie_vente=None,
        activite=None,
        cedant=Cedant(denomination=identifiant, type_personne=type_personne, siren="852872563"),
        prix=PrixCession(
            montant=montant,
            devise="EUR",
            qualification=Qualification.ACHAT,
            methode="test",
            texte_source="",
            confiance=Confiance.ACTE_DATE,
            ecart_acte_jours=0,
        ),
    )


def appeler(outil: str, arguments: dict[str, Any]) -> Any:
    """Ouvre un client MCP in-process et appelle un outil."""

    async def scenario() -> Any:
        bas_niveau = mcp_server.serveur._lowlevel_server
        async with (
            create_client_server_memory_streams() as ((cr, cw), (sr, sw)),
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(
                lambda: bas_niveau.run(
                    sr, sw, bas_niveau.create_initialization_options(), raise_exceptions=True
                )
            )
            async with ClientSession(cr, cw) as session:
                await session.initialize()
                resultat = await session.call_tool(outil, arguments)
            tg.cancel_scope.cancel()
            return resultat

    return anyio.run(scenario)


def lister_outils() -> list:
    async def scenario() -> list:
        bas_niveau = mcp_server.serveur._lowlevel_server
        async with (
            create_client_server_memory_streams() as ((cr, cw), (sr, sw)),
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(
                lambda: bas_niveau.run(
                    sr, sw, bas_niveau.create_initialization_options(), raise_exceptions=True
                )
            )
            async with ClientSession(cr, cw) as session:
                await session.initialize()
                outils = (await session.list_tools()).tools
            tg.cancel_scope.cancel()
            return outils

    return anyio.run(scenario)


@pytest.fixture
def sans_reseau(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Substitue recherche et enrichissement par des donnees de fixtures."""

    def installer(
        annonces: list | None = None,
        statut: StatutEntreprise = StatutEntreprise.ACTIVE,
    ) -> None:
        corpus = annonces if annonces is not None else annonces_de("acte_datable_recent")
        monkeypatch.setattr(mcp_server, "rechercher", lambda **_: recherche_de(corpus))
        monkeypatch.setattr(
            mcp_server,
            "enrichir",
            lambda siren, **_: Enrichissement(
                siren=str(siren or ""),
                statut=statut,
                code_ape="10.71C",
                section_ape="C",
                motif="fixture",
            ),
        )

    return installer


# --- Contrat des outils -------------------------------------------------------


def test_les_trois_outils_sont_exposes() -> None:
    noms = {o.name for o in lister_outils()}
    assert noms == {"search_liquidity_events", "enrich_company", "score_lead"}


def test_chaque_outil_porte_une_description_utilisable() -> None:
    """La description est ce que le modele lit pour decider quoi appeler : c'est
    du prompt, pas de la documentation decorative."""
    for outil in lister_outils():
        assert outil.description and len(outil.description) > 80, outil.name


def test_la_description_de_la_recherche_precise_le_format_du_departement() -> None:
    """Un modele passera `6` au lieu de `"06"` si on ne le lui dit pas."""
    recherche = next(o for o in lister_outils() if o.name == "search_liquidity_events")
    assert '"06"' in recherche.description


# --- Recherche : le pipeline complet -----------------------------------------


def test_la_recherche_rend_des_leads_deja_scores(sans_reseau) -> None:
    """Un seul appel doit suffire : trois outils granulaires forceraient le
    modele a orchestrer des dizaines d'appels."""
    sans_reseau()
    resultat = appeler("search_liquidity_events", {"departement": "13", "mois": 12})
    charge = resultat.structured_content

    assert charge["leads"], "aucun lead rendu"
    premier = charge["leads"][0]
    assert premier["score"] > 0
    assert premier["cedant"]
    assert premier["url_publication"].startswith("https://www.bodacc.fr/")
    assert premier["breakdown"], "le detail du score doit voyager jusqu'au client"


def test_les_leads_sont_tries_par_score_decroissant(sans_reseau) -> None:
    sans_reseau()
    charge = appeler("search_liquidity_events", {"departement": "13"}).structured_content
    scores = [lead["score"] for lead in charge["leads"]]
    assert scores == sorted(scores, reverse=True)


def test_la_sortie_porte_les_motifs_de_refus(sans_reseau) -> None:
    """L'auditabilite construite depuis la Phase 1 doit etre VISIBLE dans le
    transport MCP, sinon elle n'existe que dans les tests."""
    sans_reseau(
        annonces=annonces_de("acte_datable_recent")
        + annonces_de("apport_en_nature")
        + annonces_de("devise_francs")
    )
    charge = appeler("search_liquidity_events", {"departement": "13"}).structured_content

    stats = charge["statistiques"]
    assert stats["annonces_publiees"] > 0
    assert stats["classables_parmi_les_enrichis"] >= 0
    assert stats["ecartes"], "les refus doivent etre ventiles par motif"
    assert sum(stats["ecartes"].values()) > 0
    assert "resume" in charge and str(stats["annonces_publiees"]) in charge["resume"]


def test_une_societe_cessee_est_ecartee_et_comptee(sans_reseau) -> None:
    sans_reseau(statut=StatutEntreprise.CESSEE)
    charge = appeler("search_liquidity_events", {"departement": "13"}).structured_content
    assert charge["leads"] == []
    assert any("cess" in motif.lower() for motif in charge["statistiques"]["ecartes"])


def test_chaque_lead_rendu_porte_sa_provenance_complete(sans_reseau) -> None:
    """Contrainte 3, verifiee la ou elle compte : dans le transport. Les tests
    de `test_provenance.py` prouvent qu'un lead incomplet ne se serialise pas ;
    celui-ci prouve que le serveur passe bien par cette porte-la."""
    sans_reseau()
    charge = appeler("search_liquidity_events", {"departement": "13"}).structured_content

    assert charge["leads"], "aucun lead rendu"
    for lead in charge["leads"]:
        provenance = lead["provenance"]
        assert set(provenance) == {"source", "base_legale", "date_collecte", "url_publication"}
        assert all(str(v).strip() for v in provenance.values())
        assert provenance["url_publication"].startswith("https://www.bodacc.fr/")
        assert provenance["date_collecte"] == date.today().isoformat()


def test_la_provenance_distingue_les_deux_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un export qui melange personne morale et personne physique sans le champ
    qui les separe est precisement ce que CLAUDE.md interdit."""
    corpus = [
        fabriquer_annonce("SOCIETE-CEDANTE", 300_000, 10, type_personne="pm"),
        fabriquer_annonce("COMMERCANT-CEDANT", 300_000, 10, type_personne="pp"),
    ]
    monkeypatch.setattr(mcp_server, "rechercher", lambda **_: recherche_de(corpus))
    monkeypatch.setattr(
        mcp_server,
        "enrichir",
        lambda siren, **_: Enrichissement(
            siren=str(siren or ""), statut=StatutEntreprise.ACTIVE, motif="fixture"
        ),
    )

    charge = appeler("search_liquidity_events", {"departement": "06"}).structured_content
    bases = {lead["cedant"]: lead["provenance"]["base_legale"] for lead in charge["leads"]}
    assert len(bases) == 2
    assert bases["SOCIETE-CEDANTE"] != bases["COMMERCANT-CEDANT"]
    assert "qualification" in bases["COMMERCANT-CEDANT"].lower()


def test_une_annonce_sans_url_est_ecartee_et_non_rendue_sans_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`url_complete` est replie sur `""` par le client quand il manque. Le lead
    doit alors sortir du flux AVEC SON MOTIF — ni rendu sans provenance, ni
    perdu en silence, ni propage en exception jusqu'au client MCP."""
    corpus = [
        fabriquer_annonce("TRACABLE", 300_000, 10),
        fabriquer_annonce("SANS-URL", 900_000, 5, url=""),
    ]
    monkeypatch.setattr(mcp_server, "rechercher", lambda **_: recherche_de(corpus))
    monkeypatch.setattr(
        mcp_server,
        "enrichir",
        lambda siren, **_: Enrichissement(
            siren=str(siren or ""), statut=StatutEntreprise.ACTIVE, motif="fixture"
        ),
    )

    charge = appeler("search_liquidity_events", {"departement": "06"}).structured_content
    rendus = {lead["cedant"] for lead in charge["leads"]}
    assert rendus == {"TRACABLE"}, "un lead intracable ne doit pas sortir"
    assert any("provenance" in motif for motif in charge["statistiques"]["ecartes"])


def test_le_montant_minimum_filtre(sans_reseau) -> None:
    sans_reseau()
    haut = appeler(
        "search_liquidity_events", {"departement": "13", "montant_min": 10_000_000}
    ).structured_content
    assert haut["leads"] == []


def test_la_limite_borne_le_nombre_de_leads(sans_reseau) -> None:
    sans_reseau()
    charge = appeler(
        "search_liquidity_events", {"departement": "13", "limite": 1}
    ).structured_content
    assert len(charge["leads"]) <= 1


def test_le_plafond_de_rapatriement_est_annonce(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le jumeau de `leads_classables`, en amont du pipeline.

    `annonces_examinees` comptait les annonces APRES le plafond de
    rapatriement et APRES le filtre du client BODACC. Mesure reelle du
    2026-08-16 sur le 06 : 662 publiees, 600 rapatriees, 458 exploitables — le
    compteur annoncait 458 sous un nom qui promet la totalite, soit 69 % de la
    population presentee comme 100 %.

    Un chiffre plafonne doit dire qu'il l'est, sinon il se lit comme un total.
    """
    corpus = [fabriquer_annonce(f"CEDANT-{i}", 300_000, 10) for i in range(3)]
    monkeypatch.setattr(
        mcp_server,
        "rechercher",
        lambda **_: recherche_de(corpus, publiees=662, rapatriees=600),
    )
    monkeypatch.setattr(
        mcp_server,
        "enrichir",
        lambda siren, **_: Enrichissement(
            siren=str(siren or ""), statut=StatutEntreprise.ACTIVE, motif="fixture"
        ),
    )

    charge = appeler("search_liquidity_events", {"departement": "06"}).structured_content
    stats = charge["statistiques"]

    assert stats["annonces_publiees"] == 662
    assert stats["annonces_rapatriees"] == 600
    assert stats["annonces_exploitables"] == 3
    assert stats["plafond_atteint"] is True
    assert "662 annonces publiees" in charge["resume"]
    assert "600" in charge["resume"] and "plafond" in charge["resume"]


def test_sans_plafond_atteint_le_resume_n_en_parle_pas(sans_reseau) -> None:
    """Une reserve affichee en permanence cesse d'etre lue. Elle n'apparait que
    quand elle mord."""
    sans_reseau()
    charge = appeler("search_liquidity_events", {"departement": "13"}).structured_content
    assert charge["statistiques"]["plafond_atteint"] is False
    assert "plafond" not in charge["resume"]


def test_les_annonces_non_exploitables_sont_comptees(monkeypatch: pytest.MonkeyPatch) -> None:
    """`construire_annonce` ecarte les annonces sans cedant — 13 % du flux
    d'apres la Phase 0, 23,7 % sur la mesure du 06. C'est un filtre reel, et
    son decompte n'apparaissait dans aucun compteur : ni dans `ecartes`, ni
    dans le total."""
    corpus = [fabriquer_annonce(f"CEDANT-{i}", 300_000, 10) for i in range(3)]
    monkeypatch.setattr(
        mcp_server,
        "rechercher",
        lambda **_: recherche_de(corpus, publiees=10, rapatriees=10),
    )
    monkeypatch.setattr(
        mcp_server,
        "enrichir",
        lambda siren, **_: Enrichissement(
            siren=str(siren or ""), statut=StatutEntreprise.ACTIVE, motif="fixture"
        ),
    )

    charge = appeler("search_liquidity_events", {"departement": "06"}).structured_content
    stats = charge["statistiques"]

    assert stats["sans_cedant_ou_illisibles"] == 7
    assert "7 sans cedant ou illisibles" in charge["resume"]


def test_la_troncature_ne_se_compte_pas_comme_un_refus(monkeypatch: pytest.MonkeyPatch) -> None:
    """`leads_classables` doit compter ce que la grille a juge classable, pas
    ce qui reste apres la coupe a `limite`.

    Confondre les deux fait passer une troncature pour un jugement : un lecteur
    qui lit « 25 classables » sur 115 candidats conclut que la grille en a
    rejete 90, alors qu'elle n'en a jamais vu que 50 et n'en a refuse aucun.
    Le resume est recopie tel quel a l'utilisateur — c'est la que le chiffre
    detache de son referent se propage.
    """
    corpus = [fabriquer_annonce(f"CEDANT-{i}", 300_000 + i * 1_000, 10) for i in range(6)]
    monkeypatch.setattr(mcp_server, "rechercher", lambda **_: recherche_de(corpus))
    monkeypatch.setattr(
        mcp_server,
        "enrichir",
        lambda siren, **_: Enrichissement(
            siren=str(siren or ""), statut=StatutEntreprise.ACTIVE, motif="fixture"
        ),
    )

    charge = appeler(
        "search_liquidity_events", {"departement": "06", "limite": 1}
    ).structured_content
    stats = charge["statistiques"]

    # limite=1 => 2 enrichis, tous deux classables, 1 seul rendu.
    assert stats["leads_rendus"] == 1
    assert stats["classables_parmi_les_enrichis"] == 2
    assert stats["ecartes"].get("non classable", 0) == 0, "aucun refus de la grille ici"
    assert "1 rendus sur 2 classables parmi les 2 enrichis" in charge["resume"]


def test_le_compteur_de_classables_dit_qu_il_ne_voit_que_les_enrichis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Troisieme etage de la meme erreur, trouve en relisant la demo.

    La Phase 3 bis avait remonte le compteur au-dessus de la coupe finale
    `leads[:limite]`. Mais la coupe AMONT `candidats[:limite * 2]` etait
    restee : le compteur est donc plafonne a `2 * limite`, et il sature en
    silence des que la population depasse ce budget.

    Mesure du 2026-08-17 sur le 06, six mois, > 300 k EUR — meme population,
    trois budgets :

    | limite | plafond 2x | classables annonces |
    |--------|-----------|---------------------|
    | 5      | 10        | **10** — sature     |
    | 25     | 50        | 49                  |
    | 50     | 100       | 96                  |

    `demo.sh` appelle avec `limite=5` et affichait « 10 classables » sur une
    population qui en contient au moins 96. Le mot « classable » promet un
    jugement de la grille ; il rapportait combien de dossiers la grille avait
    eu le DROIT de regarder.

    Le nom doit donc porter sa condition d'obtention — c'est la regle 1 des
    lecons du projet : un chiffre ne s'ecrit jamais sans son referent.
    """
    corpus = [fabriquer_annonce(f"CEDANT-{i}", 300_000 + i * 1_000, 10) for i in range(40)]
    monkeypatch.setattr(mcp_server, "rechercher", lambda **_: recherche_de(corpus))
    monkeypatch.setattr(
        mcp_server,
        "enrichir",
        lambda siren, **_: Enrichissement(
            siren=str(siren or ""), statut=StatutEntreprise.ACTIVE, motif="fixture"
        ),
    )

    charge = appeler(
        "search_liquidity_events", {"departement": "06", "limite": 5}
    ).structured_content
    stats = charge["statistiques"]

    # 40 candidats, budget 2 x 5 = 10 : le compteur SATURE.
    assert stats["candidats_avant_enrichissement"] == 40
    assert stats["enrichis"] == 10
    assert stats["classables_parmi_les_enrichis"] == 10

    # L'ancien nom ne doit plus exister : il promettait la population entiere.
    assert "leads_classables" not in stats

    # Et le resume doit dire sur quoi le chiffre porte, dans la meme phrase.
    assert "5 rendus sur 10 classables parmi les 10 enrichis" in charge["resume"]
    assert "30 candidats non enrichis" in charge["resume"]

    # Regle 1 des lecons du projet, verifiee sur CHAQUE occurrence et pas
    # seulement sur la ligne de reserve : un chiffre ne s'ecrit jamais sans son
    # referent. Sans cette boucle, retirer « parmi les N enrichis » de la phrase
    # principale passait le test — la mutation a survecu la premiere fois.
    resume = charge["resume"]
    for suite in resume.split("classables")[1:]:
        assert suite.startswith(" parmi les "), (
            f"« classables » sans son referent dans : {resume!r}"
        )


def test_les_candidats_jamais_enrichis_sont_annonces(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un candidat non enrichi n'est ni refuse ni rendu : il est invisible.
    Le resume doit le dire, sinon la sortie parait exhaustive alors qu'elle est
    amputee — c'est la lecon « un tri en amont est un filtre », appliquee au
    compte rendu."""
    corpus = [fabriquer_annonce(f"CEDANT-{i}", 300_000 + i * 1_000, 10) for i in range(9)]
    monkeypatch.setattr(mcp_server, "rechercher", lambda **_: recherche_de(corpus))
    monkeypatch.setattr(
        mcp_server,
        "enrichir",
        lambda siren, **_: Enrichissement(
            siren=str(siren or ""), statut=StatutEntreprise.ACTIVE, motif="fixture"
        ),
    )

    charge = appeler(
        "search_liquidity_events", {"departement": "06", "limite": 2}
    ).structured_content
    stats = charge["statistiques"]

    assert stats["candidats_avant_enrichissement"] == 9
    assert stats["enrichis"] == 4
    assert stats["candidats_non_enrichis"] == 5
    assert "5 candidats non enrichis" in charge["resume"]


# --- Normalisation des parametres --------------------------------------------


@pytest.mark.parametrize("brut", ["06", "6", 6, " 06 "])
def test_le_departement_est_normalise(sans_reseau, brut: Any) -> None:
    """Un modele ecrit `6`, `"6"` ou `"06"` indifferemment. Le zero initial se
    perd des qu'on laisse passer un entier."""
    sans_reseau()
    charge = appeler("search_liquidity_events", {"departement": brut}).structured_content
    assert charge["departements"] == ["06"]


def test_paca_est_un_alias_de_la_region(sans_reseau) -> None:
    sans_reseau()
    charge = appeler("search_liquidity_events", {"departement": "PACA"}).structured_content
    assert charge["departements"] == ["04", "05", "06", "13", "83", "84"]


def test_plusieurs_departements_separes_par_virgule(sans_reseau) -> None:
    sans_reseau()
    charge = appeler("search_liquidity_events", {"departement": "06,13"}).structured_content
    assert charge["departements"] == ["06", "13"]


def test_un_departement_invalide_donne_un_message_actionnable(sans_reseau) -> None:
    """Un message d'erreur lisible par un modele est un message qui lui permet
    de se corriger seul."""
    sans_reseau()
    resultat = appeler("search_liquidity_events", {"departement": "Alpes-Maritimes"})
    assert resultat.is_error
    texte = resultat.content[0].text.lower()
    assert "departement" in texte
    assert "06" in texte


@pytest.mark.parametrize(("champ", "valeur"), [("mois", 0), ("mois", 999), ("limite", 0)])
def test_les_bornes_sont_refusees_avec_explication(sans_reseau, champ: str, valeur: int) -> None:
    sans_reseau()
    resultat = appeler("search_liquidity_events", {"departement": "13", champ: valeur})
    assert resultat.is_error
    assert champ in resultat.content[0].text.lower()


# --- Outils granulaires -------------------------------------------------------


def test_enrich_company(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mcp_server,
        "enrichir",
        lambda siren, **_: Enrichissement(
            siren=siren,
            statut=StatutEntreprise.ACTIVE,
            code_ape="56.10A",
            section_ape="I",
            motif="societe active",
        ),
    )
    charge = appeler("enrich_company", {"siren": "852872563"}).structured_content
    assert charge["statut"] == "active"
    assert charge["code_ape"] == "56.10A"
    assert charge["motif"]


def test_enrich_company_refuse_un_siren_mal_forme() -> None:
    resultat = appeler("enrich_company", {"siren": "12345"})
    assert resultat.is_error
    assert "siren" in resultat.content[0].text.lower()


def test_score_lead_rend_un_breakdown_complet() -> None:
    charge = appeler(
        "score_lead",
        {"montant_eur": 400_000, "date_acte": "2026-07-01", "departement": "06"},
    ).structured_content
    assert charge["classable"]
    assert charge["score"] > 0
    assert len(charge["breakdown"]) == 4
    assert all(c["motif"] for c in charge["breakdown"])
    assert sum(c["points"] for c in charge["breakdown"]) == pytest.approx(charge["score"])


def test_score_lead_explique_un_refus() -> None:
    charge = appeler(
        "score_lead",
        {"montant_eur": 400_000, "date_acte": "2026-07-01", "statut_cedant": "cessee"},
    ).structured_content
    assert not charge["classable"]
    assert charge["motif_refus"]


def test_score_lead_refuse_une_date_illisible() -> None:
    resultat = appeler("score_lead", {"montant_eur": 400_000, "date_acte": "hier"})
    assert resultat.is_error
    assert "aaaa-mm-jj" in resultat.content[0].text.lower()


# --- Degradation --------------------------------------------------------------


def test_une_api_muette_ne_fait_pas_echouer_la_recherche(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un lead sans enrichissement reste un lead valide — la regle de la
    Phase 3 doit survivre au passage par MCP."""
    monkeypatch.setattr(
        mcp_server, "rechercher", lambda **_: recherche_de(annonces_de("acte_datable_recent"))
    )
    monkeypatch.setattr(
        mcp_server,
        "enrichir",
        lambda siren, **_: Enrichissement(
            siren=str(siren or ""),
            statut=StatutEntreprise.INCONNU,
            motif="API entreprises injoignable : ConnectError",
        ),
    )
    charge = appeler("search_liquidity_events", {"departement": "13"}).structured_content
    assert charge["leads"], "les leads doivent survivre a une API muette"
    assert "injoignable" in charge["leads"][0]["statut_motif"]


def test_le_preclassement_ne_trie_pas_sur_le_montant_seul(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N'enrichir que le haut du panier est necessaire — l'enrichissement coute
    un appel API par lead — mais trier sur le montant reintroduirait le biais
    que la grille a corrige : une cession fraiche mais modeste ne serait jamais
    enrichie, donc jamais rendue.

    Ici, la cession la plus recente a le montant le PLUS FAIBLE. Avec une
    limite de 1, elle doit quand meme sortir.
    """
    corpus = [
        fabriquer_annonce("GROSSE-ET-VIEILLE", 1_500_000, 900),
        fabriquer_annonce("MODESTE-ET-FRAICHE", 260_000, 5),
    ]
    monkeypatch.setattr(mcp_server, "rechercher", lambda **_: recherche_de(corpus))
    monkeypatch.setattr(
        mcp_server,
        "enrichir",
        lambda siren, **_: Enrichissement(
            siren=str(siren or ""), statut=StatutEntreprise.ACTIVE, motif="fixture"
        ),
    )

    charge = appeler(
        "search_liquidity_events", {"departement": "06", "limite": 1}
    ).structured_content
    assert charge["leads"], "aucun lead rendu"
    assert charge["leads"][0]["cedant"] == "MODESTE-ET-FRAICHE"
