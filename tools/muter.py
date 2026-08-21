"""L'outil de mutation, et le controle qui lui manquait.

## Pourquoi il devient un outil versionne

La mutation est la methode de verification centrale de ce projet — la lecon
« la mutation n'est pas une verification, c'est l'ecriture du test » la place
au coeur de la facon dont les tests sont ecrits. Elle etait pourtant jouee par
des scripts shell jetables, reecrits a chaque fois.

Un de ces scripts a produit exactement le defaut que le projet documente
ailleurs. Une mutation dont l'ancre ne correspondait a rien n'a **pas ete
appliquee** ; la suite a tourne sur le code intact et a rendu « 595 passed ».
Lu vite, ca ressemble a une survivante. C'est pire : c'est une mutation qui n'a
jamais eu lieu, et rien dans la sortie ne l'en distinguait.

**Une mutation non appliquee et une mutation non detectee produisent la meme
sortie.** C'est le meme mecanisme que la limite connue de
`tools/symboles_morts.py` — anticipe pour l'audit de code mort, pas vu pour
l'outil de mutation lui-meme. D'ou ce module, et d'ou le fait que l'application
soit **verifiee** et non supposee.

## Les trois issues, et pourquoi il en faut trois

| Issue | Ce qui s'est passe | Verdict |
|---|---|---|
| `NON APPLIQUEE` | l'ancre est absente, ambigue, ou ne change rien | **erreur d'outil** |
| `SURVIVANTE` | le code a change, la suite reste verte | **trou de test** |
| `DETECTEE` | le code a change, la suite rougit | attendu |

Les deux premieres font echouer le lot, pour des raisons opposees : l'une dit
que la mesure n'a pas eu lieu, l'autre qu'elle a eu lieu et qu'elle est mauvaise.
Les confondre, c'est croire mesurer quand on ne mesure rien.

## Ce qu'il ne fait pas

Il ne genere pas les mutations. Choisir quoi casser demande de savoir ce que le
test pretend garder — c'est le travail, et l'automatiser rendrait des milliers
de mutations equivalentes dont personne ne lirait la sortie. « Un audit qui crie
au loup est desactive dans la semaine » vaut ici aussi.

Usage :

    python tools/muter.py < lot.json

ou `lot.json` est une liste d'objets `{nom, fichier, ancre, remplacement}`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

RACINE_DEFAUT = Path(__file__).resolve().parent.parent

NON_APPLIQUEE = "NON APPLIQUEE"
SURVIVANTE = "SURVIVANTE"
DETECTEE = "DETECTEE"


class MutationNonAppliquee(Exception):
    """L'ancre n'a pas produit de modification. **Ce n'est pas une survivante.**

    Levee plutot que rendue en valeur : une mutation non appliquee doit
    interrompre le raisonnement de l'appelant, pas se ranger a cote des autres
    resultats ou elle se lirait comme un verdict.
    """


class SuiteDejaRouge(Exception):
    """La suite rougit AVANT toute mutation : aucune mesure n'est possible.

    **Le troisieme visage du meme defaut, trouve en s'en servant.** Cet outil a
    ete ecrit parce qu'une mutation non appliquee et une mutation non detectee
    produisaient la meme sortie. Il restait un cas ou la sortie ne veut rien
    dire non plus, et celui-la est pire : quand la suite est deja rouge, **tout
    est DETECTEE**. Le lot affiche un sans-faute — la lecture la plus
    rassurante possible — alors qu'aucune mutation n'a ete mesuree.

    Mesure faite le 2026-08-21 sur la passe de design : sept mutations, sept
    « DETECTEE », et les sept citaient le meme test rouge, qui n'avait aucun
    rapport avec elles. Le detail le disait ; le total disait l'inverse.

    D'ou la mesure de reference, une exception plutot qu'un verdict, et le cout
    assume d'un lancement de suite en plus par lot.
    """


@dataclass(frozen=True)
class Mutation:
    nom: str
    fichier: str
    ancre: str
    remplacement: str


@dataclass(frozen=True)
class Resultat:
    mutation: Mutation
    issue: str
    detail: str = ""

    @property
    def echec(self) -> bool:
        """Vrai pour les deux issues qui doivent faire echouer le lot.

        `NON APPLIQUEE` et `SURVIVANTE` echouent toutes les deux, pour des
        raisons opposees — mesure absente contre mesure mauvaise.
        """
        return self.issue != DETECTEE


def appliquer(racine: Path, mutation: Mutation) -> str:
    """Ecrit la mutation et **verifie qu'elle a change quelque chose**.

    Trois refus, tous bruyants :

    - l'ancre est absente — faute de frappe, indentation, code deplace depuis ;
    - l'ancre apparait plusieurs fois — on ne saurait pas ce qui a ete mute ;
    - le contenu final est identique — un remplacement egal a l'ancre.

    Le dernier cas a l'air absurde et ne l'est pas : c'est celui qui reste quand
    l'ancre et le remplacement ont ete edites en meme temps par distraction.
    """
    chemin = racine / mutation.fichier
    if not chemin.exists():
        raise MutationNonAppliquee(f"{mutation.nom} : fichier absent — {mutation.fichier}")

    avant = chemin.read_text(encoding="utf-8")
    occurrences = avant.count(mutation.ancre)
    if occurrences == 0:
        raise MutationNonAppliquee(
            f"{mutation.nom} : ancre introuvable dans {mutation.fichier}. "
            "Verifier l'indentation et les retours a la ligne."
        )
    if occurrences > 1:
        raise MutationNonAppliquee(
            f"{mutation.nom} : ancre presente {occurrences} fois dans "
            f"{mutation.fichier} — on ne saurait pas ce qui a ete mute."
        )

    apres = avant.replace(mutation.ancre, mutation.remplacement)
    if apres == avant:
        raise MutationNonAppliquee(
            f"{mutation.nom} : le remplacement est identique a l'ancre, "
            "le fichier n'a pas change."
        )

    chemin.write_text(apres, encoding="utf-8")
    return avant


def suite_rougit(racine: Path) -> tuple[bool, str]:
    """Lance `pytest` et dit s'il a rougi. Sortie complete gardee pour le detail."""
    execution = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-q"],
        cwd=racine,
        capture_output=True,
        text=True,
    )
    return execution.returncode != 0, execution.stdout


def _premier_echec(sortie: str) -> str:
    for ligne in sortie.splitlines():
        if ligne.startswith("FAILED "):
            return ligne.removeprefix("FAILED ").split(" ")[0]
    return ""


def jouer(
    mutations: Sequence[Mutation],
    *,
    racine: Path | None = None,
    lancer: Callable[[Path], tuple[bool, str]] = suite_rougit,
    tracer: Callable[[str], None] = lambda _: None,
) -> list[Resultat]:
    """Joue chaque mutation, restaure, et rend un verdict par mutation.

    `lancer` est un parametre — meme raison que `rechercher` et `enrichir` dans
    le coeur : les tests de cet outil ne peuvent pas relancer la suite depuis
    l'interieur de la suite.

    La restauration est en `finally` **et verifiee** : un outil qui laisserait
    le depot mute apres un plantage transformerait une mesure en degat.

    `tracer` publie chaque verdict AU FIL DE L'EAU. La premiere version
    n'imprimait qu'a la fin : cinq mutations, cinq lancements de la suite
    complete, et pas une ligne pendant plusieurs minutes. Un outil silencieux
    pendant qu'il travaille est indistinguable d'un outil bloque — et on le tue
    avant qu'il ait fini.
    """
    racine = racine or RACINE_DEFAUT
    resultats: list[Resultat] = []

    # La mesure de reference. Sans elle, une suite deja rouge rend « DETECTEE »
    # sur toute la ligne — voir `SuiteDejaRouge`. Elle est faite AVANT la
    # premiere ecriture, donc un refus laisse le depot intact.
    tracer("mesure de reference — suite en cours...")
    rouge_au_depart, sortie = lancer(racine)
    if rouge_au_depart:
        raise SuiteDejaRouge(
            "la suite rougit avant toute mutation : rien ne peut etre mesure. "
            f"Premier echec : {_premier_echec(sortie) or 'inconnu'}"
        )
    tracer("mesure de reference : suite verte, la mesure peut avoir lieu")

    for rang, mutation in enumerate(mutations, 1):
        tracer(f"[{rang}/{len(mutations)}] {mutation.nom} — suite en cours...")
        depart = time.monotonic()
        try:
            avant = appliquer(racine, mutation)
        except MutationNonAppliquee as exc:
            resultats.append(Resultat(mutation, NON_APPLIQUEE, str(exc)))
            tracer(f"[{rang}/{len(mutations)}] {NON_APPLIQUEE} — {exc}")
            continue

        chemin = racine / mutation.fichier
        try:
            rouge, sortie = lancer(racine)
        finally:
            chemin.write_text(avant, encoding="utf-8")
            if chemin.read_text(encoding="utf-8") != avant:
                raise RuntimeError(
                    f"restauration de {mutation.fichier} echouee — depot laisse mute"
                )

        resultat = Resultat(mutation, DETECTEE if rouge else SURVIVANTE, _premier_echec(sortie))
        resultats.append(resultat)
        ecoule = time.monotonic() - depart
        tracer(f"[{rang}/{len(mutations)}] {resultat.issue} en {ecoule:.0f} s — {resultat.detail}")

    return resultats


def _tracer(ligne: str) -> None:
    print(ligne, flush=True)


def main() -> int:
    lot = [Mutation(**brut) for brut in json.load(sys.stdin)]
    try:
        resultats = jouer(lot, tracer=_tracer)
    except SuiteDejaRouge as exc:
        # Un lot refuse doit se lire comme un refus, jamais comme un resultat :
        # c'est exactement la confusion que cet outil existe pour empecher.
        print(f"\nMESURE IMPOSSIBLE — {exc}")
        print("Reparer la suite d'abord ; un lot joue sur une suite rouge ne mesure rien.")
        return 1
    print()

    largeur = max((len(r.mutation.nom) for r in resultats), default=0)
    for resultat in resultats:
        print(f"  {resultat.mutation.nom:{largeur}}  {resultat.issue:13}  {resultat.detail}")

    echecs = [r for r in resultats if r.echec]
    non_appliquees = [r for r in echecs if r.issue == NON_APPLIQUEE]
    survivantes = [r for r in echecs if r.issue == SURVIVANTE]

    print(f"\n{len(resultats)} mutations : {len(resultats) - len(echecs)} detectees", end="")
    print(f", {len(survivantes)} survivantes, {len(non_appliquees)} non appliquees")
    if non_appliquees:
        print("\nNON APPLIQUEES — la mesure n'a pas eu lieu, ce ne sont PAS des survivantes :")
        for resultat in non_appliquees:
            print(f"  {resultat.detail}")
    if survivantes:
        print("\nSURVIVANTES — trous de test :")
        for resultat in survivantes:
            print(f"  {resultat.mutation.nom}")
    return 1 if echecs else 0


if __name__ == "__main__":
    raise SystemExit(main())
