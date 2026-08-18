"""L'entrepot — palier 1 : le schema et la porte d'ecriture.

## Ce que ces tests doivent prouver

La contrainte 3 tient aujourd'hui parce que `provenance.serialiser` n'accepte
qu'un `Lead`, donc une `Provenance` validee. **Le passage en base est
exactement le moment ou ce genre de verrou se dissout** : une table est un
second chemin de sortie, et un `INSERT` ecrit plus tard ne demande la
permission a personne.

Ces tests verifient donc DEUX barrages independants, parce qu'aucun ne suffit
seul — meme raisonnement que le hook et le transport pour la contrainte 2 :

1. **La porte Python.** `enregistrer` n'accepte qu'un `Lead`, comme
   `serialiser`. C'est le chemin nominal.
2. **Le schema lui-meme.** Les contraintes `CHECK` refusent une ligne
   intracable *meme inseree en SQL direct*, c'est-a-dire meme quand la porte
   Python est contournee. C'est l'equivalent au niveau du stockage de ce que
   `TransportWhitelist` fait au niveau reseau : a cet endroit, aucun chemin de
   code ne peut l'eviter.

Le second barrage est le seul qui vaille contre le code qui n'est pas encore
ecrit. Les tests qui l'exercent inserent donc du SQL a la main, exprimant
litteralement ce qu'un futur distrait ferait.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from fundora_prospect import entrepot
from fundora_prospect import provenance as prov
from fundora_prospect.models import (
    ContributionCritere,
    Evaluation,
    Lead,
    LiquidityEvent,
    StatutEntreprise,
    TypeCedant,
)

RACINE = Path(__file__).resolve().parents[1]
URL = "https://www.bodacc.fr/pages/annonces-commerciales-detail/?q.id=id:A20260153319"


def fabriquer_lead(
    identifiant: str = "A20260153319",
    type_cedant: TypeCedant = TypeCedant.PERSONNE_MORALE,
    siren: str | None = "852872563",
    statut: StatutEntreprise = StatutEntreprise.ACTIVE,
    montant: float = 185_000.0,
    date_collecte: date = date(2026, 8, 16),
) -> Lead:
    event = LiquidityEvent(
        id=identifiant,
        date_parution=date(2026, 8, 13),
        date_acte=date(2026, 7, 25),
        departement="13",
        url_publication=URL,
        montant_eur=montant,
        devise="EUR",
        qualification="achat",
        retenu=True,
        cedant_denomination="LE FOURNIL D ORNELLA",
        cedant_type=type_cedant,
        cedant_siren=siren,
        code_ape="10.71C",
        section_ape="C",
        statut_cedant=statut,
        motif_enrichissement="societe active",
    )
    evaluation = Evaluation(
        event_id=identifiant,
        classable=True,
        score=73.2,
        contributions=[
            ContributionCritere(
                critere="montant",
                poids=55.0,
                valeur_normalisee=0.61,
                points=33.6,
                motif="185,000 EUR, normalise en echelle log entre 10,000 et 1,580,000 EUR",
            )
        ],
    )
    return prov.assembler(event, evaluation, date_collecte=date_collecte)


@pytest.fixture
def base(tmp_path: Path) -> sqlite3.Connection:
    connexion = entrepot.ouvrir(tmp_path / "essai.db")
    yield connexion
    connexion.close()


def colonnes(connexion: sqlite3.Connection, table: str) -> set[str]:
    return {ligne["name"] for ligne in connexion.execute(f"PRAGMA table_info({table})")}


# --- Barrage 1 : la porte Python ----------------------------------------------


def test_enregistrer_n_accepte_qu_un_lead(base: sqlite3.Connection) -> None:
    """Meme controle que `serialiser`, pour la meme raison : tant qu'un second
    chemin accepte un dict, la contrainte ne vaut que par la discipline de
    celui qui ecrit le prochain appel."""
    event = fabriquer_lead().event
    with pytest.raises(TypeError, match="Lead"):
        entrepot.enregistrer(base, event)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Lead"):
        entrepot.enregistrer(base, {"id": "X", "url_publication": URL})  # type: ignore[arg-type]


def test_un_lead_complet_s_enregistre_avec_sa_provenance(base: sqlite3.Connection) -> None:
    entrepot.enregistrer(base, fabriquer_lead())
    ligne = base.execute("SELECT * FROM evenement").fetchone()

    assert ligne["id"] == "A20260153319"
    assert ligne["url_publication"] == URL
    assert ligne["date_collecte"] == "2026-08-16"
    assert ligne["cedant_type"] == "pm"
    assert ligne["montant_eur"] == 185_000.0


def test_l_enrichissement_est_keye_par_siren_pas_par_annonce(base: sqlite3.Connection) -> None:
    """Le statut est une propriete de la SOCIETE. Deux annonces du meme cedant
    ne doivent pas produire deux verites sur son statut."""
    entrepot.enregistrer(base, fabriquer_lead(identifiant="A1"))
    entrepot.enregistrer(base, fabriquer_lead(identifiant="A2"))

    assert base.execute("SELECT count(*) FROM evenement").fetchone()[0] == 2
    assert base.execute("SELECT count(*) FROM cedant").fetchone()[0] == 1
    assert base.execute("SELECT statut FROM cedant").fetchone()["statut"] == "active"


def test_recollecter_la_meme_annonce_ne_duplique_pas(base: sqlite3.Connection) -> None:
    """L'id BODACC est la cle naturelle. Une recollecte met a jour, elle
    n'empile pas."""
    entrepot.enregistrer(base, fabriquer_lead(montant=185_000.0))
    entrepot.enregistrer(base, fabriquer_lead(montant=190_000.0))

    lignes = base.execute("SELECT * FROM evenement").fetchall()
    assert len(lignes) == 1
    assert lignes[0]["montant_eur"] == 190_000.0


def test_la_premiere_collecte_ne_bouge_jamais(base: sqlite3.Connection) -> None:
    """Trois dates, trois significations — donc trois colonnes.

    Ce test a d'abord ete ecrit avec deux collectes A LA MEME DATE. Les trois
    colonnes y valaient le meme jour : le test etait vert quelle que soit celle
    qu'on lui donnait, et la mutation « `premiere_collecte` avance a chaque
    recollecte » y survivait. C'est la famille du corpus degenere, rencontree
    la semaine meme ou elle a ete ecrite dans CLAUDE.md.

    Il faut donc deux dates distinctes pour que les grandeurs se separent.
    """
    entrepot.enregistrer(base, fabriquer_lead(date_collecte=date(2026, 8, 16)))
    entrepot.enregistrer(
        base, fabriquer_lead(montant=190_000.0, date_collecte=date(2026, 9, 2))
    )

    ligne = base.execute("SELECT * FROM evenement").fetchone()
    assert ligne["premiere_collecte"] == "2026-08-16", "la premiere fois ne se reecrit pas"
    assert ligne["derniere_verification"] == "2026-09-02"
    assert ligne["date_collecte"] == "2026-09-02", "le fait stocke date de sa collecte"


# --- Barrage 2 : le schema, contre le code pas encore ecrit --------------------


@pytest.mark.parametrize(
    ("url", "pourquoi"),
    [
        ("", "une URL vide satisfait `NOT NULL` et ne trace rien"),
        ("   ", "une URL blanche non plus"),
        ("/pages/annonces-commerciales-detail/", "un chemin relatif n'est pas verifiable"),
        ("www.bodacc.fr/x/A1", "sans schema, l'URL ne s'ouvre pas telle quelle"),
        ("ftp://bodacc.fr/x/A1", "un autre protocole n'est pas une publication consultable"),
    ],
)
def test_le_schema_refuse_une_url_intracable_meme_en_sql_direct(
    base: sqlite3.Connection, url: str, pourquoi: str
) -> None:
    """**Le test qui compte.** Il n'utilise pas `enregistrer` : il ecrit le SQL
    a la main, exactement comme le ferait un futur appel qui aurait oublie la
    porte. Si ce test passe, la contrainte 3 ne survit pas au passage en base.
    """
    with pytest.raises(sqlite3.IntegrityError):
        base.execute(
            "INSERT INTO evenement (id, date_parution, departement, qualification, "
            "retenu, aberrant, cedant_type, cedant_indivision, url_publication, "
            "date_collecte, premiere_collecte, derniere_verification) "
            "VALUES ('X', '2026-08-13', '13', 'achat', 1, 0, 'pm', 0, ?, "
            "'2026-08-16', '2026-08-16', '2026-08-16')",
            (url,),
        )


@pytest.mark.parametrize("date_collecte", ["", "16/08/2026", "2026-8-16", "hier", "20260816"])
def test_le_schema_refuse_une_date_de_collecte_illisible(
    base: sqlite3.Connection, date_collecte: str
) -> None:
    """Une provenance dont la date n'est pas lisible ne dit pas quand la donnee
    a ete constatee. Le champ serait present et muet — le defaut exact que les
    validateurs de `Provenance` ferment cote Python."""
    with pytest.raises(sqlite3.IntegrityError):
        base.execute(
            "INSERT INTO evenement (id, date_parution, departement, qualification, "
            "retenu, aberrant, cedant_type, cedant_indivision, url_publication, "
            "date_collecte, premiere_collecte, derniere_verification) "
            "VALUES ('X', '2026-08-13', '13', 'achat', 1, 0, 'pm', 0, ?, ?, "
            "'2026-08-16', '2026-08-16')",
            (URL, date_collecte),
        )


def test_le_schema_refuse_un_segment_de_cedant_hors_vocabulaire(
    base: sqlite3.Connection,
) -> None:
    """`cedant_type` decide de la base legale a la lecture. Une valeur hors des
    trois connues produirait un segment qu'on ne sait pas qualifier, donc un
    export melange — ce que CLAUDE.md interdit."""
    with pytest.raises(sqlite3.IntegrityError):
        base.execute(
            "INSERT INTO evenement (id, date_parution, departement, qualification, "
            "retenu, aberrant, cedant_type, cedant_indivision, url_publication, "
            "date_collecte, premiere_collecte, derniere_verification) "
            "VALUES ('X', '2026-08-13', '13', 'achat', 1, 0, 'societe', 0, ?, "
            "'2026-08-16', '2026-08-16', '2026-08-16')",
            (URL,),
        )


def test_le_schema_refuse_un_statut_hors_vocabulaire(base: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        base.execute(
            "INSERT INTO cedant (siren, statut, motif, enrichi_a) "
            "VALUES ('852872563', 'radiee', 'x', '2026-08-16')"
        )


def test_un_evenement_ne_peut_pas_referencer_un_cedant_absent(
    base: sqlite3.Connection,
) -> None:
    """SQLite n'applique PAS les cles etrangeres par defaut : il faut
    `PRAGMA foreign_keys = ON` sur chaque connexion. Une contrainte declaree
    mais desactivee est une garantie qui n'existe que sur le papier — et rien
    ne la distingue d'une garantie reelle a la lecture du schema.

    Sans ce test, retirer le PRAGMA passait les 472 autres.
    """
    with pytest.raises(sqlite3.IntegrityError):
        base.execute(
            "INSERT INTO evenement (id, date_parution, departement, qualification, "
            "retenu, aberrant, cedant_type, cedant_siren, cedant_indivision, "
            "url_publication, date_collecte, premiere_collecte, derniere_verification) "
            "VALUES ('X', '2026-08-13', '13', 'achat', 1, 0, 'pm', '000000000', 0, ?, "
            "'2026-08-16', '2026-08-16', '2026-08-16')",
            (URL,),
        )


# --- Les deux textes de provenance sont DERIVES, jamais stockes ---------------


def test_ni_la_source_ni_la_base_legale_ne_sont_stockees(base: sqlite3.Connection) -> None:
    """Decision de conception, verrouillee ici.

    `source` est une constante et `base_legale` une fonction pure de
    `cedant_type`. Les stocker creerait deux textes qui derivent l'un de
    l'autre le jour d'une reformulation — la lecon « un parametre recopie
    derive de sa source », appliquee a une colonne. On stocke le FAIT
    (`cedant_type`), on derive le texte a la lecture.

    Sans ce test, la premiere relecture qui trouve la table « incomplete » y
    ajouterait les deux colonnes, et le jour ou `provenance.py` reformule un
    texte la base continuerait a servir l'ancien.
    """
    presentes = colonnes(base, "evenement")
    assert "source" not in presentes
    assert "base_legale" not in presentes
    assert "cedant_type" in presentes, "le fait dont les deux textes se derivent"


def test_le_schema_ne_porte_aucune_colonne_de_score(base: sqlite3.Connection) -> None:
    """La fraicheur decroit des le premier jour : un score stocke est faux le
    lendemain. Et une colonne que rien ne lit est de la donnee morte, que
    `tools/symboles_morts.py` ne verrait pas — il audite les symboles, pas les
    colonnes."""
    presentes = colonnes(base, "evenement")
    assert not [c for c in presentes if "score" in c]


# --- Contrainte 4 : la base ne vit pas dans le depot ---------------------------


def test_la_base_par_defaut_vit_hors_du_depot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Premier stockage DURABLE du projet, et il porte des noms de personnes :
    `cedant_denomination` retombe sur `nom + nomUsage + prenom` pour les
    cedants personne physique. Le `.gitignore` protege du commit, pas d'une
    archive du repertoire de travail."""
    monkeypatch.delenv(entrepot.VARIABLE_BASE, raising=False)
    chemin = entrepot.chemin_base()

    assert RACINE not in chemin.parents, f"{chemin} est dans le depot"
    assert chemin.is_absolute()


def test_la_variable_d_environnement_surcharge_le_chemin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(entrepot.VARIABLE_BASE, str(tmp_path / "ailleurs.db"))
    assert entrepot.chemin_base() == tmp_path / "ailleurs.db"


# --- Versionnement du schema --------------------------------------------------


def test_le_schema_porte_sa_version(base: sqlite3.Connection) -> None:
    """Les paliers suivants ajoutent des tables. Sans version, une base creee
    aujourd'hui et une base migree demain seraient indistinguables."""
    assert base.execute("PRAGMA user_version").fetchone()[0] == entrepot.VERSION_SCHEMA


def test_rouvrir_une_base_existante_ne_la_recree_pas(tmp_path: Path) -> None:
    chemin = tmp_path / "essai.db"
    premiere = entrepot.ouvrir(chemin)
    entrepot.enregistrer(premiere, fabriquer_lead())
    premiere.close()

    seconde = entrepot.ouvrir(chemin)
    assert seconde.execute("SELECT count(*) FROM evenement").fetchone()[0] == 1
    seconde.close()
