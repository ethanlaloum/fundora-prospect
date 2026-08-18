"""La surface web — Phase 6.

## Ce que ces tests doivent prouver, et qu'aucun autre ne peut

Trois proprietes, et les trois portent sur une **relation entre deux choses** :

1. **`/leads` et `search_liquidity_events` rendent la meme FORME.** Les deux
   surfaces montent leur enveloppe a la main, chacune de son cote. Ce qui
   divergerait n'est pas la boucle — c'est une clef renommee d'un cote, un motif
   de refus ecrit « apport en nature » ici et « apport » la. **Aucun test d'une
   surface isolee ne peut voir ca** : chacune serait verte avec son propre
   vocabulaire. Meme raisonnement que la comparaison des deux chemins de
   `motif_ecart_faits` au palier 2.

   Les POPULATIONS, elles, different — c'est ecrit et voulu (CLAUDE.md,
   « l'asymetrie de population entre les deux surfaces »). On compare les clefs,
   le vocabulaire et le breakdown, jamais les nombres.

2. **Aucune route ne peut emettre un lead hors de `provenance.serialiser`.**
   La contrainte 3 tient parce que le classement passe par une porte unique ;
   une surface qui monterait son dict a la main la rouvrirait, exactement comme
   le serveur MCP le faisait avant la Phase 3 bis.

3. **`POST /hypotheses` et `score_lead` sont la MEME implementation.** Pas deux
   qui se ressemblent : la mise en forme est descendue dans
   `models.presenter_evaluation`, et ce test le verrouille.

## Aucun reseau, aucune base du poste

La base est un fichier temporaire designe par `FUNDORA_DB`, remplie par le vrai
job de collecte sur un corpus synthetique. Sans cette variable, les tests
liraient `~/.cache/fundora-prospect/prospects.db` — les donnees reelles de la
machine qui les lance.

**La dependance `connexion` n'est PAS substituee**, et c'est une correction :
la premiere version injectait une connexion creee dans le thread du test, ce
que SQLite refuse des que `TestClient` execute la route dans un thread de
travail. L'echec etait juste. Contourner par une substitution aurait laisse la
dependance — la seule chose qui gere le cycle de vie des connexions en
production — jamais exercee.
"""

from __future__ import annotations

import ast
import sqlite3
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fundora_prospect import api, collecte, entrepot, mcp_server
from fundora_prospect.bodacc import Annonce, Cedant, ResultatRecherche
from fundora_prospect.enrichment import Enrichissement
from fundora_prospect.models import StatutEntreprise
from fundora_prospect.prix import Confiance, PrixCession, Qualification
from tests.test_mcp_server import appeler

MONTANT_MIN = 100_000.0


def annonce(
    identifiant: str,
    montant: float = 400_000.0,
    jours: int = 30,
    qualification: Qualification = Qualification.ACHAT,
    siren: str | None = "852872563",
) -> Annonce:
    acte = date.today() - timedelta(days=jours)
    return Annonce(
        id=identifiant,
        date_parution=acte,
        date_acte=acte,
        departement="06",
        url_publication=f"https://www.bodacc.fr/x/{identifiant}",
        categorie_vente=None,
        activite=None,
        cedant=Cedant(denomination=f"CEDANT {identifiant}", type_personne="pm", siren=siren),
        prix=PrixCession(
            montant=montant,
            devise="EUR",
            qualification=qualification,
            methode="test",
            texte_source="",
            confiance=Confiance.ACTE_DATE,
            ecart_acte_jours=0,
        ),
    )


def corpus() -> list[Annonce]:
    """Trois annonces choisies pour que le decompte des refus soit NON VIDE et
    porte PLUSIEURS motifs distincts.

    Un corpus tout-classable rendrait `ecartes` vide des deux cotes, et la
    comparaison des vocabulaires serait vraie sans rien garder — le corpus
    degenere, applique a un test de comparaison.
    """
    return [
        annonce("RETENU", montant=400_000.0),
        annonce("APPORT", montant=500_000.0, qualification=Qualification.APPORT),
        annonce("PETIT", montant=50_000.0),
    ]


def enrichir_stub(siren: str, **_: object) -> Enrichissement:
    return Enrichissement(
        siren=str(siren), statut=StatutEntreprise.ACTIVE, code_ape="56.10A",
        section_ape="I", motif="fixture",
    )


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    """`FUNDORA_DB` plutot qu'une substitution de la dependance.

    **La substitution etait un faux ami**, et elle a echoue pour la bonne
    raison : elle injectait une connexion creee dans le thread du test, alors
    que `TestClient` execute les routes dans un thread de travail. SQLite le
    refuse — c'est exactement le bug que `connexion()` evite en production, et
    le contourner en test aurait rendu la dependance non testee.

    Par la variable d'environnement, la vraie dependance tourne : une connexion
    ouverte et fermee par requete, dans le bon thread.
    """
    monkeypatch.setenv(entrepot.VARIABLE_BASE, str(tmp_path / "api.db"))
    connexion = entrepot.ouvrir()
    yield connexion
    connexion.close()


@pytest.fixture
def base_peuplee(base: sqlite3.Connection) -> sqlite3.Connection:
    """Remplie par le VRAI job de collecte, pas par des `INSERT` a la main.

    Un dict monte a la main decrirait un contrat que la source n'honore
    peut-etre pas — c'est le sixieme visage, et il a deja coute un test a ce
    projet. Ici la chaine est complete : job -> base -> lecture -> route.
    """
    collecte.balayer(
        base,
        departements=["06"],
        rechercher=lambda **_: ResultatRecherche(
            annonces=corpus(), publiees=len(corpus()), rapatriees=len(corpus())
        ),
        enrichir=enrichir_stub,
    )
    return base


@pytest.fixture
def client(base_peuplee: sqlite3.Connection) -> TestClient:
    return TestClient(api.app)


def reponse_mcp(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """La MEME recherche, par l'autre surface."""
    monkeypatch.setattr(
        mcp_server,
        "rechercher",
        lambda **_: ResultatRecherche(
            annonces=corpus(), publiees=len(corpus()), rapatriees=len(corpus())
        ),
    )
    monkeypatch.setattr(mcp_server, "enrichir", enrichir_stub)
    return appeler(
        "search_liquidity_events",
        {"departement": "06", "mois": 12, "montant_min": MONTANT_MIN},
    ).structured_content


# --- 1. Les deux surfaces rendent la meme forme -------------------------------


def test_les_deux_surfaces_rendent_les_MEMES_CLEFS_d_enveloppe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chaque surface monte son enveloppe a la main. Une clef renommee d'un
    cote passerait inapercue des deux — chacune est verte avec la sienne."""
    web = client.get("/leads", params={"departement": "06", "montant_min": MONTANT_MIN}).json()
    mcp = reponse_mcp(monkeypatch)
    assert set(web) == set(mcp)
    assert set(web["periode"]) == set(mcp["periode"])


def test_les_deux_surfaces_emploient_le_MEME_VOCABULAIRE_de_refus(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le vocabulaire des motifs, pas leur decompte.

    Les populations different par construction et c'est documente ; les MOTS,
    eux, viennent de `motif_ecart_faits` et ne doivent jamais diverger. « apport »
    d'un cote et « apport en nature » de l'autre casserait tout comptage
    agregeant les deux sources.
    """
    web = client.get("/leads", params={"departement": "06", "montant_min": MONTANT_MIN}).json()
    mcp = reponse_mcp(monkeypatch)

    motifs_web = set(web["statistiques"]["ecartes"])
    motifs_mcp = set(mcp["statistiques"]["ecartes"])
    assert motifs_web, "corpus degenere : sans refus, la comparaison ne garde rien"
    assert "apport" in motifs_web, "le corpus doit porter au moins deux motifs distincts"
    assert "sous le montant minimum" in motifs_web
    assert motifs_web == motifs_mcp


def test_les_deux_surfaces_rendent_le_MEME_BREAKDOWN(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contrainte 5 : le detail du calcul doit etre le meme partout. Deux
    surfaces qui nommeraient leurs criteres autrement rendraient l'explication
    incomparable d'un canal a l'autre."""
    web = client.get("/leads", params={"departement": "06", "montant_min": MONTANT_MIN}).json()
    mcp = reponse_mcp(monkeypatch)
    assert web["leads"] and mcp["leads"], "sans lead des deux cotes, rien n'est compare"

    assert set(web["leads"][0]) == set(mcp["leads"][0])
    assert set(web["leads"][0]["breakdown"][0]) == set(mcp["leads"][0]["breakdown"][0])
    assert {c["critere"] for c in web["leads"][0]["breakdown"]} == {
        c["critere"] for c in mcp["leads"][0]["breakdown"]
    }


def test_leads_porte_les_compteurs_DE_LA_COLLECTE(client: TestClient) -> None:
    """Sans eux, le resume dirait « l'etendue de la collecte n'est pas connue »
    alors que le job a tourne.

    Une base ne sait pas, par elle-meme, ce qu'elle n'a pas recu : c'est la
    ligne `collecte` qui le lui dit. Oublier de la passer a `lire` ne casse
    rien de visible — la reponse reste plausible, simplement plus modeste
    qu'elle ne devrait.
    """
    statistiques = client.get("/leads", params={"departement": "06"}).json()["statistiques"]
    assert statistiques["annonces_publiees"] == 3, "ce que la source declarait contenir"
    assert statistiques["evenements_en_base"] == 3


def test_leads_respecte_la_limite_SANS_mentir_sur_le_nombre_de_classables(
    base: sqlite3.Connection,
) -> None:
    """Deux grandeurs que la limite separe : ce qui est rendu, et ce qui a ete
    juge classable AVANT la coupe.

    Un corpus a un seul classable les rendrait egales — le test serait vert
    quelle que soit celle qu'on lui donne. Trois classables et `limite=1` les
    separent, et c'est la coupe qui doit se declarer, pas se cacher.
    """
    trois = [annonce("A", montant=400_000.0), annonce("B", montant=500_000.0),
             annonce("C", montant=600_000.0)]
    collecte.balayer(
        base, departements=["06"],
        rechercher=lambda **_: ResultatRecherche(annonces=trois, publiees=3, rapatriees=3),
        enrichir=enrichir_stub,
    )
    charge = TestClient(api.app).get("/leads", params={"departement": "06", "limite": 1}).json()
    assert len(charge["leads"]) == 1, "la coupe s'applique"
    assert charge["statistiques"]["classables"] == 3, "et elle se declare"


def test_leads_ne_regarde_que_la_fenetre_demandee(base: sqlite3.Connection) -> None:
    """`mois` doit filtrer, et le meme corpus doit repondre differemment selon
    la fenetre — sinon on ne saurait pas si c'est le filtre qui opere ou le
    corpus qui est vide."""
    vieille = [annonce("VIEILLE", jours=400)]
    collecte.balayer(
        base, departements=["06"], mois=24,
        rechercher=lambda **_: ResultatRecherche(annonces=vieille, publiees=1, rapatriees=1),
        enrichir=enrichir_stub,
    )
    client = TestClient(api.app)
    large = client.get("/leads", params={"departement": "06", "mois": 24}).json()
    etroite = client.get("/leads", params={"departement": "06", "mois": 6}).json()

    assert large["statistiques"]["evenements_en_base"] == 1
    assert etroite["statistiques"]["evenements_en_base"] == 0, "hors fenetre, donc jamais lue"


# --- 2. La provenance reste sur la porte unique -------------------------------


def test_chaque_lead_rendu_par_l_api_porte_les_QUATRE_champs(client: TestClient) -> None:
    """Contrainte 3. Les quatre champs, non vides, et une URL absolue —
    une provenance presente mais muette ne serait pas verifiable par un tiers."""
    leads = client.get("/leads", params={"departement": "06"}).json()["leads"]
    assert leads, "sans lead, l'assertion ne garde rien"
    for lead in leads:
        provenance = lead["provenance"]
        assert set(provenance) == {"source", "base_legale", "date_collecte", "url_publication"}
        assert all(str(v).strip() for v in provenance.values())
        assert provenance["url_publication"].startswith("https://")


def test_l_api_ne_serialise_aucun_lead_elle_meme() -> None:
    """**Le verrou, exprime comme une propriete du CODE et non de la sortie.**

    Une assertion sur la reponse ne peut pas distinguer un lead sorti par
    `provenance.serialiser` d'un lead monte a la main qui lui ressemble — c'est
    precisement le defaut de la Phase 3 bis, ou le serveur MCP assemblait son
    dict et n'y mettait qu'un des quatre champs. Le seul controle qui tranche
    porte sur le graphe d'appel.

    L'analyse est syntaxique et non textuelle : le mot « provenance » apparait
    dans la prose de l'entete, et un test qui le chercherait en clair
    interdirait d'en parler. On lit les imports et les appels.
    """
    arbre = ast.parse(Path(api.__file__).read_text(encoding="utf-8"))

    importes = {
        alias.name.split(".")[-1]
        for n in ast.walk(arbre)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for alias in n.names
    }
    assert "provenance" not in importes, (
        "api.py ne doit pas importer provenance : un lead sort par "
        "pipeline.lire -> classer -> provenance.serialiser, jamais d'ici"
    )

    appeles = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call)
    }
    assert not appeles & {"serialiser", "assembler", "Lead", "Provenance"}, (
        f"api.py construit un lead lui-meme : {appeles & {'serialiser', 'assembler'}}"
    )


def test_le_schema_interdit_qu_un_lead_intracable_ATTEIGNE_l_api(
    base: sqlite3.Connection,
) -> None:
    """**Sur cette surface, « provenance incomplete » est impossible par
    construction — et c'est le schema qui le garantit, pas la route.**

    Le chemin direct peut rencontrer une annonce sans URL : le BODACC en
    publie. La base, non — le `CHECK` du palier 1 refuse la ligne a l'ecriture,
    y compris en SQL direct. L'API n'a donc aucun garde-fou a ajouter, et c'est
    le genre d'affirmation qui doit etre prouvee plutot que deduite : « devrait
    valoir zero » est la formule qui a produit tous les defauts de ce projet.
    """
    collecte.balayer(
        base, departements=["06"],
        rechercher=lambda **_: ResultatRecherche(
            annonces=[annonce("RETENU")], publiees=1, rapatriees=1
        ),
        enrichir=enrichir_stub,
    )
    with pytest.raises(sqlite3.IntegrityError):
        base.execute("UPDATE evenement SET url_publication = 'pas-une-url'")


# --- 3. `/hypotheses` et `score_lead` sont la meme implementation -------------


def test_hypothese_et_score_lead_rendent_le_MEME_RESULTAT(client: TestClient) -> None:
    """Pas « la meme forme » : la MEME valeur, champ par champ.

    Les deux surfaces appellent `pipeline.evaluer_hypothese` puis
    `models.presenter_evaluation`. Si ce test tombe, c'est qu'une seconde
    implementation est nee — la troisieme fois que ce projet la rencontre.
    """
    arguments = {
        "montant_eur": 400_000.0,
        "date_acte": "2026-07-01",
        "departement": "06",
        "statut_cedant": "active",
    }
    web = client.post("/hypotheses", json=arguments).json()
    mcp = appeler("score_lead", arguments).structured_content
    assert web == mcp


def test_hypothese_explique_un_refus(client: TestClient) -> None:
    """Le refus doit passer par la meme porte que le succes : un statut cesse
    ferme, avec son motif, et pas un score de zero qui se noierait."""
    charge = client.post(
        "/hypotheses", json={"montant_eur": 400_000.0, "statut_cedant": "cessee"}
    ).json()
    assert charge["classable"] is False
    assert charge["motif_refus"]


def test_hypothese_refuse_un_montant_nul(client: TestClient) -> None:
    assert client.post("/hypotheses", json={"montant_eur": 0}).status_code == 422


# --- Les routes propres a la surface web --------------------------------------


def test_un_evenement_ecarte_reste_consultable(client: TestClient) -> None:
    """**La raison d'etre de `/evenements/{id}`.** `/leads` ne rend jamais un
    refuse ; c'est le seul endroit ou l'on peut demander pourquoi."""
    charge = client.get("/evenements/APPORT").json()
    assert charge["lead"] is None
    assert charge["motif_ecart"] == "apport"


def test_un_evenement_retenu_rend_son_lead_complet(client: TestClient) -> None:
    """L'autre moitie : sans elle, une route qui rendrait TOUJOURS `lead: None`
    passerait le test precedent."""
    charge = client.get("/evenements/RETENU").json()
    assert charge["motif_ecart"] is None
    assert charge["lead"]["score"] > 0
    assert charge["lead"]["provenance"]["url_publication"].startswith("https://")


def test_un_evenement_inconnu_rend_404(client: TestClient) -> None:
    assert client.get("/evenements/JAMAIS-VU").status_code == 404


def test_un_evenement_SANS_SIREN_ne_recupere_pas_le_journal_des_autres(
    base: sqlite3.Connection,
) -> None:
    """**Le piege de `transitions(siren=None)`** : sans siren, le filtre
    disparait et la fonction rend TOUT le journal.

    Sur une route de detail, ca ferait apparaitre l'historique de statut
    d'autres societes dans la fiche d'un evenement qui n'a pas de cedant
    identifie. Pas une fuite hors du systeme, mais une attribution fausse — et
    une attribution fausse dans une fiche d'audit vaut pire qu'une absence.

    Le corpus separe : une societe qui bascule VRAIMENT, et un evenement sans
    siren. Sans la premiere, le journal serait vide et l'assertion passerait
    quelle que soit l'implementation.
    """
    avec = annonce("AVEC", siren="852872563")
    sans = annonce("SANS", siren=None)
    for jour, statut in ((date.today(), StatutEntreprise.ACTIVE),
                         (date.today() + timedelta(days=40), StatutEntreprise.CESSEE)):
        collecte.balayer(
            base, departements=["06"], aujourdhui=jour,
            rechercher=lambda **_: ResultatRecherche(
                annonces=[avec, sans], publiees=2, rapatriees=2
            ),
            # `statut=statut` en defaut : sans lui la lambda capturerait la
            # variable de boucle, pas sa valeur. Ca marche par accident ici —
            # `balayer` est synchrone — et ruff a raison de le refuser.
            enrichir=lambda siren, _s=statut, **_: Enrichissement(
                siren=str(siren), statut=_s, code_ape="56.10A",
                section_ape="I", motif="fixture",
            ),
        )

    client = TestClient(api.app)
    assert client.get("/evenements/AVEC").json()["transitions"], "la bascule existe bien"
    assert client.get("/evenements/SANS").json()["transitions"] == [], (
        "sans cedant identifie, aucune transition ne peut lui etre attribuee"
    )


def test_collecte_rend_les_compteurs_du_job(client: TestClient) -> None:
    charge = client.get("/collecte", params={"departement": "06"}).json()
    assert charge["reserve"] is None
    assert charge["compteurs"]["annonces_publiees"] == 3


def test_collecte_le_DIT_quand_la_base_n_a_jamais_ete_remplie(
    base: sqlite3.Connection,
) -> None:
    """Une base peut exister sans avoir jamais ete remplie. 404 laisserait
    croire a un probleme de route ; l'absence de collecte est un etat, et il
    doit se lire — meme regle que « l'etendue de la collecte n'est pas connue »
    dans le resume."""
    charge = TestClient(api.app).get("/collecte", params={"departement": "13"}).json()
    assert charge["compteurs"] is None
    assert "aucune collecte" in charge["reserve"]


def test_sorties_distingue_les_bascules_des_SORTIES(base: sqlite3.Connection) -> None:
    """Deux grandeurs, deux noms, et un corpus qui les SEPARE.

    Deux societes : l'une bascule `active -> cessee` (une sortie), l'autre
    `active -> inconnu` (une bascule qui n'en est pas une). Avec une seule, un
    compteur qui rendrait toutes les transitions passerait — et `sorties`
    annoncerait un prospect perdu la ou l'API a simplement cesse de repondre.
    """
    deux = [annonce("A", siren="852872563"), annonce("B", siren="404833048")]
    apres = {"852872563": StatutEntreprise.CESSEE, "404833048": StatutEntreprise.INCONNU}

    def balayer(statuts: dict[str, StatutEntreprise] | None, jour: date) -> None:
        collecte.balayer(
            base, departements=["06"], aujourdhui=jour,
            rechercher=lambda **_: ResultatRecherche(annonces=deux, publiees=2, rapatriees=2),
            enrichir=lambda siren, **_: Enrichissement(
                siren=str(siren),
                statut=(statuts or {}).get(str(siren), StatutEntreprise.ACTIVE),
                code_ape="56.10A", section_ape="I", motif="fixture",
            ),
        )

    balayer(None, date.today())
    balayer(apres, date.today() + timedelta(days=40))

    charge = TestClient(api.app).get("/sorties").json()
    assert charge["transitions_observees"] == 2, "les deux societes ont bascule"
    assert [s["siren"] for s in charge["sorties"]] == ["852872563"], "une seule est sortie"
    assert charge["sorties"][0]["statut_apres"] == "cessee"


def test_un_departement_illisible_rend_422(client: TestClient) -> None:
    """Le vocabulaire du domaine leve `ValueError` ; c'est une faute de
    l'appelant, pas du serveur. 500 le ferait chercher au mauvais endroit."""
    reponse = client.get("/leads", params={"departement": "Nice"})
    assert reponse.status_code == 422
    assert "06" in reponse.json()["detail"], "le message doit montrer la forme attendue"
