"""Les seuls tests du front qui EXECUTENT du code plutot que de le lire.

## Ce que les balayages ne peuvent pas voir

`test_front_sans_vocabulaire` et `test_front_ne_recalcule_rien` lisent
`web/src` et cherchent des motifs. Ils attrapent un libelle recopie et un
calcul ; ils ne peuvent rien dire d'une mise en forme **fausse** — une date
permutee, un arrondi qui mange un chiffre, une unite collee au mauvais champ,
un filtre vide envoye quand meme. Le code serait conforme a toutes les regles
et mentirait a l'ecran.

## Sans lanceur de tests, et sans installation

Le front n'a pas de lanceur de tests : en installer un demanderait un aller sur
le reseau. Node sait executer du TypeScript en retirant les types, et les deux
modules porteurs de logique — la mise en forme et la frontiere HTTP — sont
**purs** : pas de DOM, pas de React. `fetch` est une fonction globale, donc
remplacable. Ils s'executent tels quels.

C'est la raison d'avoir tenu la logique hors des composants. Un composant se
verifie avec un navigateur ; une fonction pure se verifie avec `node`. Le rendu
JSX reste non couvert, et c'est dit franchement : c'est le cout assume de ne
pas installer de navigateur d'essai, et la raison de garder les composants sans
decision.

## Le harnais doit savoir ROUGIR

Un lanceur qui rendrait toujours zero passerait pour un test vert. Les tests de
dents recopient un module dans un repertoire jetable, y appliquent une
alteration precise, et exigent l'echec. Meme controle que dans
`test_symboles_morts` et `test_muter` : on ne verifie pas seulement que l'outil
dit « tout va bien », on verifie qu'il sait dire autre chose.

Les deux alterations choisies produisent une sortie **plausible** — une date
bien formee mais fausse, une requete valide mais surchargee. Ce sont celles
qu'une relecture laisse passer.

## L'absence de `node` est annoncee, jamais silencieuse

Sans `node`, le test est saute avec son motif. Un saut se voit dans la sortie
de `pytest` ; un `assert True` de repli ne se verrait pas. La machine qui
touche a `web/` a `node`, sans quoi le front ne se construit pas.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
WEB = RACINE / "web"

# Node retire les types sans les verifier ; le typage est verifie ailleurs, par
# `npm run verifier` (tsc --noEmit) et par `tests/test_types_web.py`.
ARGUMENTS = ("--experimental-strip-types",)

ASSERTIONS = ("format.test.ts", "client.test.ts")


def _node() -> str:
    chemin = shutil.which("node")
    if chemin is None:
        pytest.skip("node absent : le front ne se construit pas non plus sans lui")
    return chemin


def _lancer(script: Path, racine: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [_node(), *ARGUMENTS, str(script)],
        capture_output=True,
        text=True,
        cwd=racine,
        check=False,
    )


@pytest.mark.parametrize("nom", ASSERTIONS)
def test_la_logique_du_front_passe_ses_assertions(nom: str) -> None:
    execution = _lancer(WEB / "tests" / nom, RACINE)
    assert execution.returncode == 0, (
        f"les assertions de `web/tests/{nom}` ont echoue :\n"
        f"{execution.stdout}\n{execution.stderr}"
    )


@pytest.mark.parametrize(
    ("nom", "module", "avant", "apres", "pourquoi"),
    [
        (
            "format.test.ts",
            "src/format.ts",
            "`${jour[3]}/${jour[2]}/${jour[1]}`",
            "`${jour[1]}/${jour[2]}/${jour[3]}`",
            "une date permutee reste une date bien formee",
        ),
        (
            "client.test.ts",
            "src/api/client.ts",
            'if (saisie !== "") requete.set(cle, saisie);',
            "requete.set(cle, saisie);",
            "une requete surchargee de filtres vides reste une requete valide",
        ),
    ],
)
def test_le_harnais_sait_rougir(
    tmp_path: Path, nom: str, module: str, avant: str, apres: str, pourquoi: str
) -> None:
    """**Les dents.** On altere une copie, et on exige l'echec."""
    copie = tmp_path / "web"
    shutil.copytree(WEB / "src", copie / "src")
    shutil.copytree(WEB / "tests", copie / "tests")

    source = copie / module
    intact = source.read_text(encoding="utf-8")
    altere = intact.replace(avant, apres)
    assert altere != intact, (
        f"l'alteration n'a pas ete appliquee sur {module} — une mutation non "
        "appliquee n'est PAS une survivante, et sa sortie verte ne prouve rien"
    )
    source.write_text(altere, encoding="utf-8")

    execution = _lancer(copie / "tests" / nom, tmp_path)
    assert execution.returncode != 0, (
        f"{pourquoi} : le harnais ne garde rien s'il reste vert"
    )
