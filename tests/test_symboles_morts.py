"""Le verrou contre le code mort.

Le projet a un verrou par contrainte : transport pour les domaines, liste
blanche pour l'anonymisation, porte unique pour la tracabilite. Le code mort
etait la seule verification qui restait declarative — et elle a laisse passer
`Provenance` et `Lead` pendant cinq phases.

Ces tests font deux choses distinctes :
1. ils verrouillent l'etat courant du depot — aucun symbole public non
   construit ;
2. ils verifient que **l'audit lui-meme a des dents**, sur des cas fabriques.
   Un audit qui rend toujours « rien a signaler » passerait le point 1 sans
   rien garantir : c'est exactement le defaut qu'il est cense trouver.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tools.symboles_morts import auditer, collecter

RACINE = Path(__file__).resolve().parent.parent


# --- Le depot est propre ------------------------------------------------------


def test_aucun_symbole_public_non_construit() -> None:
    """Le verrou. Un symbole public que rien ne construit est du code mort :
    aucun test ne peut echouer dessus, puisque aucun test ne l'appelle."""
    morts = auditer(RACINE)
    assert morts == [], "code mort detecte : " + ", ".join(
        f"{s.nom} ({s.module}.py:{s.ligne})" for s in morts
    )


def test_l_audit_voit_bien_le_code_du_projet() -> None:
    """Garde-fou contre un audit qui ne regarderait rien. Sans lui, une erreur
    de chemin rendrait `auditer` vert et muet — vert pour la mauvaise raison,
    ce qui est pire que rouge."""
    symboles = collecter(RACINE)
    assert len(symboles) > 40, f"seulement {len(symboles)} symboles vus"
    for attendu in ("Lead", "Provenance", "LiquidityEvent", "serialiser", "rechercher"):
        assert attendu in symboles, f"{attendu} devrait etre vu par l'audit"


# --- L'audit a des dents ------------------------------------------------------


def depot_factice(base: Path, source: str, consommateur: str = "") -> Path:
    """Mini-depot jetable, meme arborescence que le vrai : `src/` et `tests/`."""
    (base / "src" / "paquet").mkdir(parents=True)
    (base / "tests").mkdir()
    (base / "src" / "paquet" / "module.py").write_text(
        textwrap.dedent(source), encoding="utf-8"
    )
    (base / "tests" / "test_x.py").write_text(textwrap.dedent(consommateur), encoding="utf-8")
    return base


def test_l_audit_attrape_une_classe_jamais_construite(tmp_path: Path) -> None:
    """Le cas `Lead` : defini, jamais instancie, jamais meme mentionne."""
    depot_factice(tmp_path, "class Orpheline:\n    pass\n")
    morts = {s.nom for s in auditer(tmp_path)}
    assert "Orpheline" in morts


def test_une_annotation_ne_sauve_pas_un_symbole(tmp_path: Path) -> None:
    """**Le cas `Provenance`**, celui qui a rendu le defaut invisible.

    Le nom apparait dans le code — `porte: Annotee` — donc un outil qui compte
    les occurrences le declare utilise. Mais une annotation ne construit rien :
    elle reste vraie et silencieuse alors qu'aucune instance n'existe.
    """
    depot_factice(
        tmp_path,
        """
        class Annotee:
            pass

        class Porteuse:
            porte: Annotee

        def fabriquer() -> Annotee: ...
        """,
        consommateur="from paquet.module import Porteuse\n\nPorteuse()\n",
    )
    morts = {s.nom for s in auditer(tmp_path)}
    assert "Annotee" in morts, "une annotation ne doit pas valoir justification"
    assert "Porteuse" not in morts, "Porteuse est construite, elle est vivante"


def test_un_appel_sauve_un_symbole(tmp_path: Path) -> None:
    depot_factice(
        tmp_path,
        "class Construite:\n    pass\n",
        consommateur="from paquet.module import Construite\n\nConstruite()\n",
    )
    assert {s.nom for s in auditer(tmp_path)} == set()


def test_un_modele_annotant_un_parametre_ENREGISTRE_est_justifie(tmp_path: Path) -> None:
    """Le cas `Hypothese` : FastAPI la construit a chaque requete, aucun Python
    ne la nomme en position d'appel."""
    depot_factice(
        tmp_path,
        """
        def route(f):
            return f

        class Corps:
            pass

        @route
        def poster(corps: Corps) -> int:
            return 1
        """,
        consommateur="from paquet.module import route\n\nroute(None)\n",
    )
    assert "Corps" not in {s.nom for s in auditer(tmp_path)}


def test_un_modele_annotant_un_parametre_ORDINAIRE_reste_signale(tmp_path: Path) -> None:
    """**L'autre moitie, et c'est elle qui empeche l'exemption de tout avaler.**

    Sans ce cas, la regle « une annotation de parametre justifie » vaudrait
    partout, et le cas `Provenance` — annote, mort — redeviendrait invisible.
    Ce qui justifie n'est pas l'annotation, c'est le DECORATEUR d'enregistrement
    qui prouve qu'un appelant externe existe.
    """
    depot_factice(
        tmp_path,
        """
        class Corps:
            pass

        def ordinaire(corps: Corps) -> int:
            return 1
        """,
        consommateur="from paquet.module import ordinaire\n\nordinaire(None)\n",
    )
    assert "Corps" in {s.nom for s in auditer(tmp_path)}, (
        "sans enregistrement, une annotation de parametre ne justifie rien"
    )


def test_un_decorateur_INERTE_ne_justifie_pas_l_annotation_d_un_parametre(
    tmp_path: Path,
) -> None:
    """`@cache` transforme la fonction sur place, il ne la confie a personne.

    La nouvelle exemption doit reutiliser la MEME frontiere que l'ancienne —
    `_est_un_enregistrement` — et pas s'en inventer une plus large du genre
    « la fonction porte un decorateur ». Le decorateur doit ENREGISTRER.
    """
    depot_factice(
        tmp_path,
        """
        from functools import cache

        class Corps:
            pass

        @cache
        def calcule(corps: Corps) -> int:
            return 1
        """,
        consommateur="from paquet.module import calcule\n\ncalcule(None)\n",
    )
    assert "Corps" in {s.nom for s in auditer(tmp_path)}, (
        "un decorateur inerte ne confie le symbole a personne"
    )


def test_un_symbole_decore_est_justifie(tmp_path: Path) -> None:
    """Les trois outils MCP : appeles par le protocole, jamais par du Python."""
    depot_factice(
        tmp_path,
        """
        def enregistrer(f):
            return f

        @enregistrer
        def outil():
            return 1
        """,
        consommateur="from paquet.module import enregistrer\n\nenregistrer(None)\n",
    )
    assert "outil" not in {s.nom for s in auditer(tmp_path)}


def test_un_dataclass_mort_reste_mort(tmp_path: Path) -> None:
    """`@dataclass` ne justifie rien : il transforme la classe sur place, il ne
    la confie a aucun appelant. Un decorateur ne vaut justification que s'il
    ENREGISTRE le symbole quelque part, comme `@serveur.tool`.

    Le cas est realiste : `ResultatRecherche` et `GrillePonderation` sont des
    dataclasses gelees. Accepter `@dataclass` rendrait n'importe laquelle
    d'entre elles indetectable une fois morte.
    """
    depot_factice(
        tmp_path,
        """
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class JamaisConstruite:
            champ: int
        """,
    )
    assert "JamaisConstruite" in {s.nom for s in auditer(tmp_path)}


def test_un_usage_par_attribut_est_justifie(tmp_path: Path) -> None:
    """`Qualification.ACHAT`, `GrillePonderation.defaut()` : l'appel porte sur
    l'attribut, mais il prouve que la classe est vivante."""
    depot_factice(
        tmp_path,
        """
        class Enumeree:
            VALEUR = 1

            @classmethod
            def defaut(cls):
                return cls()
        """,
        consommateur=(
            "from paquet.module import Enumeree\n\n"
            "x = Enumeree.VALEUR\ny = Enumeree.defaut()\n"
        ),
    )
    assert "Enumeree" not in {s.nom for s in auditer(tmp_path)}


@pytest.mark.parametrize("prive", ["_Cachee", "__Privee"])
def test_les_symboles_prives_sont_hors_perimetre(tmp_path: Path, prive: str) -> None:
    """L'audit porte sur l'API publique du paquet. Un helper prive non utilise
    est du bruit local, pas un modele fantome dans la specification."""
    depot_factice(tmp_path, f"class {prive}:\n    pass\n")
    assert auditer(tmp_path) == []
