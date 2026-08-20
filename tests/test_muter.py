"""L'outil de mutation a-t-il des dents ?

Meme structure que `tests/test_symboles_morts.py`, et pour la meme raison : un
outil de verification qui rendrait toujours « tout va bien » passerait
inapercu, puisque c'est exactement ce qu'on espere lire.

Ici la propriete centrale n'est pas « la mutation est detectee » — c'est **la
distinction entre une mutation non appliquee et une mutation non detectee**.
Les deux produisaient la meme sortie, et c'est ce qui a laisse croire a une
mesure qui n'avait pas eu lieu.

`lancer` est substitue par un faux : la suite ne peut pas se relancer depuis
l'interieur d'elle-meme, et ce n'est de toute facon pas `pytest` qu'on teste.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.muter import (
    DETECTEE,
    NON_APPLIQUEE,
    SURVIVANTE,
    Mutation,
    MutationNonAppliquee,
    appliquer,
    jouer,
)


def depot(base: Path, contenu: str = "valeur = 1\n") -> Path:
    (base / "src").mkdir(parents=True, exist_ok=True)
    (base / "src" / "module.py").write_text(contenu, encoding="utf-8")
    return base


def mutation(ancre: str = "valeur = 1", remplacement: str = "valeur = 2") -> Mutation:
    return Mutation(
        nom="essai", fichier="src/module.py", ancre=ancre, remplacement=remplacement
    )


def rouge(_: Path) -> tuple[bool, str]:
    return True, "FAILED tests/test_x.py::test_y - AssertionError"


def vert(_: Path) -> tuple[bool, str]:
    return False, "12 passed"


# --- La distinction qui manquait ----------------------------------------------


def test_une_ancre_introuvable_n_est_PAS_une_survivante(tmp_path: Path) -> None:
    """**Le defaut qui a motive cet outil.**

    Une ancre qui ne correspond a rien laisse le code intact ; la suite reste
    verte, et un script naif l'affiche comme une survivante. C'est l'inverse :
    aucune mesure n'a eu lieu. Les deux issues doivent porter des noms
    differents, sinon on croit mesurer quand on ne mesure rien.
    """
    depot(tmp_path)
    resultat = jouer([mutation(ancre="ligne absente")], racine=tmp_path, lancer=vert)[0]

    assert resultat.issue == NON_APPLIQUEE
    assert resultat.issue != SURVIVANTE, "la distinction est toute la raison d'etre de l'outil"
    assert "ancre introuvable" in resultat.detail
    assert resultat.echec, "une mesure absente doit faire echouer le lot"


def test_une_ancre_ambigue_est_refusee(tmp_path: Path) -> None:
    """Deux occurrences : on ne saurait pas ce qui a ete mute, donc ce que le
    resultat mesure. Refus plutot que choix arbitraire de la premiere."""
    depot(tmp_path, "valeur = 1\nvaleur = 1\n")
    with pytest.raises(MutationNonAppliquee, match="2 fois"):
        appliquer(tmp_path, mutation())


def test_un_remplacement_identique_a_l_ancre_est_refuse(tmp_path: Path) -> None:
    """Le cas qui reste quand l'ancre et le remplacement ont ete edites ensemble
    par distraction. Le fichier ne change pas : c'est une non-mutation, et elle
    rendrait « tout vert » comme les autres."""
    depot(tmp_path)
    with pytest.raises(MutationNonAppliquee, match="identique"):
        appliquer(tmp_path, mutation(remplacement="valeur = 1"))


def test_un_fichier_absent_est_refuse(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    with pytest.raises(MutationNonAppliquee, match="fichier absent"):
        appliquer(tmp_path, mutation())


# --- Les deux verdicts normaux ------------------------------------------------


def test_une_mutation_appliquee_et_vue_est_DETECTEE(tmp_path: Path) -> None:
    depot(tmp_path)
    resultat = jouer([mutation()], racine=tmp_path, lancer=rouge)[0]
    assert resultat.issue == DETECTEE
    assert not resultat.echec
    assert resultat.detail == "tests/test_x.py::test_y", "le premier test rouge est nomme"


def test_une_mutation_appliquee_et_NON_vue_est_SURVIVANTE(tmp_path: Path) -> None:
    """L'autre moitie. Sans elle, un outil qui rendrait toujours `DETECTEE`
    passerait le test precedent."""
    depot(tmp_path)
    resultat = jouer([mutation()], racine=tmp_path, lancer=vert)[0]
    assert resultat.issue == SURVIVANTE
    assert resultat.echec


# --- Le depot ne doit jamais rester mute --------------------------------------


def test_le_fichier_est_restaure_apres_la_mutation(tmp_path: Path) -> None:
    depot(tmp_path)
    jouer([mutation()], racine=tmp_path, lancer=vert)
    assert (tmp_path / "src" / "module.py").read_text(encoding="utf-8") == "valeur = 1\n"


def test_le_fichier_est_restaure_MEME_si_la_suite_explose(tmp_path: Path) -> None:
    """La restauration est en `finally`. Un outil qui laisserait le depot mute
    apres un plantage transformerait une mesure en degat — et le plantage
    suivant porterait sur du code que personne n'a ecrit."""
    depot(tmp_path)

    def explose(_: Path) -> tuple[bool, str]:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        jouer([mutation()], racine=tmp_path, lancer=explose)
    assert (tmp_path / "src" / "module.py").read_text(encoding="utf-8") == "valeur = 1\n"


def test_un_lot_continue_apres_une_mutation_non_appliquee(tmp_path: Path) -> None:
    """Une ancre cassee ne doit pas masquer les mutations suivantes : on veut
    la liste complete, pas le premier probleme rencontre."""
    depot(tmp_path)
    resultats = jouer(
        [mutation(ancre="absente"), mutation()], racine=tmp_path, lancer=rouge
    )
    assert [r.issue for r in resultats] == [NON_APPLIQUEE, DETECTEE]
