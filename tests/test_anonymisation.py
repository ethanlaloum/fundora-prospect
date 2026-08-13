"""Contrainte 4 : les fixtures ne contiennent aucune donnee personnelle reelle.

**Ce test est une LISTE BLANCHE.** Il ne cherche pas des noms connus — une
liste noire laisserait passer tous ceux qu'on n'a pas anticipes, et c'est
precisement ceux-la qui posent probleme. Il verifie que chaque chaine des
fixtures appartient a un ensemble declare dans `tools.vocabulaire` : gabarit
ancre pour les champs a texte libre, valeur du vocabulaire pour les champs
structures, lexique mot a mot pour `origineFonds`.

Tout ce qui n'est pas reconnu fait echouer. Une evolution du schema BODACC qui
introduirait un nouveau champ texte est signalee ici, pas decouverte en
production.

Ce test est lance par `.githooks/pre-commit` : git conserve l'historique, un
nom commite une fois reste expose le jour ou le depot passe en public.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.vocabulaire import (
    CHEMINS_TEXTE_AUTORISES,
    FEUILLES_PERSONNE_AUTORISEES,
    GABARITS,
    PREFIXES_PERSONNE,
    VALEURS_AUTORISEES,
    mots_inconnus,
)

FIXTURES = Path(__file__).parent / "fixtures"


def deplier(valeur: Any) -> Any:
    """Les sous-objets BODACC sont des JSON encodes en string."""
    if isinstance(valeur, str) and valeur.strip()[:1] in "{[":
        try:
            return json.loads(valeur)
        except json.JSONDecodeError:
            return valeur
    return valeur


def parcourir(noeud: Any, prefixe: str = "") -> list[tuple[str, str]]:
    """Toutes les chaines de l'annonce, avec leur chemin, sous-objets deplies."""
    noeud = deplier(noeud)
    if isinstance(noeud, dict):
        return [
            couple
            for cle, valeur in noeud.items()
            for couple in parcourir(valeur, f"{prefixe}.{cle}" if prefixe else cle)
        ]
    if isinstance(noeud, list):
        return [couple for element in noeud for couple in parcourir(element, f"{prefixe}[]")]
    if isinstance(noeud, str) and noeud.strip():
        return [(prefixe, noeud)]
    return []


def normaliser(chemin: str) -> str:
    return chemin.replace("[]", "")


def chemin_autorise(chemin: str) -> bool:
    if chemin in {normaliser(c) for c in CHEMINS_TEXTE_AUTORISES}:
        return True
    for prefixe in PREFIXES_PERSONNE:
        if chemin.startswith(prefixe + "."):
            return chemin[len(prefixe) + 1 :] in FEUILLES_PERSONNE_AUTORISEES
    return False


def charger_fixtures() -> list[tuple[str, dict[str, Any]]]:
    annonces: list[tuple[str, dict[str, Any]]] = []
    for fichier in sorted(FIXTURES.glob("*.json")):
        charge = json.loads(fichier.read_text(encoding="utf-8"))
        for i, annonce in enumerate(charge if isinstance(charge, list) else [charge]):
            annonces.append((f"{fichier.name}[{i}]", annonce))
    return annonces


def test_des_fixtures_existent() -> None:
    """Garde-fou : sans ce test, tous les suivants passeraient a vide."""
    assert charger_fixtures(), "aucune fixture — les tests d'anonymisation seraient vacuous"


def _identifiants() -> list[str]:
    return [nom for nom, _ in charger_fixtures()]


@pytest.mark.parametrize("nom_fixture", _identifiants())
def test_aucun_chemin_texte_non_declare(nom_fixture: str) -> None:
    """Un champ texte inconnu peut porter des donnees personnelles : on refuse."""
    annonce = dict(charger_fixtures())[nom_fixture]
    inconnus = {
        normaliser(chemin)
        for chemin, _ in parcourir(annonce)
        if not chemin_autorise(normaliser(chemin))
    }
    assert not inconnus, f"chemins texte non declares dans {nom_fixture} : {sorted(inconnus)}"


@pytest.mark.parametrize("nom_fixture", _identifiants())
def test_champs_texte_libre_conformes_au_gabarit(nom_fixture: str) -> None:
    """Les quatre champs qui portent des noms doivent etre reconstruits."""
    annonce = dict(charger_fixtures())[nom_fixture]
    for chemin, valeur in parcourir(annonce):
        gabarit = GABARITS.get(normaliser(chemin))
        if gabarit is None:
            continue
        assert gabarit.match(valeur), (
            f"{nom_fixture} :: {chemin} ne correspond pas au gabarit synthetique.\n"
            f"  valeur  : {valeur!r}\n  gabarit : {gabarit.pattern}"
        )


@pytest.mark.parametrize("nom_fixture", _identifiants())
def test_champs_structures_sensibles_issus_du_vocabulaire(nom_fixture: str) -> None:
    """nom, prenom, adresses : uniquement des valeurs declarees."""
    annonce = dict(charger_fixtures())[nom_fixture]
    for chemin, valeur in parcourir(annonce):
        feuille = normaliser(chemin).rsplit(".", 1)[-1]
        autorisees = VALEURS_AUTORISEES.get(feuille)
        if autorisees is None:
            continue
        assert valeur in autorisees, (
            f"{nom_fixture} :: {chemin} = {valeur!r} hors vocabulaire synthetique "
            f"(attendu parmi {autorisees})"
        )


@pytest.mark.parametrize("nom_fixture", _identifiants())
def test_origine_fonds_ne_contient_que_du_lexique(nom_fixture: str) -> None:
    """`origineFonds` est conserve reel — c'est la matiere du parser — mais
    valide mot a mot : un nom propre serait un mot inconnu."""
    annonce = dict(charger_fixtures())[nom_fixture]
    for chemin, valeur in parcourir(annonce):
        if not normaliser(chemin).endswith("origineFonds"):
            continue
        inconnus = mots_inconnus(valeur)
        assert not inconnus, (
            f"{nom_fixture} :: mots hors lexique dans origineFonds : {inconnus}\n"
            f"  texte : {valeur!r}"
        )
