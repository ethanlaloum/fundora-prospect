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

from collections.abc import Callable
from itertools import count
from pathlib import Path

import pytest

from tools.muter import (
    DETECTEE,
    NON_APPLIQUEE,
    SURVIVANTE,
    Mutation,
    MutationNonAppliquee,
    SuiteDejaRouge,
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


ROUGE = (True, "FAILED tests/test_x.py::test_y - AssertionError")
VERT = (False, "12 passed")


def rouge(_: Path) -> tuple[bool, str]:
    """Rouge DES LE DEPART, donc avant toute mutation : rien n'est mesurable."""
    return ROUGE


def vert(_: Path) -> tuple[bool, str]:
    return VERT


def vert_puis_rouge() -> Callable[[Path], tuple[bool, str]]:
    """Une suite verte au depart et rouge sous mutation.

    **C'est la seule forme qui permette de mesurer quoi que ce soit**, et c'est
    pour ca que le double doit la distinguer d'une suite rouge en permanence.
    Un double qui rendrait « rouge » a tous les appels — ce qu'il faisait avant
    la mesure de reference — validerait l'outil contre le defaut meme qu'il
    doit signaler.
    """
    appels = count()
    return lambda _: VERT if next(appels) == 0 else ROUGE


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


# --- La mesure de reference ---------------------------------------------------


def test_une_suite_DEJA_rouge_refuse_de_mesurer(tmp_path: Path) -> None:
    """**Le troisieme cas ou la sortie ne veut rien dire.**

    Quand la suite rougit avant toute mutation, chaque mutation est « DETECTEE »
    — le lot affiche un sans-faute, la lecture la plus rassurante possible, et
    aucune mesure n'a eu lieu. Un refus, donc, et pas un verdict : c'est la meme
    decision que pour `MutationNonAppliquee`, et pour la meme raison.
    """
    depot(tmp_path)
    with pytest.raises(SuiteDejaRouge, match="avant toute mutation"):
        jouer([mutation()], racine=tmp_path, lancer=rouge)


def test_un_refus_de_mesure_NOMME_le_test_deja_rouge(tmp_path: Path) -> None:
    """Sans le nom, le refus envoie chercher sans dire ou.

    C'est la difference entre « quelque chose ne va pas » et une piste : le
    premier echec est deja dans la sortie de la suite, il suffit de le porter.
    """
    depot(tmp_path)
    with pytest.raises(SuiteDejaRouge, match=r"tests/test_x\.py::test_y"):
        jouer([mutation()], racine=tmp_path, lancer=rouge)


def test_un_refus_de_mesure_LAISSE_LE_DEPOT_INTACT(tmp_path: Path) -> None:
    """La mesure de reference passe AVANT la premiere ecriture.

    Sinon un lot refuse laisserait la premiere mutation sur le disque, et le
    depot serait mute par un outil qui vient d'annoncer qu'il ne mesurait
    rien — une mesure transformee en degat, ce que la restauration en `finally`
    interdit deja partout ailleurs.
    """
    depot(tmp_path)
    with pytest.raises(SuiteDejaRouge):
        jouer([mutation()], racine=tmp_path, lancer=rouge)
    assert (tmp_path / "src" / "module.py").read_text(encoding="utf-8") == "valeur = 1\n"


def test_la_mesure_de_reference_COUTE_un_lancement_de_plus(tmp_path: Path) -> None:
    """L'autre moitie : elle a lieu, une seule fois, et le lot continue.

    Sans ce test, une mesure de reference qui ne serait jamais lancee passerait
    les trois precedents — ils n'exercent que le cas rouge. Deux mutations, donc
    trois lancements : un de reference, deux mesures.
    """
    depot(tmp_path)
    appels = count()

    def compter(_: Path) -> tuple[bool, str]:
        next(appels)
        return VERT

    jouer([mutation(), mutation(remplacement="valeur = 3")], racine=tmp_path, lancer=compter)
    assert next(appels) == 3, "une reference, puis une mesure par mutation"


# --- Les deux verdicts normaux ------------------------------------------------


def test_une_mutation_appliquee_et_vue_est_DETECTEE(tmp_path: Path) -> None:
    depot(tmp_path)
    resultat = jouer([mutation()], racine=tmp_path, lancer=vert_puis_rouge())[0]
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

    # Verte a la mesure de reference, puis elle explose : sans ce premier
    # appel vert, le lot serait refuse avant d'ecrire quoi que ce soit et le
    # test passerait sans avoir rien restaure.
    appels = count()

    def explose(_: Path) -> tuple[bool, str]:
        if next(appels) == 0:
            return VERT
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        jouer([mutation()], racine=tmp_path, lancer=explose)
    assert (tmp_path / "src" / "module.py").read_text(encoding="utf-8") == "valeur = 1\n"


def test_un_lot_continue_apres_une_mutation_non_appliquee(tmp_path: Path) -> None:
    """Une ancre cassee ne doit pas masquer les mutations suivantes : on veut
    la liste complete, pas le premier probleme rencontre."""
    depot(tmp_path)
    resultats = jouer(
        [mutation(ancre="absente"), mutation()], racine=tmp_path, lancer=vert_puis_rouge()
    )
    assert [r.issue for r in resultats] == [NON_APPLIQUEE, DETECTEE]
