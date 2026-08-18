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

Le schema porte `evenement`, `cedant` et `collecte`. `cedant_journal` et
`evenement_revision` arrivent avec les paliers qui les lisent. Une table creee
d'avance est de la structure morte, et `tools/symboles_morts.py` ne voit ni les
tables ni les colonnes — il audite les symboles. D'ou `VERSION_SCHEMA`.

**`collecte_ecart` n'existe pas, et c'est deliberé.** Les annonces ecartees
sont stockees : leur decompte par motif se RECALCULE depuis `evenement` par la
meme `motif_ecart_faits` que partout ailleurs. Une table qui le dupliquerait
deriverait le jour ou un motif est renomme — la lecon « un parametre recopie
derive de sa source », appliquee a une table. Ne sont stockes que les quatre
nombres qu'aucune relecture ne peut retrouver.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fundora_prospect.models import (
    Lead,
    LiquidityEvent,
    StatutEntreprise,
    TypeCedant,
)

VARIABLE_BASE = "FUNDORA_DB"

# 1 : evenement + cedant. 2 : collecte.
#
# Les ajouts sont purement additifs et le schema est ecrit en `IF NOT EXISTS` :
# ouvrir une base v1 cree la table manquante et rien d'autre. Le numero sert a
# constater ou on en est, pas a piloter une sequence de scripts — le jour ou une
# migration devra transformer des donnees existantes, elle ne pourra plus etre
# implicite, et ce numero sera ce qui permet de la declencher.
VERSION_SCHEMA = 2

# Un statut se perime ; une annonce, non. On resonde donc les societes ACTIVES
# passe ce delai.
TTL_ENRICHISSEMENT_JOURS = 30

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

-- Les compteurs de population : dates, et par (balayage, departement).
--
-- Cette table ne porte QUE ce qui n'est pas recalculable depuis `evenement`.
-- Le decompte des ecartes par motif n'y est pas : les annonces ecartees sont
-- stockees, donc leurs motifs se recalculent par `motif_ecart_faits`. Une
-- colonne qui les dupliquerait deriverait le jour ou un motif est renomme.
--
-- Restent quatre nombres qu'aucune relecture ne peut retrouver : ce que le
-- BODACC declarait contenir, ce qu'on en a rapatrie, ce que le plafond a
-- coupe, et les annonces sans cedant — ecartees avant d'avoir un `id`, donc
-- sans ligne ou etre comptees.
CREATE TABLE IF NOT EXISTS collecte (
    id                        INTEGER PRIMARY KEY,
    lot                       TEXT NOT NULL,
    departement               TEXT NOT NULL,
    fenetre_debut             TEXT NOT NULL,
    fenetre_fin               TEXT NOT NULL,
    lancee_a                  TEXT NOT NULL,

    -- NULL tant que le balayage n'est pas alle au bout. Un balayage interrompu
    -- laisse donc une trace qui se declare comme telle, au lieu de laisser
    -- croire a des compteurs complets.
    terminee_a                TEXT,

    annonces_publiees         INTEGER NOT NULL DEFAULT 0,
    annonces_rapatriees       INTEGER NOT NULL DEFAULT 0,
    annonces_exploitables     INTEGER NOT NULL DEFAULT 0,
    sans_cedant_ou_illisibles INTEGER NOT NULL DEFAULT 0,
    plafond_atteint           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_collecte_departement
    ON collecte (departement, lancee_a DESC);
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


# --- Lecture -------------------------------------------------------------------


@dataclass(frozen=True)
class EvenementStocke:
    """Un fait relu, ET la date a laquelle il a ete constate.

    Les deux voyagent ensemble parce que la seconde ne se deduit pas de la
    premiere. `date_collecte` vient de la BASE, jamais de l'horloge du lecteur :
    une provenance qui annoncerait la date du jour pretendrait qu'on vient de
    consulter le BODACC alors qu'on relit une ligne vieille d'une semaine. La
    contrainte 3 demande une date de collecte, pas une date de lecture.
    """

    event: LiquidityEvent
    date_collecte: date


def _en_evenement(ligne: sqlite3.Row) -> LiquidityEvent:
    """Reconstruit le fait. L'enrichissement est joint depuis `cedant`.

    Un cedant sans SIREN, ou dont la societe n'a jamais ete enrichie, retombe
    sur `INCONNU` avec son motif : c'est la regle de degradation de la Phase 3,
    et elle doit survivre au passage par la base — un lead sans enrichissement
    reste un lead valide.
    """
    statut = ligne["statut"]
    return LiquidityEvent(
        id=ligne["id"],
        date_parution=date.fromisoformat(ligne["date_parution"]),
        date_acte=date.fromisoformat(ligne["date_acte"]) if ligne["date_acte"] else None,
        departement=ligne["departement"],
        url_publication=ligne["url_publication"],
        montant_eur=ligne["montant_eur"],
        devise=ligne["devise"],
        qualification=ligne["qualification"],
        retenu=bool(ligne["retenu"]),
        aberrant=bool(ligne["aberrant"]),
        cedant_denomination=ligne["cedant_denomination"],
        cedant_type=TypeCedant(ligne["cedant_type"]),
        cedant_siren=ligne["cedant_siren"],
        cedant_indivision=bool(ligne["cedant_indivision"]),
        code_ape=ligne["code_ape"],
        section_ape=ligne["section_ape"],
        statut_cedant=StatutEntreprise(statut) if statut else StatutEntreprise.INCONNU,
        motif_enrichissement=ligne["motif_enrichissement"] or "enrichissement non effectue",
    )


def evenements(
    connexion: sqlite3.Connection,
    *,
    departements: Sequence[str] | None = None,
    depuis: date | None = None,
    jusqu_a: date | None = None,
) -> list[EvenementStocke]:
    """Les faits stockes, sans jugement.

    Ce module ne filtre que sur ce qui est indexe — departement et periode de
    parution. **Il ne filtre PAS sur le montant** : ce seuil est un critere
    commercial, il appartient au classement et il porte un motif de refus qui
    doit etre compte comme les autres. Le sortir en SQL ferait disparaitre les
    ecartes du decompte, ce qui est exactement le defaut « un tri en amont est
    un filtre ».

    Aucun tri non plus : l'ordre du classement depend du score, donc de la date
    de lecture. Trier ici serait un pre-classement, et un pre-classement qui
    n'obeit pas aux regles du classement final est un filtre deguise.
    """
    clauses: list[str] = []
    parametres: list[object] = []
    if departements:
        clauses.append(f"e.departement IN ({', '.join('?' * len(departements))})")
        parametres.extend(departements)
    if depuis is not None:
        clauses.append("e.date_parution >= ?")
        parametres.append(depuis.isoformat())
    if jusqu_a is not None:
        clauses.append("e.date_parution <= ?")
        parametres.append(jusqu_a.isoformat())

    ou = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    lignes = connexion.execute(
        "SELECT e.*, c.statut, c.code_ape, c.section_ape, "
        "       c.motif AS motif_enrichissement "
        "FROM evenement e LEFT JOIN cedant c ON c.siren = e.cedant_siren" + ou,
        parametres,
    ).fetchall()

    return [
        EvenementStocke(
            event=_en_evenement(ligne),
            date_collecte=date.fromisoformat(ligne["date_collecte"]),
        )
        for ligne in lignes
    ]


# --- Le TTL d'enrichissement ---------------------------------------------------


def sirens_a_enrichir(
    connexion: sqlite3.Connection,
    sirens: Iterable[str],
    *,
    aujourdhui: date,
    ttl_jours: int = TTL_ENRICHISSEMENT_JOURS,
) -> list[str]:
    """Parmi ces SIREN, ceux qui meritent un appel API. **Le gain du design.**

    Trois regles, dans cet ordre :

    1. **Jamais vu** -> a enrichir. C'est le cas nominal d'une premiere
       collecte.
    2. **Societe CESSEE** -> jamais resondee, quel que soit son age. Une
       personne morale radiee ne redevient pas active : le sondage serait un
       appel API garanti sans information. C'est une regle metier, pas une
       optimisation — et elle est verrouillee par un test, parce qu'une regle
       qui ne vit que dans un commentaire n'est qu'une affirmation.
    3. **Vu il y a plus de `ttl_jours`** -> a resonder. Un statut se perime,
       une annonce non : c'est le seul champ de l'enrichissement qui bouge.

    Le reste — actives vues recemment, statuts inconnus vus recemment — est
    laisse tranquille.

    L'ordre du resultat suit celui de l'entree, dedoublonne. Le job en depend
    pour rester reproductible.
    """
    demandes: list[str] = []
    for siren in sirens:
        if siren and siren not in demandes:
            demandes.append(siren)
    if not demandes:
        return []

    connus = {
        ligne["siren"]: (ligne["statut"], ligne["enrichi_a"])
        for ligne in connexion.execute(
            f"SELECT siren, statut, enrichi_a FROM cedant "
            f"WHERE siren IN ({', '.join('?' * len(demandes))})",
            demandes,
        )
    }

    a_faire: list[str] = []
    for siren in demandes:
        if siren not in connus:
            a_faire.append(siren)
            continue
        statut, enrichi_a = connus[siren]
        if statut == str(StatutEntreprise.CESSEE):
            continue
        if (aujourdhui - date.fromisoformat(enrichi_a)).days >= ttl_jours:
            a_faire.append(siren)
    return a_faire


def enrichissements_connus(
    connexion: sqlite3.Connection, sirens: Iterable[str]
) -> dict[str, sqlite3.Row]:
    """Ce que la base sait deja de ces societes, pour les SIREN qu'on ne
    resonde pas. Sans ca, un lead non resonde perdrait son statut a la
    reecriture — la ligne `cedant` est mise a jour depuis le `Lead`."""
    demandes = [s for s in dict.fromkeys(sirens) if s]
    if not demandes:
        return {}
    return {
        ligne["siren"]: ligne
        for ligne in connexion.execute(
            f"SELECT * FROM cedant WHERE siren IN ({', '.join('?' * len(demandes))})",
            demandes,
        )
    }


# --- Les compteurs de collecte -------------------------------------------------


def demarrer_collecte(
    connexion: sqlite3.Connection,
    *,
    lot: str,
    departement: str,
    fenetre_debut: date,
    fenetre_fin: date,
    lancee_a: date,
) -> int:
    """Ouvre une ligne de collecte, `terminee_a` a NULL.

    La ligne est ecrite AVANT le travail, pas apres. Un balayage interrompu
    laisse ainsi une trace qui se declare incomplete ; s'il n'ecrivait qu'a la
    fin, une interruption serait indistinguable d'un balayage jamais lance.
    """
    curseur = connexion.execute(
        "INSERT INTO collecte (lot, departement, fenetre_debut, fenetre_fin, lancee_a) "
        "VALUES (?, ?, ?, ?, ?)",
        (lot, departement, fenetre_debut.isoformat(), fenetre_fin.isoformat(),
         lancee_a.isoformat()),
    )
    connexion.commit()
    return int(curseur.lastrowid or 0)


def terminer_collecte(
    connexion: sqlite3.Connection,
    identifiant: int,
    *,
    terminee_a: date,
    annonces_publiees: int,
    annonces_rapatriees: int,
    annonces_exploitables: int,
    sans_cedant_ou_illisibles: int,
    plafond_atteint: bool,
) -> None:
    """Ferme la ligne. C'est `terminee_a` qui fait passer les compteurs du
    statut « partiels » a « complets »."""
    connexion.execute(
        "UPDATE collecte SET terminee_a = ?, annonces_publiees = ?, "
        "annonces_rapatriees = ?, annonces_exploitables = ?, "
        "sans_cedant_ou_illisibles = ?, plafond_atteint = ? WHERE id = ?",
        (
            terminee_a.isoformat(),
            annonces_publiees,
            annonces_rapatriees,
            annonces_exploitables,
            sans_cedant_ou_illisibles,
            int(plafond_atteint),
            identifiant,
        ),
    )
    connexion.commit()


def compteurs_de_collecte(
    connexion: sqlite3.Connection, *, departements: Sequence[str] | None = None
) -> dict[str, object] | None:
    """Ce que la derniere collecte de chaque departement a vu. `None` si aucune.

    **La derniere par departement, pas la somme de toutes.** Le job tourne
    periodiquement : additionner les passages compterait plusieurs fois les
    memes annonces publiees, et le total gonflerait a chaque execution sans que
    rien n'ait change dans la source.

    `collecte_partielle` est vrai des qu'une des lignes retenues n'a pas de
    `terminee_a`. Les compteurs sont alors ceux d'un balayage coupe au milieu :
    ils sous-estiment, et le resume doit le dire. C'est le meme defaut que le
    plafond de rapatriement compte comme la totalite — un sous-ensemble presente
    comme un total.
    """
    requete = (
        "SELECT * FROM collecte c1 WHERE c1.id = ("
        "  SELECT c2.id FROM collecte c2 WHERE c2.departement = c1.departement"
        "  ORDER BY c2.lancee_a DESC, c2.id DESC LIMIT 1"
        ")"
    )
    parametres: list[object] = []
    if departements:
        requete += f" AND c1.departement IN ({', '.join('?' * len(departements))})"
        parametres.extend(departements)

    lignes = connexion.execute(requete, parametres).fetchall()
    if not lignes:
        return None

    def total(colonne: str) -> int:
        return sum(ligne[colonne] for ligne in lignes)

    return {
        "annonces_publiees": total("annonces_publiees"),
        "annonces_rapatriees": total("annonces_rapatriees"),
        "annonces_exploitables": total("annonces_exploitables"),
        "sans_cedant_ou_illisibles": total("sans_cedant_ou_illisibles"),
        "plafond_atteint": any(ligne["plafond_atteint"] for ligne in lignes),
        "collecte_partielle": any(ligne["terminee_a"] is None for ligne in lignes),
    }
