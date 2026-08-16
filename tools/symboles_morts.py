"""Audit du code mort : les symboles publics de `src/` que rien ne construit.

## Pourquoi ce verrou existe

`Provenance` et `Lead` ont ete du code mort de la Phase 2 a la Phase 3 bis.
Ils etaient definis, documentes, cites dans la specification — et construits
nulle part. Le serveur MCP montait sa charge utile a la main et n'y mettait
qu'un des quatre champs de tracabilite exiges par la contrainte 3.

**416 tests ne l'ont pas signale, et c'est structurel : un test ne peut pas
echouer sur du code qu'il n'appelle pas.** La couverture ne le voit pas non
plus — une classe jamais instanciee n'apparait pas comme une ligne manquante,
elle apparait comme une ligne `class` executee a l'import. Seule une analyse
du graphe d'usage la trouve.

## Le critere : jamais en position d'appel

Un symbole est suspect quand son nom **n'apparait jamais en position d'appel,
`X(...)`, dans tout le depot**.

Le critere plus intuitif — « jamais importe hors de son module » — a ete
essaye et rejete : il rendait 27 resultats sur ce depot, presque tous des
constantes locales parfaitement utilisees. Inutilisable, donc ignore, donc
inutile.

### Une annotation de type n'est pas un usage

C'est le point qui a rendu `Provenance` invisible. Il **apparaissait** dans le
code, a la ligne `Lead.provenance: Provenance` — un outil qui compte les
occurrences du nom le voit donc comme utilise.

Mais une annotation ne construit rien. Elle declare une intention : « si un
`Lead` existe, son champ `provenance` sera de ce type. » Elle reste vraie, et
silencieuse, meme quand aucun `Lead` n'est jamais construit. `Provenance`
etait ainsi reference et mort en meme temps.

D'ou la distinction que fait cet audit : les occurrences en annotation sont
comptees a part et **ne valent pas justification**. Seul un appel prouve que
le code s'execute.

## Exemptions : declarees, jamais silencieuses

Deux formes d'usage reel n'apparaissent pas en position d'appel :

- un symbole **decore** (`@serveur.tool`) est appele par le protocole MCP ;
- une enumeration ou dataclass utilisee **par attribut** (`Qualification.ACHAT`,
  `GrillePonderation.defaut()`) : c'est l'attribut qui est appele, pas le nom.

Ces cas sont reconnus automatiquement et affiches AVEC leur justification. Un
symbole sans appel et sans justification reconnue fait echouer le test.

`@dataclass` ne compte pas comme une justification : il transforme la classe
sur place, il ne l'enregistre nulle part. Seuls les decorateurs qui confient le
symbole a un appelant externe justifient l'absence d'appel.

## Ce que cet audit ne peut pas faire

Il travaille sur des noms, pas sur des types resolus. Un appel qualifie —
`provenance.assembler(...)` — est compte pour le symbole `assembler`, sans
verifier que le module a gauche du point est bien le notre. **Un homonyme dans
une autre bibliotheque marquerait donc notre symbole comme vivant a tort.**

Ce choix est assume : la forme qualifiee est dominante dans ce depot, et sans
elle l'audit signalait `assembler` et `serialiser` comme morts alors que le
serveur MCP les appelle a chaque lead. Un audit qui crie au loup sur du code
vivant est desactive dans la semaine, donc ne protege plus de rien.

Le biais va donc vers le silence : l'audit peut manquer un symbole mort, il ne
doit pas en inventer. C'est la limite a garder en tete si un symbole porte un
nom tres commun.

Usage : `python tools/symboles_morts.py [racine]`
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

RACINE_DEFAUT = Path(__file__).resolve().parent.parent
DOSSIERS_ANALYSES = ("src", "tests", "tools", "explore", "bin")

# Un decorateur ne justifie un symbole que s'il l'ENREGISTRE quelque part —
# le protocole MCP l'appellera sans qu'aucun Python ne le nomme. `@dataclass`
# et consorts ne font que transformer la classe sur place : ils ne prouvent
# aucun usage, et les accepter masquerait du code mort.
DECORATEURS_INERTES = frozenset(
    {"dataclass", "final", "runtime_checkable", "total_ordering", "override", "cache"}
)


def _est_un_enregistrement(decorateur: str) -> bool:
    return decorateur.split("(")[0].split(".")[-1] not in DECORATEURS_INERTES


@dataclass
class Symbole:
    nom: str
    module: str
    ligne: int
    genre: str
    decorateurs: list[str] = field(default_factory=list)
    appele_dans: set[str] = field(default_factory=set)
    annote_dans: set[str] = field(default_factory=set)
    attribut_appele_dans: set[str] = field(default_factory=set)

    @property
    def justification(self) -> str | None:
        """Pourquoi ce symbole est vivant. Ordre du plus probant au moins."""
        if self.appele_dans:
            return "appele"
        if self.attribut_appele_dans:
            return "utilise par attribut"
        enregistrement = [d for d in self.decorateurs if _est_un_enregistrement(d)]
        if enregistrement:
            return f"decore par @{enregistrement[0].split('(')[0]}"
        return None

    @property
    def mort(self) -> bool:
        return self.justification is None


def fichiers_python(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def collecter(racine: Path) -> dict[str, Symbole]:
    """Definitions publiques de niveau module dans `src/`."""
    source = racine / "src"
    symboles: dict[str, Symbole] = {}
    for chemin in fichiers_python(source):
        module = chemin.relative_to(source).with_suffix("").as_posix().replace("/", ".")
        for noeud in ast.parse(chemin.read_text(encoding="utf-8")).body:
            if not isinstance(noeud, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if noeud.name.startswith("_"):
                continue
            symboles[noeud.name] = Symbole(
                nom=noeud.name,
                module=module,
                ligne=noeud.lineno,
                genre="class" if isinstance(noeud, ast.ClassDef) else "def",
                decorateurs=[ast.unparse(d) for d in noeud.decorator_list],
            )
    return symboles


def _noeuds_d_annotation(arbre: ast.AST) -> set[int]:
    """Identifiants des noeuds situes dans une annotation de type.

    Une annotation declare une intention, elle n'execute rien : c'est
    exactement ce qui rendait `Provenance` invisible.
    """
    dedans: set[int] = set()
    for noeud in ast.walk(arbre):
        for champ in ("annotation", "returns"):
            cible = getattr(noeud, champ, None)
            if cible is not None:
                dedans.update(id(sous) for sous in ast.walk(cible))
    return dedans


def analyser(racine: Path, symboles: dict[str, Symbole]) -> None:
    """Remplit les usages de chaque symbole, par nature."""
    for dossier in DOSSIERS_ANALYSES:
        base = racine / dossier
        if not base.exists():
            continue
        for chemin in fichiers_python(base):
            etiquette = chemin.relative_to(racine).as_posix()
            try:
                arbre = ast.parse(chemin.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            annotations = _noeuds_d_annotation(arbre)

            for noeud in ast.walk(arbre):
                if isinstance(noeud, ast.Call):
                    fonction = noeud.func
                    if isinstance(fonction, ast.Name) and fonction.id in symboles:
                        symboles[fonction.id].appele_dans.add(etiquette)
                    elif isinstance(fonction, ast.Attribute):
                        # `provenance.assembler(...)` : l'appel est qualifie par
                        # le module. C'est la forme dominante dans ce depot, et
                        # l'ignorer rendait l'audit inutilisable — il signalait
                        # `assembler` et `serialiser` comme morts alors que le
                        # serveur MCP les appelle a chaque lead.
                        if fonction.attr in symboles:
                            symboles[fonction.attr].appele_dans.add(etiquette)
                        # `GrillePonderation.defaut()` : l'appel porte sur
                        # l'attribut, mais il prouve que la classe est vivante.
                        socle = fonction.value
                        if isinstance(socle, ast.Name) and socle.id in symboles:
                            symboles[socle.id].attribut_appele_dans.add(etiquette)
                elif isinstance(noeud, ast.Attribute):
                    socle = noeud.value
                    if isinstance(socle, ast.Name) and socle.id in symboles:
                        symboles[socle.id].attribut_appele_dans.add(etiquette)
                elif isinstance(noeud, ast.Name) and noeud.id in symboles:
                    if id(noeud) in annotations:
                        symboles[noeud.id].annote_dans.add(etiquette)


def auditer(racine: Path | None = None) -> list[Symbole]:
    """Rend les symboles morts. Liste vide = aucun code mort."""
    racine = racine or RACINE_DEFAUT
    symboles = collecter(racine)
    analyser(racine, symboles)
    return [s for s in symboles.values() if s.mort]


def main() -> int:
    racine = Path(sys.argv[1]) if len(sys.argv) > 1 else RACINE_DEFAUT
    symboles = collecter(racine)
    analyser(racine, symboles)

    morts = [s for s in symboles.values() if s.mort]
    vivants_sans_appel = [s for s in symboles.values() if not s.mort and not s.appele_dans]

    print(f"{len(symboles)} classes et fonctions publiques dans {racine.name}/src\n")

    if vivants_sans_appel:
        print("Vivants sans appel direct — justification reconnue :")
        for s in sorted(vivants_sans_appel, key=lambda s: s.nom):
            lieu = f"{s.module.split('.')[-1]}.py:{s.ligne}"
            print(f"  {s.genre:6} {s.nom:32} {lieu:22} {s.justification}")
        print()

    if not morts:
        print("Aucun code mort : chaque symbole public est construit ou justifie.")
        return 0

    print(f"CODE MORT — {len(morts)} symbole(s) que rien ne construit :\n")
    for s in sorted(morts, key=lambda s: s.nom):
        print(f"  {s.genre:6} {s.nom:32} {s.module.split('.')[-1]}.py:{s.ligne}")
        if s.annote_dans:
            print(
                f"         annote dans {len(s.annote_dans)} fichier(s) — "
                "une annotation n'est pas un usage"
            )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
