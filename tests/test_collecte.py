"""Le job de collecte — palier 3.

Trois choses a prouver, et la premiere n'etait jusqu'ici qu'une phrase :

1. **Le TTL.** « 30 jours pour les actives, jamais de re-enrichissement des
   cessees » etait ecrit dans CLAUDE.md avec sa propre reserve : *c'est une
   affirmation tant qu'un test ne la prouve pas*. Deux assertions distinctes,
   parce que ce sont deux regles distinctes — l'une est un delai, l'autre est
   une regle metier sans delai.
2. **La reprise.** Un balayage coupe laisse une ligne `collecte` sans
   `terminee_a`. Ses compteurs sous-estiment, et la lecture doit le dire :
   sinon c'est le plafond de rapatriement compte comme la totalite, deplace
   d'un cran.
3. **La deduplication par SIREN**, qui est le gain d'appels du design. Un
   chiffre qu'on annonce doit etre un chiffre qu'on mesure.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from fundora_prospect import collecte, entrepot
from fundora_prospect.bodacc import Annonce, Cedant, ResultatRecherche
from fundora_prospect.enrichment import Enrichissement
from fundora_prospect.models import StatutEntreprise
from fundora_prospect.pipeline import lire, resumer
from fundora_prospect.prix import Confiance, PrixCession, Qualification

AUJOURDHUI = date(2026, 8, 18)


def annonce(
    identifiant: str,
    siren: str | None = "852872563",
    montant: float = 400_000.0,
    qualification: Qualification = Qualification.ACHAT,
    departement: str = "06",
    url: str | None = None,
) -> Annonce:
    jour = AUJOURDHUI - timedelta(days=20)
    return Annonce(
        id=identifiant,
        date_parution=jour,
        date_acte=jour,
        departement=departement,
        url_publication=f"https://www.bodacc.fr/x/{identifiant}" if url is None else url,
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


@pytest.fixture
def base(tmp_path: Path) -> sqlite3.Connection:
    connexion = entrepot.ouvrir(tmp_path / "essai.db")
    yield connexion
    connexion.close()


class Compteur:
    """Un `enrichir` qui retient qui il a appele. Le nombre d'appels EST la
    mesure du design : le compter est le seul moyen de savoir si la
    deduplication opere."""

    def __init__(self, statut: StatutEntreprise = StatutEntreprise.ACTIVE) -> None:
        self.appels: list[str] = []
        self.statut = statut

    def __call__(self, siren: str, **_: object) -> Enrichissement:
        self.appels.append(str(siren))
        return Enrichissement(
            siren=str(siren), statut=self.statut, code_ape="56.10A",
            section_ape="I", motif="fixture",
        )


def recherche_de(annonces: list[Annonce], publiees: int | None = None) -> ResultatRecherche:
    total = len(annonces) if publiees is None else publiees
    return ResultatRecherche(annonces=annonces, publiees=total, rapatriees=total)


# --- 1. Le TTL ----------------------------------------------------------------


def enregistrer_cedant(
    base: sqlite3.Connection, siren: str, statut: StatutEntreprise, enrichi_a: date
) -> None:
    base.execute(
        "INSERT INTO cedant (siren, statut, motif, enrichi_a) VALUES (?, ?, ?, ?)",
        (siren, str(statut), "fixture", enrichi_a.isoformat()),
    )
    base.commit()


@pytest.mark.parametrize("age", [30, 31, 90, 400])
def test_une_active_perimee_est_reenrichie(base: sqlite3.Connection, age: int) -> None:
    """Un statut se perime : une societe active il y a plus de 30 jours peut
    avoir cesse depuis. C'est le seul champ de l'enrichissement qui bouge."""
    enregistrer_cedant(
        base, "852872563", StatutEntreprise.ACTIVE, AUJOURDHUI - timedelta(days=age)
    )
    assert entrepot.sirens_a_enrichir(
        base, ["852872563"], aujourdhui=AUJOURDHUI
    ) == ["852872563"]


@pytest.mark.parametrize("age", [0, 1, 29])
def test_une_active_fraiche_n_est_pas_resondee(base: sqlite3.Connection, age: int) -> None:
    """L'autre moitie du seuil. Sans ce cas, un TTL de zero jour passerait le
    test precedent — les deux bornes doivent etre exercees pour que le seuil
    soit garde, pas seulement franchi."""
    enregistrer_cedant(
        base, "852872563", StatutEntreprise.ACTIVE, AUJOURDHUI - timedelta(days=age)
    )
    assert entrepot.sirens_a_enrichir(base, ["852872563"], aujourdhui=AUJOURDHUI) == []


@pytest.mark.parametrize("age", [0, 1, 29, 30, 31, 400, 5_000])
def test_une_cessee_n_est_jamais_reenrichie(base: sqlite3.Connection, age: int) -> None:
    """**La regle metier, verrouillee.**

    Une personne morale radiee ne redevient pas active. Resonder son SIREN est
    un appel API garanti sans information — pas une precaution.

    Le parametrage couvre delibérement des ages DE PART ET D'AUTRE du seuil de
    30 jours, jusqu'a treize ans. Un test qui ne montrerait qu'une cessee
    fraiche serait vert meme si la regle etait « cessee = pas encore perimee » :
    on ne saurait pas si c'est le statut ou le delai qui l'a protegee. C'est la
    famille du corpus degenere, appliquee a un parametre.
    """
    enregistrer_cedant(
        base, "852872563", StatutEntreprise.CESSEE, AUJOURDHUI - timedelta(days=age)
    )
    assert entrepot.sirens_a_enrichir(base, ["852872563"], aujourdhui=AUJOURDHUI) == []


def test_un_siren_jamais_vu_est_enrichi(base: sqlite3.Connection) -> None:
    assert entrepot.sirens_a_enrichir(
        base, ["404833048"], aujourdhui=AUJOURDHUI
    ) == ["404833048"]


def test_le_ttl_distingue_les_statuts_dans_un_meme_lot(base: sqlite3.Connection) -> None:
    """Le cas qui compte vraiment : les trois populations dans le meme appel.
    Un test par statut isole ne prouve pas que la regle discrimine."""
    vieux = AUJOURDHUI - timedelta(days=200)
    enregistrer_cedant(base, "111111111", StatutEntreprise.ACTIVE, vieux)
    enregistrer_cedant(base, "222222222", StatutEntreprise.CESSEE, vieux)
    enregistrer_cedant(base, "333333333", StatutEntreprise.ACTIVE, AUJOURDHUI)
    enregistrer_cedant(base, "444444444", StatutEntreprise.INCONNU, vieux)

    a_faire = entrepot.sirens_a_enrichir(
        base,
        ["111111111", "222222222", "333333333", "444444444", "555555555"],
        aujourdhui=AUJOURDHUI,
    )
    assert a_faire == ["111111111", "444444444", "555555555"]


def test_le_job_ne_resonde_pas_une_cessee(base: sqlite3.Connection) -> None:
    """La regle doit tenir DANS le job, pas seulement dans la fonction qui la
    porte. Un balayage qui contournerait `sirens_a_enrichir` la perdrait."""
    enregistrer_cedant(
        base, "852872563", StatutEntreprise.CESSEE, AUJOURDHUI - timedelta(days=900)
    )
    compteur = Compteur()
    collecte.balayer(
        base,
        departements=["06"],
        aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de([annonce("A1")]),
        enrichir=compteur,
    )
    assert compteur.appels == [], "une cessee ne doit declencher aucun appel"


# --- 2. La deduplication par SIREN --------------------------------------------


def test_un_siren_cite_dix_fois_ne_coute_qu_un_appel(base: sqlite3.Connection) -> None:
    """Le gain du design. Le statut est une propriete de la SOCIETE : dix
    annonces du meme cedant rendraient dix fois la meme reponse."""
    corpus = [annonce(f"A{i}", siren="852872563") for i in range(10)]
    compteur = Compteur()
    resultat = collecte.balayer(
        base,
        departements=["06"],
        aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus),
        enrichir=compteur,
    )

    assert len(compteur.appels) == 1
    assert resultat.enrichissements == 1
    assert resultat.enrichissements_evites == 9
    assert resultat.economie == pytest.approx(0.9)
    assert resultat.evenements_ecrits == 10, "les dix evenements sont ecrits"

    # `cedants_distincts` compte des SOCIETES, pas des citations. Sans cette
    # assertion, retirer le dedoublonnage du job passait inapercu : les appels
    # API restaient corrects — `sirens_a_enrichir` dedoublonne aussi — mais le
    # compteur annoncait 10 societes la ou il n'y en a qu'une. Un compteur
    # nomme d'apres une population doit etre calcule sur cette population.
    assert resultat.cedants_distincts == 1


def test_un_second_balayage_ne_reenrichit_rien(base: sqlite3.Connection) -> None:
    """Idempotence : relancer le job le meme jour ne redemande rien a l'API."""
    corpus = [annonce("A1"), annonce("A2", siren="404833048")]
    premier = Compteur()
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=premier,
    )
    second = Compteur()
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=second,
    )

    assert len(premier.appels) == 2
    assert second.appels == []
    assert base.execute("SELECT count(*) FROM evenement").fetchone()[0] == 2


def test_un_statut_deja_connu_n_est_pas_efface(base: sqlite3.Connection) -> None:
    """Un SIREN qu'on ne resonde pas doit garder son statut : la ligne `cedant`
    est reecrite depuis le `Lead`, donc sans reinjecter ce qu'on sait, un
    second balayage repasserait tout le monde a INCONNU."""
    corpus = [annonce("A1")]
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=Compteur(),
    )
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=Compteur(),
    )
    assert base.execute("SELECT statut FROM cedant").fetchone()["statut"] == "active"


# --- 3. Ce que le job ecrit, et ce que la lecture en fait ---------------------


def test_le_job_ecrit_aussi_les_annonces_ecartees(base: sqlite3.Connection) -> None:
    """Sans les ecartees en base, leur decompte par motif cesserait d'etre
    recalculable a la lecture — et il faudrait une table pour le figer, qui
    deriverait au premier renommage."""
    corpus = [annonce("VENTE"), annonce("APPORT", qualification=Qualification.APPORT)]
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=Compteur(),
    )
    assert base.execute("SELECT count(*) FROM evenement").fetchone()[0] == 2

    resultat = lire(entrepot.evenements(base), aujourdhui=AUJOURDHUI)
    assert resultat.statistiques["ecartes"] == {"apport": 1}


def test_la_reserve_d_etendue_disparait_quand_le_job_a_tourne(
    base: sqlite3.Connection,
) -> None:
    """Les deux sens, avec la VRAIE source des compteurs.

    Le palier 2 le testait avec un dict ecrit a la main. Ici les compteurs
    viennent de la table que le job a remplie — c'est la seule facon de savoir
    si les deux morceaux s'emboitent reellement.
    """
    corpus = [annonce("A1")]
    avant = lire(entrepot.evenements(base), aujourdhui=AUJOURDHUI)
    assert "l'etendue de la collecte n'est pas connue" in resumer(avant.statistiques)

    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus, publiees=42), enrichir=Compteur(),
    )
    apres = lire(
        entrepot.evenements(base),
        aujourdhui=AUJOURDHUI,
        collecte=entrepot.compteurs_de_collecte(base),
    )
    resume = resumer(apres.statistiques)

    assert "42 annonces publiees" in resume
    assert "l'etendue de la collecte n'est pas connue" not in resume
    # Le referent de « classables » reste celui de la lecture : la grille a vu
    # tous les candidats, pas seulement un budget d'enrichis.
    assert "classables sur 1 candidats" in resume


def test_une_collecte_interrompue_ne_se_presente_pas_comme_complete(
    base: sqlite3.Connection,
) -> None:
    """**Le test de reprise.**

    Un balayage coupe au milieu laisse une ligne avec `terminee_a` a NULL. Ses
    compteurs sous-estiment ce que la source contenait. Les servir sans reserve
    serait exactement le defaut du plafond de rapatriement compte comme la
    totalite — un sous-ensemble presente comme un total.
    """
    entrepot.demarrer_collecte(
        base, lot="interrompu", departement="06",
        fenetre_debut=date(2025, 9, 1), fenetre_fin=AUJOURDHUI, lancee_a=AUJOURDHUI,
    )
    compteurs = entrepot.compteurs_de_collecte(base)

    assert compteurs is not None
    assert compteurs["collecte_partielle"] is True

    resume = resumer(
        lire(entrepot.evenements(base), aujourdhui=AUJOURDHUI, collecte=compteurs).statistiques
    )
    assert "n'est pas allee au bout" in resume


def test_une_collecte_terminee_ne_porte_pas_la_reserve(base: sqlite3.Connection) -> None:
    """L'autre sens : une reserve affichee en permanence cesse d'etre lue."""
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de([annonce("A1")]), enrichir=Compteur(),
    )
    compteurs = entrepot.compteurs_de_collecte(base)
    assert compteurs is not None
    assert compteurs["collecte_partielle"] is False

    resume = resumer(
        lire(entrepot.evenements(base), aujourdhui=AUJOURDHUI, collecte=compteurs).statistiques
    )
    assert "n'est pas allee au bout" not in resume


def test_une_reprise_apres_interruption_ferme_la_reserve(base: sqlite3.Connection) -> None:
    """Relancer le job apres une coupure doit rendre les compteurs complets.

    La ligne interrompue reste en base — c'est une trace, on ne la reecrit
    pas — mais `compteurs_de_collecte` ne retient que la DERNIERE par
    departement. Sans cette regle, une vieille coupure marquerait toutes les
    lectures suivantes comme partielles.
    """
    entrepot.demarrer_collecte(
        base, lot="interrompu", departement="06",
        fenetre_debut=date(2025, 9, 1), fenetre_fin=AUJOURDHUI, lancee_a=AUJOURDHUI,
    )
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de([annonce("A1")]), enrichir=Compteur(),
    )
    compteurs = entrepot.compteurs_de_collecte(base)

    assert compteurs is not None
    assert compteurs["collecte_partielle"] is False
    assert base.execute("SELECT count(*) FROM collecte").fetchone()[0] == 2, (
        "la ligne interrompue reste : c'est une trace"
    )


def test_les_compteurs_ne_s_additionnent_pas_entre_deux_passages(
    base: sqlite3.Connection,
) -> None:
    """Le job tourne periodiquement. Additionner les passages compterait
    plusieurs fois les memes annonces publiees, et le total gonflerait a chaque
    execution sans que rien n'ait change dans la source."""
    for jour in (AUJOURDHUI - timedelta(days=1), AUJOURDHUI):
        collecte.balayer(
            base, departements=["06"], aujourdhui=jour,
            rechercher=lambda **_: recherche_de([annonce("A1")], publiees=42),
            enrichir=Compteur(),
        )
    compteurs = entrepot.compteurs_de_collecte(base)
    assert compteurs is not None
    assert compteurs["annonces_publiees"] == 42, "la derniere, pas la somme"


def test_le_balayage_couvre_chaque_departement_demande(base: sqlite3.Connection) -> None:
    """Le perimetre est un parametre des maintenant : PACA en defaut, mais
    l'elargissement ne doit pas demander de refactoring."""
    vus: list[str] = []

    def rechercher(**kwargs: object) -> ResultatRecherche:
        departement = list(kwargs["departements"])[0]  # type: ignore[index]
        vus.append(departement)
        return recherche_de([annonce(f"A-{departement}", departement=departement)])

    resultat = collecte.balayer(
        base, departements=["06", "13", "83"], aujourdhui=AUJOURDHUI,
        rechercher=rechercher, enrichir=Compteur(),
    )
    assert vus == ["06", "13", "83"]
    assert resultat.evenements_ecrits == 3
    assert base.execute("SELECT count(*) FROM collecte").fetchone()[0] == 3


def test_une_annonce_intracable_est_un_incident_pas_une_ligne(
    base: sqlite3.Connection,
) -> None:
    """La contrainte 3 vaut aussi a l'ecriture par le job : une annonce sans
    URL ne devient pas une ligne, et ne disparait pas en silence non plus."""
    corpus = [annonce("TRACABLE"), annonce("SANS-URL", url="")]
    resultat = collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=Compteur(),
    )
    assert resultat.evenements_ecrits == 1
    assert len(resultat.incidents) == 1
    assert "SANS-URL" in resultat.incidents[0]


def test_le_job_n_applique_aucun_seuil_de_montant(base: sqlite3.Connection) -> None:
    """Le seuil est un filtre de LECTURE. L'appliquer a la collecte obligerait
    a recollecter pour le relever."""
    corpus = [annonce("GROSSE", montant=900_000), annonce("PETITE", montant=5_000)]
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=Compteur(),
    )
    assert base.execute("SELECT count(*) FROM evenement").fetchone()[0] == 2


# --- Migration ----------------------------------------------------------------


def test_ouvrir_une_base_v1_ajoute_la_table_collecte(tmp_path: Path) -> None:
    """Le schema est additif et ecrit en `IF NOT EXISTS` : ouvrir une base d'un
    palier precedent la complete sans rien detruire."""
    chemin = tmp_path / "v1.db"
    ancienne = sqlite3.connect(chemin)
    ancienne.executescript(
        "CREATE TABLE cedant (siren TEXT PRIMARY KEY, statut TEXT NOT NULL, "
        "code_ape TEXT, section_ape TEXT, motif TEXT NOT NULL, enrichi_a TEXT NOT NULL);"
        "PRAGMA user_version = 1;"
    )
    ancienne.close()

    connexion = entrepot.ouvrir(chemin)
    assert connexion.execute("PRAGMA user_version").fetchone()[0] == entrepot.VERSION_SCHEMA
    connexion.execute("SELECT count(*) FROM collecte")
    connexion.close()
