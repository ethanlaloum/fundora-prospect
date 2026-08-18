"""L'entrepot : le schema SQLite et la porte d'ecriture.

## Pourquoi une base

Le pipeline en direct paie, a chaque requete, une recherche BODACC plus un
appel d'enrichissement par lead. C'est lent, ca tape dans les limites de debit,
et ca impose les plafonds qu'on connait — annonces jamais lues, candidats non
enrichis faute de budget. Un job de collecte balaye sans contrainte de temps de
reponse et ecrit ici ; les lecteurs ne font que lire.

## Le verrou de la contrainte 3, et pourquoi il en faut DEUX ici

La tracabilite tient aujourd'hui parce que `provenance.serialiser` n'accepte
qu'un `Lead`, donc une `Provenance` validee. **Une table est un second chemin
de sortie**, et un `INSERT` ecrit dans six mois ne demandera la permission a
personne. Le verrou se dissoudrait exactement la.

Deux barrages, comme pour la contrainte 2 ou le hook barre l'agent et le
transport barre le code :

- **`enregistrer` n'accepte qu'un `Lead`.** C'est le chemin nominal, et le
  controle de type est ce qui ferme le contournement — pas de la defense
  d'usage.
- **Le schema refuse une ligne intracable.** Les `CHECK` sur `url_publication`
  et `date_collecte` s'appliquent au SQL direct, donc au code qui n'est pas
  encore ecrit. C'est le seul barrage qui protege de l'avenir.

## Ce qu'on stocke, et ce qu'on derive

`source` est une constante et `base_legale` une fonction pure de
`cedant_type`. **Les stocker creerait deux textes qui derivent l'un de l'autre**
le jour d'une reformulation — la lecon « un parametre recopie derive de sa
source », appliquee a une colonne. On stocke le fait, on derive le texte a la
lecture.

**Aucune colonne de score.** La fraicheur decroit des le premier jour, sans
plateau : un score stocke est faux le lendemain. Et la grille est rechargeable
sans toucher au code — un score gele annulerait cette propriete. Le score est
recalcule a la lecture, ce pour quoi `evaluer` a ete ecrite : pure,
deterministe, `aujourdhui` en parametre.

## On ne cree que ce qu'on utilise

Le schema de ce palier porte `evenement` et `cedant`, rien d'autre. Les tables
`collecte`, `cedant_journal` et `evenement_revision` arrivent avec les paliers
qui les lisent. Une table creee d'avance est de la structure morte, et
`tools/symboles_morts.py` ne voit ni les tables ni les colonnes — il audite les
symboles. D'ou `VERSION_SCHEMA` et une migration explicite a chaque palier.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fundora_prospect.models import Lead

VARIABLE_BASE = "FUNDORA_DB"

VERSION_SCHEMA = 1

# Vocabulaires fermes, repris des StrEnum du domaine. Les figer dans le schema
# est ce qui rend la base relisible sans le code : une valeur hors liste
# produirait un segment qu'on ne sait pas qualifier a la lecture.
_TYPES_CEDANT = ("pm", "pp", "inconnu")
_STATUTS = ("active", "cessee", "non_diffusible", "inconnu")
_QUALIFICATIONS = ("achat", "apport", "devise_obsolete", "acte_trop_ancien", "absent")


def _en_liste_sql(valeurs: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valeurs)


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS cedant (
    siren        TEXT PRIMARY KEY,
    statut       TEXT NOT NULL CHECK (statut IN ({_en_liste_sql(_STATUTS)})),
    code_ape     TEXT,
    section_ape  TEXT,
    motif        TEXT NOT NULL,
    enrichi_a    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evenement (
    id                    TEXT PRIMARY KEY,

    date_parution         TEXT NOT NULL,
    date_acte             TEXT,
    departement           TEXT NOT NULL,
    montant_eur           REAL,
    devise                TEXT,
    qualification         TEXT NOT NULL
                          CHECK (qualification IN ({_en_liste_sql(_QUALIFICATIONS)})),
    retenu                INTEGER NOT NULL,
    aberrant              INTEGER NOT NULL,

    cedant_denomination   TEXT,
    cedant_type           TEXT NOT NULL
                          CHECK (cedant_type IN ({_en_liste_sql(_TYPES_CEDANT)})),
    cedant_siren          TEXT REFERENCES cedant(siren),
    cedant_indivision     INTEGER NOT NULL,

    -- Provenance (contrainte 3). Sur la ligne, jamais dans une table jointe :
    -- un JOIN s'oublie, et un LEFT JOIN produit des NULL qui ressemblent a une
    -- ligne valide. Ici, « une ligne sans provenance » est irrepresentable.
    --
    -- Le CHECK sur l'URL est le seul barrage qui vaille contre le code pas
    -- encore ecrit : `NOT NULL` laisserait passer '' et un chemin relatif,
    -- c'est-a-dire un champ present et muet.
    url_publication       TEXT NOT NULL CHECK (
                              url_publication LIKE 'http://%'
                           OR url_publication LIKE 'https://%'),
    date_collecte         TEXT NOT NULL CHECK (
                              date_collecte GLOB
                              '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),

    premiere_collecte     TEXT NOT NULL,
    derniere_verification TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evenement_recherche
    ON evenement (departement, retenu, date_parution);
CREATE INDEX IF NOT EXISTS idx_evenement_cedant ON evenement (cedant_siren);
"""


def chemin_base() -> Path:
    """Emplacement du fichier SQLite, surchargeable par `FUNDORA_DB`.

    **Hors du depot, contrainte 4.** C'est le premier stockage durable du
    projet, et il porte des donnees personnelles reelles : `cedant_denomination`
    retombe sur `nom + nomUsage + prenom` quand le cedant est une personne
    physique. Le `.gitignore` protege du commit, pas d'une archive du
    repertoire de travail ni d'un partage d'ecran — meme raisonnement que pour
    les dumps d'exploration et le cache HTTP.
    """
    force = os.environ.get(VARIABLE_BASE)
    if force:
        return Path(force).expanduser()
    return Path.home() / ".cache" / "fundora-prospect" / "prospects.db"


def ouvrir(chemin: Path | str | None = None) -> sqlite3.Connection:
    """Ouvre la base, la cree si besoin, et rend une connexion prete.

    `foreign_keys` est active par connexion : SQLite l'ignore par defaut, et
    une contrainte declaree mais desactivee est exactement le genre de garantie
    qui n'existe que sur le papier.
    """
    cible = Path(chemin) if chemin is not None else chemin_base()
    cible.parent.mkdir(parents=True, exist_ok=True)

    connexion = sqlite3.connect(cible)
    connexion.row_factory = sqlite3.Row
    connexion.execute("PRAGMA foreign_keys = ON")
    connexion.executescript(SCHEMA)
    connexion.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")
    connexion.commit()
    return connexion


def enregistrer(connexion: sqlite3.Connection, lead: Lead) -> None:
    """**La porte d'ecriture unique.**

    Le controle de type joue ici le meme role que dans `provenance.serialiser` :
    accepter un dict ou un `LiquidityEvent` nu rouvrirait le chemin par lequel
    un evenement intracable entrerait en base. Un `Lead` ne peut pas exister
    sans `Provenance` validee — c'est ce qui rend l'ecriture sure par
    construction, avant meme que le schema n'ait a se defendre.

    L'`id` BODACC est la cle naturelle : recollecter met a jour, n'empile pas.
    `premiere_collecte` ne bouge jamais.
    """
    if not isinstance(lead, Lead):
        raise TypeError(
            f"enregistrer n'accepte qu'un Lead, recu {type(lead).__name__}. "
            "Un evenement sans provenance complete ne doit pas pouvoir entrer "
            "en base (contrainte 3) : construire la ligne a la main "
            "contournerait ce controle."
        )

    event = lead.event
    collecte = lead.provenance.date_collecte.isoformat()

    with connexion:
        # Le cedant d'abord : la cle etrangere de `evenement` le referencera.
        # L'enrichissement est une propriete de la SOCIETE, pas de l'annonce —
        # deux annonces du meme cedant ne doivent pas produire deux verites sur
        # son statut.
        if event.cedant_siren:
            connexion.execute(
                "INSERT INTO cedant (siren, statut, code_ape, section_ape, motif, enrichi_a) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(siren) DO UPDATE SET "
                "  statut = excluded.statut,"
                "  code_ape = excluded.code_ape,"
                "  section_ape = excluded.section_ape,"
                "  motif = excluded.motif,"
                "  enrichi_a = excluded.enrichi_a",
                (
                    event.cedant_siren,
                    str(event.statut_cedant),
                    event.code_ape,
                    event.section_ape,
                    event.motif_enrichissement,
                    collecte,
                ),
            )

        connexion.execute(
            "INSERT INTO evenement ("
            "  id, date_parution, date_acte, departement, montant_eur, devise,"
            "  qualification, retenu, aberrant, cedant_denomination, cedant_type,"
            "  cedant_siren, cedant_indivision, url_publication, date_collecte,"
            "  premiere_collecte, derniere_verification"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  date_parution = excluded.date_parution,"
            "  date_acte = excluded.date_acte,"
            "  departement = excluded.departement,"
            "  montant_eur = excluded.montant_eur,"
            "  devise = excluded.devise,"
            "  qualification = excluded.qualification,"
            "  retenu = excluded.retenu,"
            "  aberrant = excluded.aberrant,"
            "  cedant_denomination = excluded.cedant_denomination,"
            "  cedant_type = excluded.cedant_type,"
            "  cedant_siren = excluded.cedant_siren,"
            "  cedant_indivision = excluded.cedant_indivision,"
            "  url_publication = excluded.url_publication,"
            "  date_collecte = excluded.date_collecte,"
            "  derniere_verification = excluded.derniere_verification",
            (
                event.id,
                event.date_parution.isoformat(),
                event.date_acte.isoformat() if event.date_acte else None,
                event.departement,
                event.montant_eur,
                event.devise,
                event.qualification,
                int(event.retenu),
                int(event.aberrant),
                event.cedant_denomination,
                str(event.cedant_type),
                event.cedant_siren,
                int(event.cedant_indivision),
                lead.provenance.url_publication,
                collecte,
                collecte,
                collecte,
            ),
        )
