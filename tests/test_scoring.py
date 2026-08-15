"""Grille de ponderation — a dire d'expert, pas un modele.

Les poids sont des hypotheses commerciales sans donnee de conversion pour les
calibrer. Ces tests ne valident donc pas une justesse predictive, qui n'a aucun
sens ici : ils verifient que la grille se comporte comme sa specification le
dit, qu'elle est deterministe, et qu'elle explique chacun de ses points.
"""

from __future__ import annotations

from datetime import date

import pytest

from fundora_prospect.models import Evaluation, LiquidityEvent, TypeCedant
from fundora_prospect.scoring import (
    GrillePonderation,
    correlation_spearman,
    evaluer,
    normaliser_fraicheur,
    normaliser_montant,
    rangs,
)

AUJOURDHUI = date(2026, 8, 15)


@pytest.fixture(scope="module")
def grille() -> GrillePonderation:
    return GrillePonderation.defaut()


def evenement(
    montant: float | None = 250_000.0,
    *,
    date_acte: date | None = date(2026, 6, 1),
    retenu: bool = True,
    aberrant: bool = False,
    code_ape: str | None = None,
    identifiant: str = "A2026000001",
) -> LiquidityEvent:
    return LiquidityEvent(
        id=identifiant,
        date_parution=date(2026, 6, 20),
        date_acte=date_acte,
        departement="13",
        url_publication="https://www.bodacc.fr/pages/annonces-commerciales-detail/?q.id=id:X",
        montant_eur=montant,
        devise="EUR" if montant else None,
        qualification="achat" if retenu else "apport",
        retenu=retenu,
        aberrant=aberrant,
        code_ape=code_ape,
        cedant_denomination="SOCIETE TEST",
        cedant_type=TypeCedant.PERSONNE_MORALE,
        cedant_siren="325662559",
    )


# --- Montant : echelle logarithmique ----------------------------------------


def test_montant_est_monotone_croissant(grille: GrillePonderation) -> None:
    valeurs = [normaliser_montant(m, grille.montant) for m in (20_000, 100_000, 500_000)]
    assert valeurs == sorted(valeurs)
    assert len(set(valeurs)) == 3


def test_le_log_rend_lisible_la_bande_ou_vit_le_volume(grille: GrillePonderation) -> None:
    """200 -> 400 k EUR doit peser plus que 1,2 -> 1,4 M EUR.

    C'est le sens metier : passer de 200 a 400 k change la capacite
    d'investissement, passer de 1,2 a 1,4 M non. Une echelle lineaire donnerait
    exactement le meme ecart aux deux.
    """
    bas = normaliser_montant(400_000, grille.montant) - normaliser_montant(200_000, grille.montant)
    haut = normaliser_montant(1_400_000, grille.montant) - normaliser_montant(
        1_200_000, grille.montant
    )
    assert bas > haut * 2


def test_montant_sous_le_plancher_ne_contribue_pas(grille: GrillePonderation) -> None:
    assert normaliser_montant(5_000, grille.montant) == 0.0
    assert normaliser_montant(grille.montant.plancher_eur, grille.montant) == 0.0


def test_le_plafond_borne_sans_saturer_le_metier(grille: GrillePonderation) -> None:
    """Le plafond est place au p99 : il borne une valeur mal parsee, il ne
    modelise pas une saturation de la capacite d'investissement."""
    assert normaliser_montant(grille.montant.plafond_eur, grille.montant) == pytest.approx(1.0)
    assert normaliser_montant(6_200_000, grille.montant) == pytest.approx(1.0)
    assert grille.montant.plafond_eur >= 1_000_000


def test_montant_absent_donne_none(grille: GrillePonderation) -> None:
    assert normaliser_montant(None, grille.montant) is None


# --- Fraicheur ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("jours", "attendu"),
    [
        (0, 1.0),
        (-10, 1.0),  # date future : borne, pas d'erreur
    ],
)
def test_fraicheur_bornes_hautes(grille: GrillePonderation, jours: int, attendu: float) -> None:
    assert normaliser_fraicheur(jours, grille.fraicheur) == pytest.approx(attendu)


def test_la_demi_vie_divise_par_deux_a_chaque_periode(grille: GrillePonderation) -> None:
    demi_vie = grille.fraicheur.demi_vie_jours
    assert normaliser_fraicheur(demi_vie, grille.fraicheur) == pytest.approx(0.5)
    assert normaliser_fraicheur(2 * demi_vie, grille.fraicheur) == pytest.approx(0.25)


def test_la_fraicheur_decroit_DES_LE_PREMIER_JOUR(grille: GrillePonderation) -> None:
    """Correction de la Phase 2 : la version initiale accordait une
    contribution pleine jusqu'a 18 mois. C'etait une fenetre de pertinence
    commerciale la ou il faut un critere de discrimination — toute la
    population d'une recherche sur 12 mois tombait dans le plateau.

    Sens metier : une cession de 3 semaines et une de 11 mois ne sont pas le
    meme prospect. Dans le premier cas le produit est encore en tresorerie et
    la decision de placement n'est pas prise ; dans le second l'argent a deja
    trouve une destination.
    """
    trois_semaines = normaliser_fraicheur(21, grille.fraicheur)
    onze_mois = normaliser_fraicheur(335, grille.fraicheur)
    assert trois_semaines > onze_mois
    assert trois_semaines - onze_mois > 0.3, "la decroissance doit etre franche sur 12 mois"


def test_la_fraicheur_est_strictement_decroissante(grille: GrillePonderation) -> None:
    valeurs = [normaliser_fraicheur(j, grille.fraicheur) for j in (1, 30, 90, 180, 365, 548)]
    assert valeurs == sorted(valeurs, reverse=True)
    assert len(set(valeurs)) == len(valeurs), "aucun palier : chaque delai a sa valeur"


def test_la_forme_de_decroissance_est_configurable(grille: GrillePonderation) -> None:
    """Lineaire ou demi-vie : la forme vient du fichier, pas du code."""
    from dataclasses import replace

    lineaire = replace(grille.fraicheur, forme="lineaire")
    assert normaliser_fraicheur(548, lineaire) == pytest.approx(1 - 548 / 1096, abs=0.01)
    assert normaliser_fraicheur(1096, lineaire) == pytest.approx(0.0)
    assert normaliser_fraicheur(2000, lineaire) == 0.0


def test_forme_inconnue_leve(grille: GrillePonderation) -> None:
    from dataclasses import replace

    with pytest.raises(ValueError, match="forme de decroissance inconnue"):
        normaliser_fraicheur(100, replace(grille.fraicheur, forme="exponentielle_inversee"))


def test_la_fraicheur_part_de_l_acte_quand_il_est_datable(grille: GrillePonderation) -> None:
    """L'ecart median acte -> parution est de 33 jours mais p95 atteint 145 :
    compter depuis la parution surestimerait systematiquement la fraicheur."""
    depuis_acte = evaluer(evenement(date_acte=date(2025, 1, 1)), grille, aujourdhui=AUJOURDHUI)
    depuis_parution = evaluer(evenement(date_acte=None), grille, aujourdhui=AUJOURDHUI)
    assert depuis_acte.score is not None and depuis_parution.score is not None
    assert depuis_acte.score < depuis_parution.score


def test_le_breakdown_dit_quelle_date_a_servi(grille: GrillePonderation) -> None:
    sans_acte = evaluer(evenement(date_acte=None), grille, aujourdhui=AUJOURDHUI)
    contribution = next(c for c in sans_acte.contributions if c.critere == "fraicheur")
    assert "parution" in contribution.motif.lower()


# --- Secteur : declare mais indisponible avant la Phase 3 -------------------


def test_secteur_sans_ape_est_neutre_et_le_dit(grille: GrillePonderation) -> None:
    """Un critere silencieusement absent est un trou dans l'explicabilite."""
    evaluation = evaluer(evenement(code_ape=None), grille, aujourdhui=AUJOURDHUI)
    contribution = next(c for c in evaluation.contributions if c.critere == "secteur")
    assert contribution.valeur_normalisee is None
    assert contribution.points == 0.0
    assert "ape" in contribution.motif.lower()


# --- Departement : poids nul delibere ---------------------------------------


def test_departement_a_poids_nul_par_defaut(grille: GrillePonderation) -> None:
    """Rien ne justifie de hierarchiser les six departements de PACA."""
    assert grille.departement.poids == 0
    evaluation = evaluer(evenement(), grille, aujourdhui=AUJOURDHUI)
    contribution = next(c for c in evaluation.contributions if c.critere == "departement")
    assert contribution.points == 0.0
    assert contribution.motif


# --- Refus de classement -----------------------------------------------------


def test_evenement_non_retenu_n_est_pas_score(grille: GrillePonderation) -> None:
    """Un zero se noierait dans le classement ; un refus motive est auditable."""
    evaluation = evaluer(evenement(retenu=False), grille, aujourdhui=AUJOURDHUI)
    assert not evaluation.classable
    assert evaluation.score is None
    assert evaluation.motif_refus


def test_montant_aberrant_est_hors_classement_pas_plafonne(
    grille: GrillePonderation,
) -> None:
    """Une donnee dont on ignore si elle est juste ne doit pas atterrir en tete
    du classement. Meme regle que les non-retenus."""
    evaluation = evaluer(
        evenement(montant=99_000_000, aberrant=True), grille, aujourdhui=AUJOURDHUI
    )
    assert not evaluation.classable
    assert evaluation.score is None
    assert "aberrant" in (evaluation.motif_refus or "").lower()


def test_montant_absent_est_hors_classement(grille: GrillePonderation) -> None:
    evaluation = evaluer(evenement(montant=None), grille, aujourdhui=AUJOURDHUI)
    assert not evaluation.classable


# --- Proprietes du score -----------------------------------------------------


@pytest.mark.parametrize("montant", [10_001, 200_000, 1_000_000, 6_200_000])
def test_score_borne_entre_0_et_100(grille: GrillePonderation, montant: float) -> None:
    evaluation = evaluer(evenement(montant), grille, aujourdhui=AUJOURDHUI)
    assert evaluation.score is not None
    assert 0.0 <= evaluation.score <= 100.0


def test_le_score_est_la_somme_exacte_des_contributions(grille: GrillePonderation) -> None:
    """Contrainte 5 : pas de boite noire. Le detail doit reconstituer le total."""
    evaluation = evaluer(evenement(), grille, aujourdhui=AUJOURDHUI)
    assert evaluation.score is not None
    assert sum(c.points for c in evaluation.contributions) == pytest.approx(evaluation.score)


def test_chaque_contribution_porte_un_motif(grille: GrillePonderation) -> None:
    evaluation = evaluer(evenement(), grille, aujourdhui=AUJOURDHUI)
    assert len(evaluation.contributions) == 4
    for contribution in evaluation.contributions:
        assert contribution.motif.strip(), f"{contribution.critere} sans motif"


def test_la_grille_est_deterministe(grille: GrillePonderation) -> None:
    premiere = evaluer(evenement(), grille, aujourdhui=AUJOURDHUI)
    seconde = evaluer(evenement(), grille, aujourdhui=AUJOURDHUI)
    assert premiere.model_dump() == seconde.model_dump()


def test_la_grille_est_pure(grille: GrillePonderation) -> None:
    """Aucun effet de bord : l'evenement d'entree n'est pas modifie."""
    event = evenement()
    avant = event.model_dump()
    evaluer(event, grille, aujourdhui=AUJOURDHUI)
    assert event.model_dump() == avant


# --- Correlation de rang -----------------------------------------------------


def test_rangs_gere_les_ex_aequo() -> None:
    assert rangs([10, 20, 30]) == [1.0, 2.0, 3.0]
    assert rangs([10, 10, 30]) == [1.5, 1.5, 3.0]


@pytest.mark.parametrize(
    ("a", "b", "attendu"),
    [
        ([1, 2, 3, 4], [1, 2, 3, 4], 1.0),
        ([1, 2, 3, 4], [4, 3, 2, 1], -1.0),
        ([1, 2, 3, 4], [10, 20, 30, 40], 1.0),
    ],
)
def test_correlation_spearman(a: list[float], b: list[float], attendu: float) -> None:
    assert correlation_spearman(a, b) == pytest.approx(attendu)


def test_spearman_refuse_des_series_de_tailles_differentes() -> None:
    with pytest.raises(ValueError):
        correlation_spearman([1, 2], [1, 2, 3])


def test_les_autres_criteres_departagent_a_montant_egal(grille: GrillePonderation) -> None:
    """LA garantie qui compte. Si deux evenements de meme montant obtiennent le
    meme score, les autres criteres sont du code mort — quelle que soit la
    correlation d'ensemble avec le montant."""
    recent = evaluer(
        evenement(300_000, date_acte=date(2026, 6, 1), identifiant="recent"),
        grille,
        aujourdhui=AUJOURDHUI,
    )
    ancien = evaluer(
        evenement(300_000, date_acte=date(2024, 6, 1), identifiant="ancien"),
        grille,
        aujourdhui=AUJOURDHUI,
    )
    assert recent.score is not None and ancien.score is not None
    ecart = recent.score - ancien.score
    assert ecart >= grille.controle.ecart_minimal_a_montant_egal, (
        f"ecart de seulement {ecart:.2f} point(s) a montant egal : "
        "les criteres autres que le montant ne discriminent pas"
    )


def test_deux_cessions_recentes_de_meme_montant_sont_departagees(
    grille: GrillePonderation,
) -> None:
    """Le cas qui echouait avec le plateau : 3 mois contre 15 mois, meme
    montant. Les deux tombaient dans la fenetre pleine et obtenaient le meme
    score. C'est le coeur de la correction."""
    trois_mois = evaluer(
        evenement(300_000, date_acte=date(2026, 5, 15), identifiant="recent"),
        grille,
        aujourdhui=AUJOURDHUI,
    )
    quinze_mois = evaluer(
        evenement(300_000, date_acte=date(2025, 5, 15), identifiant="moins-recent"),
        grille,
        aujourdhui=AUJOURDHUI,
    )
    assert trois_mois.score is not None and quinze_mois.score is not None
    assert trois_mois.score > quinze_mois.score
    assert trois_mois.score - quinze_mois.score > 10.0


def test_la_fraicheur_peut_renverser_un_ecart_de_montant(
    grille: GrillePonderation,
) -> None:
    """Preuve que la grille n'est plus un tri par montant : un montant plus
    faible mais tres frais doit pouvoir passer devant un montant plus eleve
    mais ancien."""
    modeste_et_frais = evaluer(
        evenement(250_000, date_acte=date(2026, 8, 1), identifiant="frais"),
        grille,
        aujourdhui=AUJOURDHUI,
    )
    eleve_et_ancien = evaluer(
        evenement(600_000, date_acte=date(2024, 10, 1), identifiant="ancien"),
        grille,
        aujourdhui=AUJOURDHUI,
    )
    assert modeste_et_frais.score is not None and eleve_et_ancien.score is not None
    assert modeste_et_frais.score > eleve_et_ancien.score


# --- Configuration -----------------------------------------------------------


def test_les_poids_somment_a_cent(grille: GrillePonderation) -> None:
    total = (
        grille.montant.poids
        + grille.fraicheur.poids
        + grille.secteur.poids
        + grille.departement.poids
    )
    assert total == 100


def test_les_bornes_de_la_config_sont_coherentes(grille: GrillePonderation) -> None:
    assert grille.montant.plancher_eur < grille.montant.plafond_eur
    assert grille.fraicheur.forme in {"demi_vie", "lineaire"}
    assert grille.fraicheur.demi_vie_jours > 0
    assert grille.fraicheur.fenetre_nulle_jours > 0


def test_la_grille_se_declare_non_calibree(grille: GrillePonderation) -> None:
    """Elle doit dire ce qu'elle est : a dire d'expert, sans validation."""
    assert "expert" in grille.methode.lower()


def test_chaque_critere_porte_son_motif_de_ponderation(grille: GrillePonderation) -> None:
    for critere in (grille.montant, grille.fraicheur, grille.secteur, grille.departement):
        assert critere.motif.strip()


def test_les_poids_sont_rechargeables_sans_toucher_au_code(
    tmp_path, grille: GrillePonderation
) -> None:
    """Recalibrer ne doit modifier aucun .py."""
    variante = tmp_path / "ponderation.toml"
    source = GrillePonderation.CHEMIN_DEFAUT.read_text(encoding="utf-8")
    variante.write_text(
        source.replace("poids = 55", "poids = 40").replace("poids = 35", "poids = 50"),
        encoding="utf-8",
    )

    rechargee = GrillePonderation.depuis_toml(variante)
    assert rechargee.montant.poids == 40
    assert rechargee.fraicheur.poids == 50
    assert grille.montant.poids == 55, "la grille par defaut ne doit pas etre affectee"


# --- Construction depuis une annonce ----------------------------------------


def test_liquidity_event_se_construit_depuis_une_annonce() -> None:
    import json
    from pathlib import Path

    from fundora_prospect.bodacc import construire_annonce

    fixtures = Path(__file__).parent / "fixtures" / "achat_cedant_pm.json"
    annonce = construire_annonce(json.loads(fixtures.read_text(encoding="utf-8"))[0])
    assert annonce is not None

    event = LiquidityEvent.depuis_annonce(annonce)
    assert event.id == annonce.id
    assert event.montant_eur == annonce.prix.montant
    assert event.retenu == annonce.prix.retenu
    assert event.url_publication == annonce.url_publication
    assert isinstance(event, LiquidityEvent)


def test_evaluation_est_serialisable(grille: GrillePonderation) -> None:
    evaluation = evaluer(evenement(), grille, aujourdhui=AUJOURDHUI)
    assert isinstance(evaluation, Evaluation)
    charge = evaluation.model_dump_json()
    assert "contributions" in charge
