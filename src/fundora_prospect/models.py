"""Modeles du domaine.

`LiquidityEvent` est le fait brut : une cession, son montant, son cedant, sa
provenance. `Evaluation` est ce que la grille de ponderation en dit, avec le
detail de chaque point attribue. `Lead` reunit les deux et porte la
tracabilite exigee par la contrainte 3.

Le `cedant_type` est transporte jusqu'au `Lead` mais **n'entre jamais dans le
score** : c'est une contrainte de conformite (les personnes physiques relevent
d'une base legale distincte), pas un critere de qualification commerciale.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from fundora_prospect.bodacc import Annonce


class TypeCedant(StrEnum):
    """Determine la base legale applicable a la prospection."""

    PERSONNE_MORALE = "pm"
    PERSONNE_PHYSIQUE = "pp"
    INCONNU = "inconnu"


class LiquidityEvent(BaseModel):
    """Un evenement de liquidite : une cession avec un cedant identifie."""

    model_config = ConfigDict(frozen=True)

    id: str
    date_parution: date
    date_acte: date | None = None
    departement: str
    url_publication: str

    montant_eur: float | None = None
    devise: str | None = None
    qualification: str
    retenu: bool
    aberrant: bool = False

    # Renseigne par l'enrichissement en Phase 3 : BODACC ne porte aucun code
    # d'activite normalise.
    code_ape: str | None = None

    cedant_denomination: str | None = None
    cedant_type: TypeCedant = TypeCedant.INCONNU
    cedant_siren: str | None = None
    cedant_indivision: bool = False

    @classmethod
    def depuis_annonce(cls, annonce: Annonce) -> LiquidityEvent:
        try:
            type_cedant = TypeCedant(annonce.cedant.type_personne)
        except ValueError:
            type_cedant = TypeCedant.INCONNU

        return cls(
            id=annonce.id,
            date_parution=annonce.date_parution,
            date_acte=annonce.date_acte,
            departement=annonce.departement,
            url_publication=annonce.url_publication,
            montant_eur=annonce.prix.montant,
            devise=annonce.prix.devise,
            qualification=str(annonce.prix.qualification),
            retenu=annonce.prix.retenu,
            aberrant=annonce.prix.aberrant,
            cedant_denomination=annonce.cedant.denomination,
            cedant_type=type_cedant,
            cedant_siren=annonce.cedant.siren,
            cedant_indivision=annonce.cedant.indivision,
        )


class ContributionCritere(BaseModel):
    """La part d'un critere dans le score, et pourquoi (contrainte 5)."""

    model_config = ConfigDict(frozen=True)

    critere: str
    poids: float
    valeur_normalisee: float | None
    points: float
    motif: str


class Evaluation(BaseModel):
    """Resultat de la grille. `classable` a faux, le lead sort du flux avec
    son motif — jamais avec un score de zero, qui se noierait dans le
    classement au lieu d'etre auditable."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    classable: bool
    motif_refus: str | None = None
    score: float | None = None
    contributions: list[ContributionCritere] = Field(default_factory=list)


# Conserve pour compatibilite avec le vocabulaire de la spec.
ScoreBreakdown = Evaluation


class Provenance(BaseModel):
    """Contrainte 3. Le controle a la serialisation arrive en Phase 3."""

    model_config = ConfigDict(frozen=True)

    source: str
    base_legale: str
    date_collecte: date
    url_publication: str


class Lead(BaseModel):
    model_config = ConfigDict(frozen=True)

    event: LiquidityEvent
    evaluation: Evaluation
    provenance: Provenance
