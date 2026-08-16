"""Client BODACC : recherche, depliage, extraction du cedant.

Point contre-intuitif du dataset : **les annonces sont redigees cote
acheteur**. `categorieVente` dit « Achat d'un fonds par… ». Le prospect — le
cedant, celui qui encaisse — est dans `listeprecedentproprietaire`, pas dans
`listepersonnes`. Une lecture naive du champ « commercant » designerait
l'acheteur.

Les sous-objets sont des JSON encodes en string, et les collections sont tantot
un objet, tantot une liste selon le nombre d'elements. Les deux formes doivent
etre gerees partout.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from fundora_prospect.http import creer_client
from fundora_prospect.prix import PrixCession, Qualification, extraire_date_acte, parser_prix

BASE = (
    "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1"
    "/catalog/datasets/annonces-commerciales"
)

DEPARTEMENTS_PACA = ("04", "05", "06", "13", "83", "84")

LIMITE_PAR_PAGE = 100


# --- Depliage -----------------------------------------------------------------


def deplier(valeur: Any) -> Any:
    """Decode les sous-objets encodes en JSON-string, laisse le reste intact."""
    if isinstance(valeur, str) and valeur.strip()[:1] in "{[":
        try:
            return json.loads(valeur)
        except json.JSONDecodeError:
            return valeur
    return valeur


def _en_liste(noeud: Any, cle: str) -> list[dict[str, Any]]:
    """Normalise `{cle: {...}}` et `{cle: [{...}, ...]}` en liste."""
    noeud = deplier(noeud) or {}
    if not isinstance(noeud, dict):
        return []
    contenu = noeud.get(cle)
    if isinstance(contenu, dict):
        return [contenu]
    if isinstance(contenu, list):
        return [x for x in contenu if isinstance(x, dict)]
    return []


def etablissements(annonce: dict[str, Any]) -> list[dict[str, Any]]:
    return _en_liste(annonce.get("listeetablissements"), "etablissement")


def personnes_precedentes(annonce: dict[str, Any]) -> list[dict[str, Any]]:
    return _en_liste(annonce.get("listeprecedentproprietaire"), "personne")


# --- Cedant -------------------------------------------------------------------


def normaliser_siren(brut: str | None) -> str | None:
    """L'API rend le SIREN espace : `325 662 559`."""
    if not brut:
        return None
    compact = "".join(brut.split())
    return compact if len(compact) == 9 and compact.isdigit() else None


@dataclass(frozen=True)
class Cedant:
    """Le prospect. `type_personne` decide de la base legale applicable.

    `pm` : societe cedante, prospection B2B, segment principal.
    `pp` : personne physique, segment secondaire — base legale distincte,
    a ne jamais melanger au segment principal dans un export.
    """

    denomination: str | None
    type_personne: str
    siren: str | None
    indivision: bool = False


def _denomination(personne: dict[str, Any]) -> str | None:
    for cle in ("denomination", "nomCommercial"):
        if personne.get(cle):
            return str(personne[cle])
    morale = personne.get("personneMorale")
    if isinstance(morale, dict) and morale.get("denomination"):
        return str(morale["denomination"])
    nom = " ".join(str(personne[cle]) for cle in ("nom", "nomUsage", "prenom") if personne.get(cle))
    return nom or None


def extraire_cedant(annonce: dict[str, Any]) -> Cedant | None:
    """Le cedant est le PRECEDENT proprietaire, pas l'annonceur.

    En indivision (1,6 % du flux), on retient la personne physique s'il y en a
    une — c'est elle qui porte la contrainte de base legale.
    """
    personnes = personnes_precedentes(annonce)
    if not personnes:
        return None

    physiques = [p for p in personnes if p.get("typePersonne") == "pp"]
    retenue = physiques[0] if physiques else personnes[0]
    type_personne = str(retenue.get("typePersonne") or "inconnu")

    immatriculation = retenue.get("numeroImmatriculation")
    siren = None
    if isinstance(immatriculation, dict):
        siren = normaliser_siren(immatriculation.get("numeroIdentification"))

    return Cedant(
        denomination=_denomination(retenue),
        type_personne=type_personne,
        siren=siren,
        indivision=len(personnes) > 1,
    )


# --- Annonce ------------------------------------------------------------------


@dataclass(frozen=True)
class Annonce:
    """Un evenement de liquidite, avec sa provenance (contrainte 3)."""

    id: str
    date_parution: date
    date_acte: date | None
    departement: str
    url_publication: str
    categorie_vente: str | None
    activite: str | None
    cedant: Cedant
    prix: PrixCession
    ambigu: bool = False


def _date(valeur: Any) -> date | None:
    try:
        return date.fromisoformat(str(valeur))
    except (TypeError, ValueError):
        return None


def _acte(annonce: dict[str, Any]) -> dict[str, Any]:
    acte = deplier(annonce.get("acte"))
    return acte if isinstance(acte, dict) else {}


def construire_annonce(brut: dict[str, Any]) -> Annonce | None:
    """Transforme une annonce brute en `Annonce`, ou None si elle n'est pas
    une cession exploitable.

    Ecarte les annonces sans cedant : 13 % du flux, ce sont des mises en
    activite. Aucun cedant, donc aucun prospect.
    """
    cedant = extraire_cedant(brut)
    if cedant is None:
        return None

    date_parution = _date(brut.get("dateparution"))
    if date_parution is None:
        return None

    acte = _acte(brut)
    date_acte = extraire_date_acte(acte.get("descriptif"))

    etabs = etablissements(brut)
    origines = [str(e.get("origineFonds") or "") for e in etabs]

    prix_par_etablissement = [
        parser_prix(origine, date_acte=date_acte, date_parution=date_parution)
        for origine in origines
    ]
    valorises = [p for p in prix_par_etablissement if p.montant is not None]

    # Multi-etablissements valorises : 0,1 % du flux, sous le seuil de 5 %.
    # On marque et on passe, plutot qu'une somme conditionnelle non testable
    # sur un cas par an. La regle complete est documentee dans CLAUDE.md.
    ambigu = len(valorises) > 1
    if ambigu:
        prix = PrixCession(
            montant=None,
            devise=None,
            qualification=Qualification.ABSENT,
            methode="ambigu:plusieurs_etablissements_valorises",
            texte_source=" | ".join(origines),
            confiance=prix_par_etablissement[0].confiance,
            ecart_acte_jours=prix_par_etablissement[0].ecart_acte_jours,
        )
    elif prix_par_etablissement:
        prix = max(prix_par_etablissement, key=lambda p: (p.retenu, p.montant or 0))
    else:
        prix = parser_prix("", date_acte=date_acte, date_parution=date_parution)

    vente = acte.get("vente") if isinstance(acte.get("vente"), dict) else {}

    return Annonce(
        id=str(brut.get("id") or ""),
        date_parution=date_parution,
        date_acte=date_acte,
        departement=str(brut.get("numerodepartement") or ""),
        url_publication=str(brut.get("url_complete") or ""),
        categorie_vente=vente.get("categorieVente"),
        activite=etabs[0].get("activite") if etabs else None,
        cedant=cedant,
        prix=prix,
        ambigu=ambigu,
    )


# --- Recherche ----------------------------------------------------------------


def _clause_departements(departements: Sequence[str]) -> str:
    return " OR ".join(f'numerodepartement="{d}"' for d in departements)


def construire_where(
    departements: Sequence[str] = DEPARTEMENTS_PACA,
    depuis: date | None = None,
    jusqu_a: date | None = None,
) -> str:
    clauses = [f'familleavis="vente" AND ({_clause_departements(departements)})']
    if depuis:
        clauses.append(f"dateparution >= date'{depuis.isoformat()}'")
    if jusqu_a:
        clauses.append(f"dateparution < date'{jusqu_a.isoformat()}'")
    return " AND ".join(clauses)


def rechercher_brut(
    client: httpx.Client,
    where: str,
    limite: int = 100,
) -> Iterable[dict[str, Any]]:
    """Pagine l'API. `limit` est plafonne a 100 par requete cote Opendatasoft."""
    recuperes = 0
    while recuperes < limite:
        reponse = client.get(
            f"{BASE}/records",
            params={
                "where": where,
                "limit": min(LIMITE_PAR_PAGE, limite - recuperes),
                "offset": recuperes,
            },
        )
        reponse.raise_for_status()
        resultats = reponse.json().get("results", [])
        if not resultats:
            return
        yield from resultats
        recuperes += len(resultats)


def compter(client: httpx.Client, where: str) -> int:
    reponse = client.get(f"{BASE}/records", params={"where": where, "limit": 0})
    reponse.raise_for_status()
    return int(reponse.json()["total_count"])


@dataclass(frozen=True)
class ResultatRecherche:
    """Ce que la recherche a trouve, ET ce qu'elle n'a pas regarde.

    Ne rendre que `annonces` obligeait l'appelant a presenter un sous-ensemble
    comme un total. Deux coupes se produisent avant que la liste existe :

    - le **plafond de rapatriement** : on ne lit que `limite` enregistrements
      sur les `publiees` que compte l'API ;
    - le **filtre du client** : `construire_annonce` ecarte les annonces sans
      cedant, ~13 % du flux d'apres la Phase 0.

    Aucune des deux n'etait visible dans le compte rendu. Les deux nombres sont
    donc portes ici, a cote de la liste, pour que l'appelant puisse dire sa
    propre incompletude au lieu de la taire.
    """

    annonces: list[Annonce]
    publiees: int
    rapatriees: int

    @property
    def plafond_atteint(self) -> bool:
        """Vrai des qu'une annonce publiee n'a pas ete rapatriee."""
        return self.rapatriees < self.publiees

    @property
    def non_exploitables(self) -> int:
        """Rapatriees mais ecartees par `construire_annonce` : sans cedant,
        sans date de parution. Un filtre reel, longtemps sans decompte."""
        return self.rapatriees - len(self.annonces)


def rechercher(
    departements: Sequence[str] = DEPARTEMENTS_PACA,
    depuis: date | None = None,
    jusqu_a: date | None = None,
    limite: int = 100,
    client: httpx.Client | None = None,
) -> ResultatRecherche:
    """Cessions exploitables sur la periode et les departements demandes.

    Le `compter` initial coute une requete a `limit=0`. C'est le prix du seul
    nombre qui dise ce qu'on n'a pas lu — negligeable devant la pagination
    qui suit, et sans lui le plafond serait invisible.
    """
    where = construire_where(departements, depuis, jusqu_a)
    propre = client is None
    client = client or creer_client()
    try:
        publiees = compter(client, where)
        bruts = list(rechercher_brut(client, where, limite))
        return ResultatRecherche(
            annonces=[
                annonce for brut in bruts if (annonce := construire_annonce(brut)) is not None
            ],
            publiees=publiees,
            rapatriees=len(bruts),
        )
    finally:
        if propre:
            client.close()
