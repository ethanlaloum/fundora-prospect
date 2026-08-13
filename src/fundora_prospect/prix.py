"""Parsing et qualification du prix de cession.

Le prix n'a pas de champ dedie dans le BODACC : il est en texte semi-structure
dans `listeetablissements.etablissement.origineFonds`.

Ce module repond a UNE question : **ce montant decrit-il bien la transaction
annoncee ?** C'est de la qualite de donnee. Savoir si le cash est encore
disponible releve de la pertinence commerciale, donc du scoring (Phase 2).
Melanger les deux ferait fuiter la regle metier dans le parser : le jour ou la
fenetre commerciale change, il faudrait modifier ce fichier.

Trois gardes, par ordre de precedence :

1. **Nature** — un apport n'est pas une cession (contrainte 6). Le cedant
   recoit des parts, pas du cash. Discriminant lexical fiable :
   « montant evalue » (apport) contre « prix stipule » (achat).
2. **Devise** — le franc a disparu en 2002, le dataset commence en 2008. Un
   montant en francs ne peut pas decrire la cession publiee : il decrit une
   transaction anterieure. Mesure : 599 annonces nationales, jusqu'en 2026.
3. **Fraicheur de l'acte** — au-dela de 24 mois entre l'acte et la parution, la
   donnee ne decrit plus l'operation publiee. Couverture partielle : la date
   d'acte n'est lisible que dans 40 % des annonces.

La precedence compte pour la ventilation des motifs de rejet : un apport en
francs est compte comme apport, parce que la regle metier prime sur le defaut
de qualite de donnee.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

# 24 mois. Seuil de QUALITE DE DONNEE, pas de pertinence commerciale : la
# fenetre de fraicheur du scoring (18 mois) est un autre reglage, ailleurs.
# Choisi sur la distribution mesuree en Phase 0 : 0,49 % des actes tombent
# entre 1 et 2 ans, 0,96 % au-dela — la masse est au-dessus de 2 ans, ce qui
# signale deux populations distinctes. La cassure est la.
SEUIL_ACTE_JOURS = 730

# Bornes de plausibilite. Au-dela, le montant est marque mais CONSERVE : le
# plafonnement est une decision de scoring.
MONTANT_PLANCHER = 1_000.0
MONTANT_PLAFOND = 50_000_000.0


class Qualification(StrEnum):
    """Ce que le parser a conclu du montant trouve."""

    ACHAT = "achat"
    APPORT = "apport"
    DEVISE_OBSOLETE = "devise_obsolete"
    ACTE_TROP_ANCIEN = "acte_trop_ancien"
    ABSENT = "absent"


class Confiance(StrEnum):
    """Ce qu'on sait de la datation de l'operation."""

    ACTE_DATE = "acte_date"
    ACTE_INDATABLE = "acte_indatable"


@dataclass(frozen=True)
class PrixCession:
    """Resultat de parsing, avec de quoi expliquer le calcul (contrainte 5)."""

    montant: float | None
    devise: str | None
    qualification: Qualification
    methode: str
    texte_source: str
    confiance: Confiance
    ecart_acte_jours: int | None = None
    aberrant: bool = False

    @property
    def retenu(self) -> bool:
        return self.qualification is Qualification.ACHAT


# --- Motifs -------------------------------------------------------------------

_ACHAT = r"prix\s+stipul[ée]e?\s+(?:de\s+)?"
_APPORT = r"montant\s+[ée]valu[ée]e?\s+(?:[aà]\s+)?"
_NOMBRE = r"([\d][\d\s  .,]*)"
_DEVISE = r"(euros?|eur|€|francs?\s+francais|francs?\s+fran[çc]ais|francs?|frf|f)\b"

MOTIF_ACHAT = re.compile(_ACHAT + _NOMBRE + r"\s*" + _DEVISE, re.IGNORECASE)
MOTIF_APPORT = re.compile(_APPORT + _NOMBRE + r"\s*" + _DEVISE, re.IGNORECASE)

MOTIF_DATE_ACTE = re.compile(r"[Aa]cte\s+en\s+date\s+du\s+(\d{2})/(\d{2})/(\d{4})")

_DEVISES_OBSOLETES = {"FRF"}


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if not unicodedata.combining(c))


def normaliser_devise(brut: str) -> str:
    """`euros`, `EUR`, `€` -> EUR ; `francs`, `FRANCS FRANCAIS`, `FRF`, `F` -> FRF."""
    token = _sans_accents(brut).strip().lower()
    if token.startswith("euro") or token in {"eur", "€"}:
        return "EUR"
    return "FRF"


def normaliser_montant(brut: str) -> float | None:
    """Normalise les formats observes : `70000.00`, `52.485,00`, `1 250 000,50`.

    Regle de separateur decimal : quand les deux caracteres sont presents, le
    DERNIER est le decimal. Quand un seul est present, il n'est decimal que
    s'il est suivi de une ou deux decimales — le corpus ecrit les centimes sur
    deux chiffres, donc trois chiffres apres un point sont des milliers
    (`52.485` = 52 485).
    """
    texte = brut.strip()
    for espace in (" ", " ", " "):
        texte = texte.replace(espace, "")
    if not texte:
        return None

    dernier_point = texte.rfind(".")
    derniere_virgule = texte.rfind(",")

    if dernier_point >= 0 and derniere_virgule >= 0:
        separateur = max(dernier_point, derniere_virgule)
    elif dernier_point >= 0 or derniere_virgule >= 0:
        separateur = max(dernier_point, derniere_virgule)
        if len(texte) - separateur - 1 not in (1, 2):
            separateur = -1
    else:
        separateur = -1

    if separateur >= 0:
        entier = re.sub(r"[.,]", "", texte[:separateur])
        decimales = texte[separateur + 1 :]
        texte = f"{entier}.{decimales}"
    else:
        texte = re.sub(r"[.,]", "", texte)

    try:
        return float(texte)
    except ValueError:
        return None


def extraire_date_acte(descriptif: str | None) -> date | None:
    """Date de l'acte, lue dans `acte.descriptif`. Absente 60 % du temps."""
    if not descriptif:
        return None
    trouve = MOTIF_DATE_ACTE.search(descriptif)
    if not trouve:
        return None
    jour, mois, annee = (int(x) for x in trouve.groups())
    try:
        return date(annee, mois, jour)
    except ValueError:
        return None


def parser_prix(
    origine_fonds: str | None,
    *,
    date_acte: date | None = None,
    date_parution: date | None = None,
) -> PrixCession:
    """Extrait et qualifie le montant porte par `origineFonds`."""
    texte = origine_fonds or ""

    confiance = Confiance.ACTE_DATE if date_acte else Confiance.ACTE_INDATABLE
    ecart = (date_parution - date_acte).days if date_acte and date_parution else None

    def resultat(
        montant: float | None,
        devise: str | None,
        qualification: Qualification,
        methode: str,
    ) -> PrixCession:
        aberrant = montant is not None and not (MONTANT_PLANCHER <= montant <= MONTANT_PLAFOND)
        return PrixCession(
            montant=montant,
            devise=devise,
            qualification=qualification,
            methode=methode,
            texte_source=texte,
            confiance=confiance,
            ecart_acte_jours=ecart,
            aberrant=aberrant,
        )

    # 1. Nature — la regle metier prime (contrainte 6).
    apport = MOTIF_APPORT.search(texte)
    if apport:
        return resultat(
            normaliser_montant(apport.group(1)),
            normaliser_devise(apport.group(2)),
            Qualification.APPORT,
            "motif:montant_evalue",
        )

    achat = MOTIF_ACHAT.search(texte)
    if not achat:
        return resultat(None, None, Qualification.ABSENT, "aucun_motif")

    montant = normaliser_montant(achat.group(1))
    devise = normaliser_devise(achat.group(2))

    # 2. Devise obsolete — decrit forcement une transaction anterieure.
    if devise in _DEVISES_OBSOLETES:
        return resultat(montant, devise, Qualification.DEVISE_OBSOLETE, "motif:prix_stipule")

    # 3. Fraicheur de l'acte — garde partiel, 40 % de couverture.
    if ecart is not None and ecart > SEUIL_ACTE_JOURS:
        return resultat(montant, devise, Qualification.ACTE_TROP_ANCIEN, "motif:prix_stipule")

    if montant is None:
        return resultat(None, None, Qualification.ABSENT, "montant_illisible")

    return resultat(montant, devise, Qualification.ACHAT, "motif:prix_stipule")
