"""Grille de ponderation — A DIRE D'EXPERT.

**Ce n'est pas un modele.** Les poids sont des hypotheses commerciales, pas des
coefficients appris : aucune donnee de conversion n'existe pour les calibrer, on
ne sait pas quels leads se transforment. Le vocabulaire du module le dit —
`GrillePonderation`, `evaluer`, `Contribution`. Pas de `model`, pas de
`predict`, pas de `train`. Presenter cette grille comme un modele laisserait
croire a une validation empirique qui n'a pas eu lieu, et c'est indefendable
devant un CIF.

Les poids vivent dans `src/fundora_prospect/config/ponderation.toml`, charge au runtime. Recalibrer
la grille ne doit toucher aucun fichier `.py`.

La fonction `evaluer` est pure et deterministe : meme entree, meme sortie. La
date du jour est un parametre, pas un appel a `date.today()`.
"""

from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass
from datetime import date
from importlib import resources
from pathlib import Path

from fundora_prospect.models import (
    ContributionCritere,
    Evaluation,
    LiquidityEvent,
    StatutEntreprise,
)

VARIABLE_PONDERATION = "FUNDORA_PONDERATION"


def chemin_ponderation() -> Path:
    """Localise `ponderation.toml`, dans cet ordre de precedence.

    1. La variable d'environnement `FUNDORA_PONDERATION`, qui permet de pointer
       une grille recalibree sans toucher au depot.
    2. La donnee de paquet, `src/fundora_prospect/config/ponderation.toml`,
       qui voyage avec le module quel que soit le mode d'installation.

    Un simple `Path(__file__).parents[2]` ne couvrait que l'execution depuis le
    depot et levait un `FileNotFoundError` sur une installation normale — le
    cas du serveur MCP, lance en stdio depuis un repertoire arbitraire.
    """
    force = os.environ.get(VARIABLE_PONDERATION)
    if force:
        chemin = Path(force).expanduser()
        if not chemin.is_file():
            raise FileNotFoundError(
                f"{VARIABLE_PONDERATION}={force!r} ne designe aucun fichier lisible"
            )
        return chemin

    try:
        ressource = resources.files("fundora_prospect") / "config" / "ponderation.toml"
        if ressource.is_file():
            return Path(str(ressource))
    except (ModuleNotFoundError, TypeError, OSError):  # pragma: no cover
        pass

    voisin = Path(__file__).resolve().parent / "config" / "ponderation.toml"
    if voisin.is_file():
        return voisin

    raise FileNotFoundError(
        f"ponderation.toml introuvable : ni via {VARIABLE_PONDERATION}, ni dans le paquet"
    )


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
    forme: str
    demi_vie_jours: int
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
                forme=charge["fraicheur"]["forme"],
                demi_vie_jours=charge["fraicheur"]["demi_vie_jours"],
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
        return cls.depuis_toml(chemin_ponderation())


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
    """Decroit DES LE PREMIER JOUR, sans plateau.

    Le delai est le critere le plus decisif du metier : une cession de trois
    semaines et une de onze mois ne sont pas le meme prospect. Dans le premier
    cas le produit est encore en tresorerie et la decision de placement n'est
    pas prise, dans le second l'argent a deja trouve une destination.

    Un plateau ferait de la fraicheur une fenetre de pertinence commerciale la
    ou il faut un critere de discrimination — c'est ce qui rendait le
    classement equivalent a un tri par montant.

    La forme vient de la configuration. La demi-vie modelise mieux le
    phenomene : la probabilite que le cash soit encore disponible decroit
    continument, sans date de bascule.
    """
    if jours <= 0:
        return 1.0
    if critere.forme == "lineaire":
        return max(0.0, 1.0 - jours / critere.fenetre_nulle_jours)
    if critere.forme == "demi_vie":
        return 0.5 ** (jours / critere.demi_vie_jours)
    raise ValueError(
        f"forme de decroissance inconnue : {critere.forme!r} (attendu 'demi_vie' ou 'lineaire')"
    )


# --- Evaluation ---------------------------------------------------------------


def _motif_refus(event: LiquidityEvent) -> str | None:
    """Un evenement peut sortir du classement, jamais y entrer avec un zero."""
    # Le statut de la societe cedante est une PORTE, pas un poids. Une societe
    # radiee n'est pas « un peu moins bonne » : la personne morale n'existe
    # plus, elle ne peut pas etre prospectee, et nous avons decide de ne pas
    # poursuivre les associes. C'est binaire, donc une porte — un poids
    # laisserait entendre une gradation qui n'existe pas.
    #
    # Le statut INCONNU ne ferme rien : l'API peut etre muette, et un lead sans
    # enrichissement reste un lead valide.
    if event.statut_cedant is StatutEntreprise.CESSEE:
        return (
            "societe cedante cessee : le produit de cession est descendu aux "
            "associes, la personne morale n'est plus prospectable"
        )
    if event.statut_cedant is StatutEntreprise.NON_DIFFUSIBLE:
        return "entreprise non diffusible : opposition INSEE explicite, non exploitee"
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
                f"{jours} jours depuis la {origine} ; decroissance "
                f"{grille.fraicheur.forme} des le premier jour"
                + (
                    f", demi-vie {grille.fraicheur.demi_vie_jours} jours"
                    if grille.fraicheur.forme == "demi_vie"
                    else f", nulle a {grille.fraicheur.fenetre_nulle_jours} jours"
                )
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
                    "code APE non disponible (enrichissement absent ou muet) ; "
                    f"critere a poids {grille.secteur.poids}, contribution neutre"
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
            # Le motif de configuration sort ENTIER. Il portait auparavant
            # `.splitlines()[0]`, c'est-a-dire la premiere ligne PHYSIQUE du bloc
            # TOML — un retour a la ligne de mise en page. Le motif s'arretait
            # donc au milieu d'une phrase (« rien ne justifie de »), ce qui viole
            # la contrainte 5 : un motif coupe n'explique rien, et c'est
            # justement le « pourquoi zero » qu'on veut lire.
            #
            # Si un affichage a besoin d'une version courte, ce sera un second
            # champ nomme, jamais un decoupage silencieux d'un texte existant.
            motif=(
                f"departement {event.departement} ; poids "
                f"{grille.departement.poids} — {grille.departement.motif}"
            ),
        )
    )

    score = round(sum(c.points for c in contributions), 4)
    return Evaluation(
        event_id=event.id,
        classable=True,
        score=min(100.0, max(0.0, score)),
        contributions=contributions,
        # Les memes `jours` et la meme `reference` que le motif de la fraicheur
        # ci-dessus : un seul calcul, deux presentations.
        jours_ecoules=jours,
        date_reference=reference,
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
