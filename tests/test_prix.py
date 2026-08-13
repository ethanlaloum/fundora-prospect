"""Parsing et qualification du prix de cession.

Le parser repond a UNE question : « ce montant decrit-il bien la transaction
annoncee ? » C'est de la qualite de donnee. La pertinence commerciale — ce cash
est-il encore disponible — appartient au scoring (Phase 2). D'ou un seuil dur a
24 mois ici, et une fenetre de fraicheur de 18 mois la-bas : les deux ne
mesurent pas la meme chose.
"""

from __future__ import annotations

from datetime import date

import pytest

from fundora_prospect.prix import (
    SEUIL_ACTE_JOURS,
    Confiance,
    Qualification,
    extraire_date_acte,
    parser_prix,
)

# --- Cas nominaux : formes reellement observees dans le corpus ---------------


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("établissement principal acquis par achat au prix stipulé de 70000.00 euros", 70000.0),
        ("Etablissement principal acquis par achat au prix stipulé de 10000 EUR", 10000.0),
        ("acquis par achat au prix stipulé de 108398 Euros.", 108398.0),
        (
            "siège et établissement principal acquis par achat au prix stipulé de 150000.00 euros",
            150000.0,
        ),
        ("Fonds acquis par achat au prix stipulé de 46908.04 euros", 46908.04),
    ],
)
def test_achat_en_euros_est_retenu(texte: str, attendu: float) -> None:
    prix = parser_prix(texte)
    assert prix.qualification is Qualification.ACHAT
    assert prix.retenu
    assert prix.montant == pytest.approx(attendu)
    assert prix.devise == "EUR"


# --- Formats de nombre -------------------------------------------------------


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("70000.00", 70000.0),  # point decimal
        ("200000,00", 200000.0),  # virgule decimale
        ("52.485,00", 52485.0),  # point milliers + virgule decimale
        ("1 250 000,50", 1250000.50),  # espaces milliers
        ("10000", 10000.0),  # entier nu
        ("1452171", 1452171.0),
        ("3765000.00", 3765000.0),
    ],
)
def test_formats_de_nombre(brut: str, attendu: float) -> None:
    prix = parser_prix(f"acquis par achat au prix stipulé de {brut} euros")
    assert prix.montant == pytest.approx(attendu)


def test_point_suivi_de_trois_chiffres_est_un_separateur_de_milliers() -> None:
    """`52.485` vaut 52 485, pas 52,485. Le corpus ecrit les decimales sur
    deux chiffres ; trois chiffres apres un point sont des milliers."""
    assert parser_prix("achat au prix stipulé de 52.485 euros").montant == pytest.approx(52485.0)


# --- Regle metier : un apport n'est pas une cession (contrainte 6) -----------


@pytest.mark.parametrize(
    "texte",
    [
        "acquis par apport au montant évalué à 1452171 Francs.",
        "Apport en société au montant évalué à 303281,74 FRANCS FRANCAIS.",
        "établissement principal acquis par apport au montant évalué à 250000.00 euros",
    ],
)
def test_apport_est_rejete_avec_motif(texte: str) -> None:
    """Le cedant recoit des parts, pas du cash : aucune liquidite a placer."""
    prix = parser_prix(texte)
    assert prix.qualification is Qualification.APPORT
    assert not prix.retenu


def test_apport_n_est_jamais_score_a_zero() -> None:
    """Un zero se noierait dans le flux ; un rejet motive est auditable."""
    prix = parser_prix("acquis par apport au montant évalué à 250000.00 euros")
    assert prix.montant != 0
    assert prix.qualification is Qualification.APPORT


def test_apport_prime_sur_la_devise_obsolete() -> None:
    """Un apport en francs est d'abord un apport : la regle metier prime sur
    le defaut de qualite de donnee."""
    prix = parser_prix("acquis par apport au montant évalué à 1452171 Francs.")
    assert prix.qualification is Qualification.APPORT


# --- Devise obsolete ---------------------------------------------------------


@pytest.mark.parametrize(
    "texte",
    [
        "Etablissement secondaire acquis par achat au prix stipulé de 300000 Francs.",
        "Fonds acquis par achat au prix stipulé de 52.485,00 FRF",
        "Achat au prix stipulé de 200000,00 FRANCS FRANCAIS.",
    ],
)
def test_montant_en_francs_est_rejete(texte: str) -> None:
    """Le franc a disparu en 2002 : un tel montant ne peut pas decrire la
    cession publiee, il decrit une transaction anterieure."""
    prix = parser_prix(texte)
    assert prix.qualification is Qualification.DEVISE_OBSOLETE
    assert not prix.retenu
    assert prix.devise == "FRF"


def test_le_montant_en_francs_reste_lisible_pour_l_audit() -> None:
    prix = parser_prix("acquis par achat au prix stipulé de 300000 Francs.")
    assert prix.montant == pytest.approx(300000.0)
    assert not prix.retenu


# --- Absence de prix ---------------------------------------------------------


@pytest.mark.parametrize("texte", ["Reprise d'activité", "", "   ", "Création"])
def test_prix_absent_donne_none_jamais_zero(texte: str) -> None:
    """L'absence de prix n'est pas la gratuite. Un zero fausserait le scoring."""
    prix = parser_prix(texte)
    assert prix.qualification is Qualification.ABSENT
    assert prix.montant is None
    assert not prix.retenu


# --- Garde de fraicheur de l'acte -------------------------------------------


def test_acte_plus_vieux_que_le_seuil_est_rejete() -> None:
    prix = parser_prix(
        "acquis par achat au prix stipulé de 200000.00 euros",
        date_acte=date(2020, 1, 1),
        date_parution=date(2026, 1, 1),
    )
    assert prix.qualification is Qualification.ACTE_TROP_ANCIEN
    assert not prix.retenu


def test_acte_de_vingt_mois_reste_une_donnee_valide() -> None:
    """20 mois : vieux mais valide. C'est au scoring de le declasser, pas au
    parser de le supprimer — sinon elargir la fenetre metier obligerait a
    modifier prix.py."""
    prix = parser_prix(
        "acquis par achat au prix stipulé de 200000.00 euros",
        date_acte=date(2024, 5, 1),
        date_parution=date(2026, 1, 1),
    )
    assert prix.qualification is Qualification.ACHAT
    assert prix.retenu
    assert prix.ecart_acte_jours is not None
    assert prix.ecart_acte_jours > 540


def test_le_seuil_est_bien_de_vingt_quatre_mois() -> None:
    assert SEUIL_ACTE_JOURS == 730


def test_acte_non_datable_est_retenu_mais_signale() -> None:
    """60 % des annonces n'ont pas de date d'acte lisible : les rejeter
    supprimerait la majorite du flux. On retient en marquant l'incertitude."""
    prix = parser_prix(
        "acquis par achat au prix stipulé de 200000.00 euros",
        date_acte=None,
        date_parution=date(2026, 1, 1),
    )
    assert prix.qualification is Qualification.ACHAT
    assert prix.confiance is Confiance.ACTE_INDATABLE
    assert prix.ecart_acte_jours is None


def test_acte_date_porte_l_ecart() -> None:
    prix = parser_prix(
        "acquis par achat au prix stipulé de 200000.00 euros",
        date_acte=date(2025, 12, 1),
        date_parution=date(2026, 1, 1),
    )
    assert prix.confiance is Confiance.ACTE_DATE
    assert prix.ecart_acte_jours == 31


# --- Extraction de la date d'acte -------------------------------------------


@pytest.mark.parametrize(
    ("descriptif", "attendu"),
    [
        ("Acte en date du 29/06/2026.", date(2026, 6, 29)),
        ("Acte en date du 29/06/2026 enregistre le 17/07/2026.", date(2026, 6, 29)),
        ("Reprise", None),
        ("", None),
        ("Acte en date du 32/13/2026.", None),  # date impossible
    ],
)
def test_extraire_date_acte(descriptif: str, attendu: date | None) -> None:
    assert extraire_date_acte(descriptif) == attendu


# --- Montants aberrants ------------------------------------------------------


@pytest.mark.parametrize("montant", ["1", "100", "999"])
def test_montant_symbolique_est_marque_mais_conserve(montant: str) -> None:
    prix = parser_prix(f"acquis par achat au prix stipulé de {montant} euros")
    assert prix.aberrant
    assert prix.qualification is Qualification.ACHAT, "le plafonnement appartient au scoring"


def test_montant_demesure_est_marque() -> None:
    prix = parser_prix("acquis par achat au prix stipulé de 99000000000 euros")
    assert prix.aberrant


def test_montant_plausible_n_est_pas_marque() -> None:
    assert not parser_prix("acquis par achat au prix stipulé de 110000.00 euros").aberrant


# --- Tracabilite du calcul (contrainte 5) ------------------------------------


def test_le_texte_source_et_la_methode_sont_conserves() -> None:
    """Le breakdown de la Phase 2 doit pouvoir montrer d'ou vient chaque euro."""
    texte = "établissement principal acquis par achat au prix stipulé de 70000.00 euros"
    prix = parser_prix(texte)
    assert prix.texte_source == texte
    assert prix.methode
