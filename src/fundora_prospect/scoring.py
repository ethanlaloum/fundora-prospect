"""Grille de ponderation — A DIRE D'EXPERT.

**Ce n'est pas un modele.** Les poids sont des hypotheses commerciales, pas des
coefficients appris : aucune donnee de conversion n'existe pour les calibrer, on
ne sait pas quels leads se transforment. Le vocabulaire du module le dit —
`GrillePonderation`, `evaluer`, `Contribution`. Pas de `model`, pas de
`predict`, pas de `train`. Presenter cette grille comme un modele laisserait
croire a une validation empirique qui n'a pas eu lieu, et c'est indefendable
devant un CIF.

Les poids vivent dans `config/ponderation.toml`, charge au runtime. Recalibrer
la grille ne doit toucher aucun fichier `.py`.

La fonction `evaluer` est pure et deterministe : meme entree, meme sortie. La
date du jour est un parametre, pas un appel a `date.today()`.
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fundora_prospect.models import ContributionCritere, Evaluation, LiquidityEvent

CHEMIN_CONFIG = Path(__file__).resolve().parents[2] / "config" / "ponderation.toml"


# --- Configuration ------------------------------------------------------------


@dataclass(frozen=True)
class CritereMontant:
    poids: float
    motif: str
    echelle: str
    plancher_eur: float
    plafond_eur: float


@dataclass(frozen=True)
class CritereFraicheur:
    poids: float
    motif: str
    fenetre_pleine_jours: int
    fenetre_nulle_jours: int


@dataclass(frozen=True)
class CritereSecteur:
    poids: float
    motif: str
    codes_prioritaires: tuple[str, ...]


@dataclass(frozen=True)
class CritereDepartement:
    poids: float
    motif: str
    departements_prioritaires: tuple[str, ...]


@dataclass(frozen=True)
class Controle:
    correlation_montant_avertissement: float
    ecart_minimal_a_montant_egal: float


@dataclass(frozen=True)
class GrillePonderation:
    """Les poids et les seuils, tels que lus dans le fichier de configuration."""

    version: int
    date_calibration: str
    methode: str
    montant: CritereMontant
    fraicheur: CritereFraicheur
    secteur: CritereSecteur
    departement: CritereDepartement
    controle: Controle

    CHEMIN_DEFAUT = CHEMIN_CONFIG

    @classmethod
    def depuis_toml(cls, chemin: Path) -> GrillePonderation:
        charge = tomllib.loads(chemin.read_text(encoding="utf-8"))
        return cls(
            version=charge["version"],
            date_calibration=charge["date_calibration"],
            methode=charge["methode"],
            montant=CritereMontant(
                poids=charge["montant"]["poids"],
                motif=charge["montant"]["motif"].strip(),
                echelle=charge["montant"]["echelle"],
                plancher_eur=charge["montant"]["plancher_eur"],
                plafond_eur=charge["montant"]["plafond_eur"],
            ),
            fraicheur=CritereFraicheur(
                poids=charge["fraicheur"]["poids"],
                motif=charge["fraicheur"]["motif"].strip(),
                fenetre_pleine_jours=charge["fraicheur"]["fenetre_pleine_jours"],
                fenetre_nulle_jours=charge["fraicheur"]["fenetre_nulle_jours"],
            ),
            secteur=CritereSecteur(
                poids=charge["secteur"]["poids"],
                motif=charge["secteur"]["motif"].strip(),
                codes_prioritaires=tuple(charge["secteur"]["codes_prioritaires"]),
            ),
            departement=CritereDepartement(
                poids=charge["departement"]["poids"],
                motif=charge["departement"]["motif"].strip(),
                departements_prioritaires=tuple(charge["departement"]["departements_prioritaires"]),
            ),
            controle=Controle(
                correlation_montant_avertissement=charge["controle"][
                    "correlation_montant_avertissement"
                ],
                ecart_minimal_a_montant_egal=charge["controle"]["ecart_minimal_a_montant_egal"],
            ),
        )

    @classmethod
    def defaut(cls) -> GrillePonderation:
        return cls.depuis_toml(CHEMIN_CONFIG)


# --- Normalisations -----------------------------------------------------------


def normaliser_montant(montant: float | None, critere: CritereMontant) -> float | None:
    """Normalise en echelle LOGARITHMIQUE, entre 0 et 1.

    Le critere serait sinon lineaire sur une distribution qui ne l'est pas
    (mediane 110 k EUR, max 6,2 M). Le log preserve l'ordre, empeche le haut de
    la distribution d'ecraser le reste, et rend lisible l'ecart entre 200 et
    400 k EUR — la ou vit le volume. C'est aussi le sens metier : 200 -> 400 k
    change la capacite d'investissement, 5 -> 6 M non.

    Le plafond n'est pas une saturation metier : il borne une valeur aberrante
    mal parsee. Un plafond bas rendrait 6,2 M et 1 M equivalents alors que le
    premier est un meilleur prospect.
    """
    if montant is None:
        return None
    if montant <= critere.plancher_eur:
        return 0.0
    borne = min(montant, critere.plafond_eur)
    etendue = math.log(critere.plafond_eur) - math.log(critere.plancher_eur)
    return (math.log(borne) - math.log(critere.plancher_eur)) / etendue


def normaliser_fraicheur(jours: int, critere: CritereFraicheur) -> float:
    """Contribution pleine jusqu'a la fenetre, puis decroissance lineaire."""
    if jours <= critere.fenetre_pleine_jours:
        return 1.0
    if jours >= critere.fenetre_nulle_jours:
        return 0.0
    etendue = critere.fenetre_nulle_jours - critere.fenetre_pleine_jours
    return 1.0 - (jours - critere.fenetre_pleine_jours) / etendue


# --- Evaluation ---------------------------------------------------------------


def _motif_refus(event: LiquidityEvent) -> str | None:
    """Un evenement peut sortir du classement, jamais y entrer avec un zero."""
    if not event.retenu:
        return f"evenement non retenu par le parser (qualification : {event.qualification})"
    if event.aberrant:
        return (
            "montant aberrant : hors des bornes de plausibilite. Une donnee dont "
            "on ignore si elle est juste ne doit pas atterrir en tete du classement."
        )
    if event.montant_eur is None:
        return "aucun montant exploitable"
    return None


def evaluer(
    event: LiquidityEvent,
    grille: GrillePonderation,
    *,
    aujourdhui: date,
) -> Evaluation:
    """Applique la grille. Pure et deterministe.

    `aujourdhui` est un parametre plutot qu'un `date.today()` interne : sans ca,
    la fonction ne serait ni testable ni reproductible.
    """
    refus = _motif_refus(event)
    if refus is not None:
        return Evaluation(event_id=event.id, classable=False, motif_refus=refus)

    contributions: list[ContributionCritere] = []

    # --- Montant
    valeur = normaliser_montant(event.montant_eur, grille.montant)
    contributions.append(
        ContributionCritere(
            critere="montant",
            poids=grille.montant.poids,
            valeur_normalisee=valeur,
            points=round((valeur or 0.0) * grille.montant.poids, 4),
            motif=(
                f"{event.montant_eur:,.0f} EUR, normalise en echelle log entre "
                f"{grille.montant.plancher_eur:,.0f} et {grille.montant.plafond_eur:,.0f} EUR"
            ),
        )
    )

    # --- Fraicheur : depuis l'ACTE si datable, sinon depuis la parution.
    if event.date_acte is not None:
        reference, origine = event.date_acte, "date d'acte"
    else:
        reference, origine = event.date_parution, "date de parution (acte non datable)"
    jours = (aujourdhui - reference).days
    valeur_fraicheur = normaliser_fraicheur(jours, grille.fraicheur)
    contributions.append(
        ContributionCritere(
            critere="fraicheur",
            poids=grille.fraicheur.poids,
            valeur_normalisee=valeur_fraicheur,
            points=round(valeur_fraicheur * grille.fraicheur.poids, 4),
            motif=(
                f"{jours} jours depuis la {origine} ; contribution pleine "
                f"jusqu'a {grille.fraicheur.fenetre_pleine_jours} jours, "
                f"nulle a partir de {grille.fraicheur.fenetre_nulle_jours}"
            ),
        )
    )

    # --- Secteur : declare mais indisponible avant la Phase 3.
    if event.code_ape is None:
        contributions.append(
            ContributionCritere(
                critere="secteur",
                poids=grille.secteur.poids,
                valeur_normalisee=None,
                points=0.0,
                motif=(
                    "code APE non disponible : BODACC n'en porte aucun, "
                    "l'enrichissement arrive en Phase 3. Contribution neutre."
                ),
            )
        )
    else:
        prioritaire = event.code_ape in grille.secteur.codes_prioritaires
        contributions.append(
            ContributionCritere(
                critere="secteur",
                poids=grille.secteur.poids,
                valeur_normalisee=1.0 if prioritaire else 0.0,
                points=round((1.0 if prioritaire else 0.0) * grille.secteur.poids, 4),
                motif=(
                    f"code APE {event.code_ape} "
                    f"{'dans' if prioritaire else 'hors'} la liste prioritaire"
                ),
            )
        )

    # --- Departement : poids nul par defaut, delibere.
    prioritaire_dep = event.departement in grille.departement.departements_prioritaires
    contributions.append(
        ContributionCritere(
            critere="departement",
            poids=grille.departement.poids,
            valeur_normalisee=1.0 if prioritaire_dep else 0.0,
            points=round((1.0 if prioritaire_dep else 0.0) * grille.departement.poids, 4),
            motif=(
                f"departement {event.departement} ; poids "
                f"{grille.departement.poids} — {grille.departement.motif.splitlines()[0]}"
            ),
        )
    )

    score = round(sum(c.points for c in contributions), 4)
    return Evaluation(
        event_id=event.id,
        classable=True,
        score=min(100.0, max(0.0, score)),
        contributions=contributions,
    )


# --- Controle de la grille ----------------------------------------------------


def rangs(valeurs: list[float]) -> list[float]:
    """Rangs 1..n, moyennes pour les ex-aequo."""
    ordonnes = sorted(range(len(valeurs)), key=lambda i: valeurs[i])
    resultat = [0.0] * len(valeurs)
    i = 0
    while i < len(ordonnes):
        j = i
        while j + 1 < len(ordonnes) and valeurs[ordonnes[j + 1]] == valeurs[ordonnes[i]]:
            j += 1
        rang_moyen = (i + j) / 2 + 1
        for k in range(i, j + 1):
            resultat[ordonnes[k]] = rang_moyen
        i = j + 1
    return resultat


def correlation_spearman(a: list[float], b: list[float]) -> float:
    """Correlation de rang, sans dependance externe.

    Sert a repondre a une question precise : le classement produit par la
    grille est-il autre chose qu'un tri par montant deguise ?
    """
    if len(a) != len(b):
        raise ValueError("les deux series doivent avoir la meme longueur")
    if len(a) < 2:
        raise ValueError("il faut au moins deux points")

    ra, rb = rangs(a), rangs(b)
    moyenne_a = sum(ra) / len(ra)
    moyenne_b = sum(rb) / len(rb)
    covariance = sum((x - moyenne_a) * (y - moyenne_b) for x, y in zip(ra, rb, strict=True))
    ecart_a = math.sqrt(sum((x - moyenne_a) ** 2 for x in ra))
    ecart_b = math.sqrt(sum((y - moyenne_b) ** 2 for y in rb))
    if ecart_a == 0 or ecart_b == 0:
        return 0.0
    return covariance / (ecart_a * ecart_b)
