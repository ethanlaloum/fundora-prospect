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
from fundora_prospect.models import StatutEntreprise, TypeCedant
from fundora_prospect.pipeline import LIMITE_DEFAUT, LIMITE_MAX, MOIS_MAX
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


@pytest.fixture
def client_riche(base: sqlite3.Connection) -> TestClient:
    """Un corpus **choisi pour que la coupe morde**.

    Les tests de `/ecartes` comparent deux grandeurs — combien correspondent au
    filtre, combien sont rendus. Avec trois annonces elles vaudraient le meme
    nombre et le test serait vert que le total soit compte avant ou apres la
    coupe. Il faut donc un motif abondant : six cessions sous le seuil, deux
    apports, une retenue.
    """
    corpus_riche = [annonce(f"PETIT{i}", montant=50_000.0) for i in range(6)]
    corpus_riche += [
        annonce(f"APPORT{i}", montant=500_000.0, qualification=Qualification.APPORT)
        for i in range(2)
    ]
    corpus_riche.append(annonce("RETENU", montant=400_000.0))
    collecte.balayer(
        base, departements=["06"],
        rechercher=lambda **_: ResultatRecherche(
            annonces=corpus_riche, publiees=len(corpus_riche), rapatriees=len(corpus_riche)
        ),
        enrichir=enrichir_stub,
    )
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


# --- /ecartes : la troisieme surface qui nomme les memes refus ----------------


def test_ecartes_et_leads_emploient_le_MEME_VOCABULAIRE(client_riche: TestClient) -> None:
    """**Troisieme surface a nommer ces refus, troisieme comparaison.**

    Les deux routes passent par `pipeline.lire`, donc les motifs sont les memes
    objets — mais c'est vrai aujourd'hui, pas par construction. Le jour ou
    quelqu'un donne a `/ecartes` son propre parcours « pour aller plus vite »,
    seul ce test le verra : chaque route isolee resterait verte avec son propre
    vocabulaire.
    """
    parametres = {"departement": "06", "mois": 12, "montant_min": MONTANT_MIN}
    comptes = client_riche.get("/leads", params=parametres).json()["statistiques"]["ecartes"]
    liste = client_riche.get("/ecartes", params={**parametres, "limite": 100}).json()["ecartes"]

    assert comptes, "corpus degenere : sans refus, la comparaison ne garde rien"
    assert len(comptes) >= 2, "il faut plusieurs motifs pour comparer des vocabulaires"
    assert {e["motif"] for e in liste} == set(comptes)


def test_les_comptes_de_leads_SE_DERIVENT_de_la_liste_d_ecartes(client_riche: TestClient) -> None:
    """Une source, pas deux.

    Avant, les comptes etaient tenus au vol dans un dict et la liste n'existait
    pas. Maintenant la liste est la source et le compte en decoule — ce test
    verrouille l'egalite motif par motif, pas seulement l'ensemble des cles.
    """
    parametres = {"departement": "06", "mois": 12, "montant_min": MONTANT_MIN}
    comptes = client_riche.get("/leads", params=parametres).json()["statistiques"]["ecartes"]
    liste = client_riche.get("/ecartes", params={**parametres, "limite": 100}).json()["ecartes"]

    recomptes: dict[str, int] = {}
    for e in liste:
        recomptes[e["motif"]] = recomptes.get(e["motif"], 0) + 1
    assert recomptes == comptes


def test_ecartes_se_filtre_par_motif_SANS_mentir_sur_le_total(client_riche: TestClient) -> None:
    """Le filtre restreint, et le total dit combien correspondent AVANT la coupe.

    Le corpus separe les deux : plus de correspondants que la limite, sinon le
    test serait vert que le total soit compte avant ou apres.
    """
    parametres = {"departement": "06", "mois": 12, "montant_min": MONTANT_MIN}
    comptes = client_riche.get("/leads", params=parametres).json()["statistiques"]["ecartes"]
    motif, total = max(comptes.items(), key=lambda kv: kv[1])
    assert total > 3, "il faut un motif abondant pour que la coupe morde"

    charge = client_riche.get("/ecartes", params={**parametres, "motif": motif, "limite": 3}).json()
    assert charge["correspondants"] == total, "le total se compte avant la coupe"
    assert charge["rendus"] == 3
    assert {e["motif"] for e in charge["ecartes"]} == {motif}


def test_le_lead_porte_la_FRAICHEUR_en_donnee_pas_seulement_en_prose(
    client: TestClient,
) -> None:
    """Le nombre de jours n'existait que dans le texte du motif.

    Une surface qui voudrait l'afficher devrait soit le recalculer — deuxieme
    calcul, donc divergence le jour ou la regle change — soit chercher le
    critere par son nom, donc recopier un mot du domaine. Il est desormais
    calcule une fois par `evaluer` et recopie tel quel.

    L'assertion croise les deux presentations : le nombre en donnee doit etre
    celui que la prose annonce. Verifier seulement sa presence laisserait
    passer un champ qui compte autre chose.
    """
    lead = client.get("/leads", params={"departement": "06"}).json()["leads"][0]
    assert lead["jours_ecoules"] == 30, "les annonces du corpus datent de 30 jours"
    assert lead["date_reference"] == (date.today() - timedelta(days=30)).isoformat()

    fraicheur = next(c for c in lead["breakdown"] if c["critere"] == "fraicheur")
    assert f"{lead['jours_ecoules']} jours" in fraicheur["motif"], (
        "la donnee et la prose doivent dire le meme nombre"
    )


def test_le_libelle_du_type_de_cedant_vient_du_COEUR(client: TestClient) -> None:
    """Le segment personne physique releve d'une base legale distincte.

    Le libelle vient de l'enum et d'elle seule : une surface qui ecrirait
    « personne physique » dans son propre code recopierait un vocabulaire du
    domaine au moment precis ou il faut le lire.
    """
    lead = client.get("/leads", params={"departement": "06"}).json()["leads"][0]
    assert lead["type_cedant"] == "pm"
    assert lead["type_cedant_libelle"] == TypeCedant.PERSONNE_MORALE.libelle


@pytest.mark.parametrize(
    ("type_cedant", "attendu"),
    [
        (TypeCedant.PERSONNE_MORALE, "personne morale"),
        (TypeCedant.PERSONNE_PHYSIQUE, "personne physique"),
        (TypeCedant.INCONNU, "type de cedant non renseigne"),
    ],
)
def test_chaque_segment_a_son_LIBELLE_PROPRE(type_cedant: TypeCedant, attendu: str) -> None:
    """Les trois, et trois textes distincts. Un libelle commun aux trois
    passerait le test precedent tout en effacant la distinction que la
    contrainte impose de garder lisible."""
    assert type_cedant.libelle == attendu
    assert len({t.libelle for t in TypeCedant}) == 3


def test_un_ecarte_NE_RESSEMBLE_PAS_a_un_lead(client: TestClient) -> None:
    """**Structurel, pas cosmetique.**

    Un ecarte qui porterait un `score` et un bloc `provenance` serait un second
    chemin par lequel quelque chose ayant la forme d'un lead quitte le systeme
    sans passer par `provenance.serialiser` — le defaut de la Phase 3 bis,
    rouvert par une route d'audit.

    `url_publication` reste : c'est ce qui rend le refus verifiable par un tiers.
    """
    e = client.get("/ecartes", params={"departement": "06", "limite": 1}).json()["ecartes"][0]
    assert "score" not in e
    assert "provenance" not in e
    assert "breakdown" not in e
    assert e["url_publication"].startswith("https://")
    assert e["motif"]


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
    assert charge["ecarte"]["motif"] == "apport"


def test_la_fiche_d_un_refus_porte_de_quoi_le_CONTREDIRE(client: TestClient) -> None:
    """Un motif seul n'est pas auditable.

    La route ne rendait qu'une chaine : le lecteur voyait « apport » et n'avait
    aucun moyen d'aller verifier. Un refus doit porter ses faits — le cedant, le
    montant, les dates — et surtout son `url_publication`, qui est ce qui le
    rend contestable chez le tiers.

    Les valeurs sont comparees a celles que `/ecartes` rend pour le meme
    evenement : deux vues d'un meme refus ne doivent pas differer, et seule leur
    comparaison peut le voir.
    """
    fiche = client.get("/evenements/APPORT").json()["ecarte"]
    liste = client.get("/ecartes", params={"departement": "06", "motif": "apport"}).json()
    depuis_la_liste = next(e for e in liste["ecartes"] if e["id"] == "APPORT")

    assert fiche == depuis_la_liste
    assert fiche["url_publication"].startswith("https://")
    assert fiche["cedant"] and fiche["montant_eur"] > 0


def test_un_evenement_retenu_rend_son_lead_complet(client: TestClient) -> None:
    """L'autre moitie : sans elle, une route qui rendrait TOUJOURS `lead: None`
    passerait le test precedent."""
    charge = client.get("/evenements/RETENU").json()
    assert charge["ecarte"] is None
    assert charge["lead"]["score"] > 0
    assert charge["lead"]["provenance"]["url_publication"].startswith("https://")
    # Sans lui, la fiche n'est pas atteignable depuis un lead : c'est la clef
    # que le front met dans le lien.
    assert charge["lead"]["id"] == "RETENU"


@pytest.mark.parametrize("identifiant", ["RETENU", "APPORT"])
def test_une_fiche_porte_un_lead_OU_un_refus_jamais_les_deux(
    client: TestClient, identifiant: str
) -> None:
    """L'invariant de la route, verifie sur les deux cas.

    Les deux nuls laisseraient une fiche muette sans que rien ne le signale ;
    les deux renseignes feraient coexister a l'ecran un prospect et son refus.
    Aucune assertion sur un seul cas ne voit ces deux defauts.
    """
    charge = client.get(f"/evenements/{identifiant}").json()
    assert (charge["lead"] is None) != (charge["ecarte"] is None), (
        f"{identifiant} : lead={charge['lead'] is not None} "
        f"ecarte={charge['ecarte'] is not None}"
    )


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
    fiche_avec = client.get("/evenements/AVEC").json()
    fiche_sans = client.get("/evenements/SANS").json()

    assert fiche_avec["transitions"], "la bascule existe bien"
    assert fiche_sans["transitions"] == [], (
        "sans cedant identifie, aucune transition ne peut lui etre attribuee"
    )

    # La fiche doit dire A QUI le journal se rapporte, sinon une liste vide se
    # lit comme « cette societe n'a jamais bouge » alors qu'elle veut dire
    # « aucune societe n'est identifiee ». Le siren est ce qui distingue les
    # deux, et il doit etre lisible sur la fiche elle-meme.
    porteur = fiche_sans["lead"] or fiche_sans["ecarte"]
    assert porteur["siren"] is None
    assert (fiche_avec["lead"] or fiche_avec["ecarte"])["siren"] == "852872563"


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
    # Le compteur des sorties est rendu par l'API parce que le front n'a pas le
    # droit de compter. Le corpus separe les deux grandeurs — 2 bascules, 1
    # sortie — sans quoi un compteur qui rendrait l'un pour l'autre passerait.
    assert charge["sorties_observees"] == 1
    assert charge["sorties_observees"] != charge["transitions_observees"]


def test_filtres_dit_l_UNITE_de_chaque_champ(client: TestClient) -> None:
    """Le front affiche des clefs prettifiees ; une clef ne dit pas son unite.

    Les deux confusions ont eu lieu en usage reel sur cet ecran : « Avril »
    saisi dans `mois`, et `limite=25` lu comme 25 millions d'euros. Les tests
    portent donc sur ce qui les distingue — l'unite nommee — et pas sur la
    presence d'une description non vide, qui serait satisfaite par n'importe
    quelle phrase.
    """
    par_nom = {f["nom"]: f for f in client.get("/filtres").json()["filtres"]}
    assert set(par_nom) == {"departement", "mois", "montant_min", "limite"}

    assert "mois" in par_nom["mois"]["description"].lower()
    assert "nombre" in par_nom["mois"]["description"].lower(), "un nombre, pas un nom de mois"
    assert "euro" in par_nom["montant_min"]["description"].lower()
    assert "lead" in par_nom["limite"]["description"].lower(), "des leads, pas des euros"


def test_filtres_lit_ses_bornes_DANS_LE_SCHEMA(client: TestClient) -> None:
    """Les bornes ne sont pas redeclarees : elles viennent de `Query(ge=, le=)`.

    Le test les compare aux constantes du coeur. Une seconde ecriture dans une
    phrase de description deriverait au premier elargissement de fenetre, et
    c'est le defaut signature de ce projet applique a une aide de saisie.
    """
    par_nom = {f["nom"]: f for f in client.get("/filtres").json()["filtres"]}

    assert par_nom["mois"]["maximum"] == MOIS_MAX
    assert par_nom["limite"]["maximum"] == LIMITE_MAX
    assert par_nom["limite"]["defaut"] == LIMITE_DEFAUT
    assert par_nom["montant_min"]["minimum"] == 0
    # Le departement n'a pas de borne numerique : un champ sans borne doit
    # rendre `null`, pas etre absent — sinon le front devrait deviner.
    assert par_nom["departement"]["maximum"] is None
    assert par_nom["departement"]["defaut"] == "PACA"


def test_un_departement_illisible_rend_422(client: TestClient) -> None:
    """Le vocabulaire du domaine leve `ValueError` ; c'est une faute de
    l'appelant, pas du serveur. 500 le ferait chercher au mauvais endroit."""
    reponse = client.get("/leads", params={"departement": "Nice"})
    assert reponse.status_code == 422
    assert "06" in reponse.json()["detail"], "le message doit montrer la forme attendue"


# Les DEUX chemins de refus de cette surface, et ils ne se ressemblaient pas.
#
# `ValueError` (le vocabulaire du domaine) passe par `_argument_invalide` et
# rend une chaine. La validation de FastAPI, elle, rendait nativement une LISTE
# d'objets `{loc, msg, input}` — une autre forme, sous la meme clef, avec le
# meme code HTTP.
#
# Constate en usage reel : une recherche « 06 / Avril / 300k / 500k » affichait
# « /leads : reponse 422 » au lieu de nommer les trois champs fautifs. Le front
# n'y pouvait rien — il attendait une chaine, et il en recevait une la moitie du
# temps.
REFUS = [
    ({"departement": "Nice"}, "departement", "le vocabulaire du domaine"),
    ({"mois": "Avril"}, "mois", "un entier attendu, un mot recu"),
    ({"montant_min": "300k"}, "montant_min", "un nombre attendu, un raccourci recu"),
    ({"limite": "500k"}, "limite", "idem sur la limite"),
    ({"mois": "0"}, "mois", "un entier valide mais hors bornes"),
    ({"limite": "99999"}, "limite", "au-dela du plafond du coeur"),
]


@pytest.mark.parametrize(("parametres", "champ", "pourquoi"), REFUS)
def test_tout_refus_rend_un_detail_TEXTUEL_qui_nomme_le_champ(
    client: TestClient, parametres: dict[str, str], champ: str, pourquoi: str
) -> None:
    """**Le contrat que le front consomme : `detail` est une chaine, toujours.**

    Le corpus couvre les deux gestionnaires — sans quoi il ne departagerait
    rien. Un jeu d'essai qui ne contiendrait que des departements illisibles
    serait vert avec une surface qui rend une liste sur tous les autres cas.

    Et l'assertion porte sur le CONTENU : une chaine non vide qui ne nomme pas
    le champ fautif laisse l'utilisateur deviner lequel de ses quatre filtres
    est en cause.
    """
    reponse = client.get("/leads", params=parametres)
    assert reponse.status_code == 422, pourquoi

    detail = reponse.json()["detail"]
    assert isinstance(detail, str), (
        f"detail est un {type(detail).__name__} : le front attend une chaine, "
        "et il affiche le code HTTP quand il n'en recoit pas"
    )
    assert champ in detail, f"le message doit nommer le champ fautif : {detail!r}"
    # Le champ est nomme comme l'appelant l'a ECRIT, pas comme le framework le
    # localise. « query.mois » contient bien « mois » — l'assertion precedente
    # passerait — mais parle un langage que celui qui a rempli le formulaire ne
    # connait pas.
    assert "query" not in detail and "body" not in detail, (
        f"le message parle le langage du framework : {detail!r}"
    )


def test_un_refus_de_validation_cite_la_valeur_RECUE(client: TestClient) -> None:
    """Nommer le champ ne suffit pas : « mois : doit etre un entier » laisse
    croire a une regle generale, quand le probleme est la valeur d'un coup.

    Corpus choisi pour que la valeur ne puisse pas apparaitre par hasard : un
    mot qui ne figure ni dans le nom du champ ni dans le message de la
    bibliotheque.
    """
    detail = client.get("/leads", params={"mois": "Avril"}).json()["detail"]
    assert "Avril" in detail, detail


def test_plusieurs_champs_fautifs_sont_TOUS_nommes(client: TestClient) -> None:
    """La recherche qui a produit le defaut en portait trois d'un coup.

    N'en nommer qu'un ferait corriger, relancer, echouer encore — trois fois.
    C'est le corpus degenere applique a un message : un seul champ fautif ne
    permet pas de distinguer « les nomme tous » de « nomme le premier ».
    """
    detail = client.get(
        "/leads",
        params={"departement": "06", "mois": "Avril", "montant_min": "300k", "limite": "500k"},
    ).json()["detail"]

    for champ in ("mois", "montant_min", "limite"):
        assert champ in detail, f"{champ} manque dans : {detail!r}"


def test_un_corps_invalide_rend_lui_aussi_un_detail_textuel(client: TestClient) -> None:
    """L'autre porte d'entree. `loc` y commence par « body » et non « query » :
    une extraction du nom de champ qui supposerait la seconde rendrait ici un
    message decale d'un cran, sans rien casser de visible."""
    detail = client.post("/hypotheses", json={"montant_eur": 0}).json()["detail"]
    assert isinstance(detail, str), detail
    assert "montant_eur" in detail, detail
    assert "body" not in detail, f"l'origine du champ n'interesse pas l'appelant : {detail!r}"


# --- La troisieme voie : /recherche -------------------------------------------
#
# Les tests de la boucle elle-meme sont dans `tests/test_agent.py`. Ceux-ci
# branchent la ROUTE sur le vrai `agent.analyser` — via les deux dependances,
# comme `connexion` — plutot que de substituer la fonction testee, ce qui
# reviendrait a ne verifier que le cablage.


def _route_agent(client_double: object, executer_double: object) -> TestClient:
    api.app.dependency_overrides[api.client_anthropic] = lambda: client_double
    api.app.dependency_overrides[api.executeur] = lambda: executer_double
    return TestClient(api.app)


@pytest.fixture(autouse=True)
def _nettoyer_les_substitutions() -> Iterator[None]:
    yield
    api.app.dependency_overrides.clear()


def test_recherche_separe_la_sortie_de_l_outil_et_la_prose(base: sqlite3.Connection) -> None:
    """L'enveloppe de la troisieme voie : trois clefs, et `outil` n'est pas
    reconstruit a partir de ce que le modele a dit."""
    from tests.test_agent import PROSE_MENSONGERE, client_nominal, executer_double

    reponse = _route_agent(client_nominal(), executer_double).post(
        "/recherche", json={"departement": "06", "limite": 25}
    )
    assert reponse.status_code == 200
    charge = reponse.json()

    assert set(charge) == {"outil", "analyse", "mesure"}
    # La prose annonce 3 leads et un score de 12 ; la sortie tient bon.
    assert charge["outil"]["statistiques"]["leads_rendus"] == 2
    assert charge["outil"]["leads"][0]["score"] == 98.6348
    assert charge["analyse"]["synthese"] == PROSE_MENSONGERE["synthese"]
    assert charge["mesure"]["tours"] == 2


def test_recherche_rend_les_leads_meme_sans_modele(base: sqlite3.Connection) -> None:
    """Degradation propre, verifiee a travers la route et pas seulement dans le
    coeur : une panne d'Anthropic ne coute que le commentaire."""
    from tests.test_agent import ClientEnPanne, executer_double

    charge = (
        _route_agent(ClientEnPanne(), executer_double)
        .post("/recherche", json={"departement": "06"})
        .json()
    )

    assert charge["analyse"]["disponible"] is False
    assert charge["outil"]["leads"], "les leads doivent survivre a la panne"


def test_recherche_refuse_un_argument_hors_bornes(base: sqlite3.Connection) -> None:
    """Memes bornes que `/leads` — sinon l'ecart mesure entre les deux voies ne
    voudrait plus rien dire."""
    from tests.test_agent import client_nominal, executer_double

    reponse = _route_agent(client_nominal(), executer_double).post(
        "/recherche", json={"departement": "06", "limite": 99999}
    )
    assert reponse.status_code == 422
    assert "limite" in reponse.json()["detail"]


def test_comparatif_rend_les_trois_voies_et_DEUX_ecarts(base_peuplee: sqlite3.Connection) -> None:
    """La route branche les trois voies sur les memes filtres.

    Le corpus de la base est celui du job de collecte ; celui des deux autres
    voies est le double du pipeline. Les ids different donc par CONSTRUCTION —
    et c'est exactement ce que `fraicheur_de_la_base` doit rendre lisible.
    """
    from tests.test_agent import client_nominal, executer_double

    charge = (
        _route_agent(client_nominal(), executer_double)
        .post("/comparatif", json={"departement": "06", "limite": 25})
        .json()
    )

    assert set(charge) == {"parametres", "voies", "effet_du_modele", "fraicheur_de_la_base"}
    assert set(charge["voies"]) == {"agent", "direct", "base"}
    # L'ecart qui compte : nul, parce que les deux cotes appellent la meme
    # fonction avec les memes arguments.
    assert charge["effet_du_modele"]["identiques"] is True
    # L'autre mesure autre chose, et le dit.
    assert charge["fraicheur_de_la_base"]["disponible"] is True
    assert "pas l'effet du modele" in charge["fraicheur_de_la_base"]["reserve"]
    assert charge["fraicheur_de_la_base"]["identiques"] is False
