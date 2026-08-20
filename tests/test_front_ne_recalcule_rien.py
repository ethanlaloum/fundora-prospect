"""Le front AFFICHE, il ne calcule pas.

## La contrainte, et pourquoi un verrou plutot qu'une intention

« Le front n'affiche que ce que l'API rend. Il ne recalcule ni score, ni
compteur, ni motif. » C'est la contrainte structurante de la Phase 7, et elle a
la meme forme que toutes celles de ce projet : ecrite, elle ne garantit rien ;
c'est le defaut de la Phase 3 bis, ou `Provenance` etait documentee, testee
nulle part, et fausse en production.

Le danger n'est pas theorique. Recalculer est *facile* en JavaScript, la sortie
reste **plausible**, et rien ne la distingue a l'ecran d'une valeur venue du
coeur. Trois occasions concretes :

- diviser `montant_eur` pour afficher des milliers d'euros ;
- afficher `leads.length` au lieu du compteur `leads_rendus` que l'API rend —
  or les deux ne sont **pas** la meme grandeur des qu'une coupe existe, et
  c'est exactement le defaut « le compteur decrit un budget, pas une
  population » reintroduit dans une autre langue ;
- ponderer un critere du breakdown pour « ameliorer » l'affichage, ce qui
  ferait sortir un score que `evaluer` n'a jamais produit.

## Deux regles, et la premiere est DERIVEE du schema

**1. Aucune arithmetique sur un champ numerique de l'API.** La liste de ces
champs n'est pas ecrite ici : elle est lue dans `web/src/api/schema.d.ts`, qui
est lui-meme genere depuis des reponses reelles. Un champ numerique ajoute
demain au coeur est donc couvert le jour ou le schema est regenere — meme
mecanique que le vocabulaire derive du coeur dans
`tests/test_front_sans_vocabulaire.py`.

**2. Aucun `.length`.** Compter est un calcul. Toute grandeur affichable doit
venir d'un compteur rendu par l'API ; si elle n'existe pas, c'est une route qui
ne rend pas assez, pas une invitation a la coder en JavaScript. La regle est
volontairement brutale — un `.length` legitime est indiscernable a la lecture
d'un `.length` qui remplace un compteur, et une exception tolerable une fois se
tolere ensuite toujours.

## Les commentaires sont retires AVANT le balayage

C'est la difference d'avec le verrou de vocabulaire, qui balaye le texte entier
y compris les commentaires — et le fait volontairement, parce qu'un libelle
recopie dans un commentaire finit par etre recopie dans une chaine.

Ici la propriete gardee est autre : **un commentaire ne calcule pas.** Le
laisser dans le balayage n'ajouterait aucune garantie et couterait des faux
positifs immediats, `// montant_eur ...` etant deja un `/` suivi du nom d'un
champ. « Un audit qui crie au loup est desactive dans la semaine » : ce
retrait-la est le prix de le garder lisible.

Le retrait protege `https://` (le `//` d'une URL n'est pas un commentaire),
sinon la ligne serait tronquee et un vrai calcul place apres passerait.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
WEB = RACINE / "web" / "src"
SCHEMA = WEB / "api" / "schema.d.ts"

# Les dossiers produits par l'outillage : ils ne sont pas du code ecrit ici.
IGNORES = {"node_modules", "dist", ".vite"}

# Le schema est genere et se decrit lui-meme ; il ne s'execute pas.
GENERES = {SCHEMA}

OPERATEURS = r"[+\-*/%]"


def champs_numeriques(schema: Path | None = None) -> set[str]:
    """Les champs que l'API rend en nombre, lus dans le schema genere.

    Le motif exige un type *feuille* — `number` ou `null | number` — et non
    n'importe quelle declaration contenant le mot. Sans cette exigence,
    `contenu: Record<string, number | string>` ferait entrer « contenu » dans
    la liste des champs numeriques, et le verrou signalerait des calculs sur un
    nom qui n'en designe aucun.
    """
    texte = (schema or SCHEMA).read_text(encoding="utf-8")
    return set(re.findall(r"^\s*(\w+)\??: (?:null \| )?number;\s*$", texte, flags=re.M))


def sans_commentaires(texte: str) -> str:
    """Retire les commentaires. Voir l'entete : un commentaire ne calcule pas.

    Le `(?<!:)` protege `https://` — sans lui, tout ce qui suit une URL sur la
    meme ligne sortirait du balayage, ce qui creerait une cachette au lieu d'une
    tolerance.
    """
    texte = re.sub(r"/\*.*?\*/", " ", texte, flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", " ", texte)


def calculs(texte: str, champs: set[str]) -> set[str]:
    """Les champs de l'API sur lesquels ce texte fait une operation."""
    code = sans_commentaires(texte)
    trouves = set()
    for champ in champs:
        # A gauche de l'operateur le champ termine un chemin (`lead.score +`) ;
        # a droite il en commence un (`100 - lead.score`), d'ou le chemin
        # optionnel. Sans lui, la moitie des calculs passait — mesure faite :
        # `100 - lead.score` n'etait pas signale.
        avant = re.search(rf"{OPERATEURS}\s*(?:[\w$]+\.)*\b{re.escape(champ)}\b", code)
        apres = re.search(rf"\b{re.escape(champ)}\b\s*{OPERATEURS}", code)
        if avant or apres:
            trouves.add(champ)
    return trouves


def comptages(texte: str) -> int:
    """Les `.length`, c'est-a-dire les comptages faits ici plutot que lus."""
    return len(re.findall(r"\.length\b", sans_commentaires(texte)))


def fichiers_web(base: Path | None = None) -> list[Path]:
    """Le repertoire est un PARAMETRE, jamais une globale substituee — meme
    raison que dans `test_front_sans_vocabulaire` : un `monkeypatch` qui rate sa
    cible laisse les tests de dents verts sur un repertoire vide."""
    base = base or WEB
    if not base.exists():
        return []
    return sorted(
        p
        for p in base.rglob("*")
        if p.is_file() and not (set(p.parts) & IGNORES) and p not in GENERES
    )


# --- Le depot est propre ------------------------------------------------------


def test_aucune_arithmetique_sur_un_champ_rendu_par_l_api() -> None:
    champs = champs_numeriques()
    fautifs = {
        p.relative_to(RACINE).as_posix(): trouves
        for p in fichiers_web()
        if (trouves := calculs(p.read_text(encoding="utf-8", errors="ignore"), champs))
    }
    assert not fautifs, (
        "le front calcule sur des champs que l'API rend deja — la valeur doit "
        "venir du coeur, ou la route ne rend pas assez :\n"
        + "\n".join(f"  {f} : {sorted(t)}" for f, t in sorted(fautifs.items()))
    )


def test_aucun_comptage_dans_le_front() -> None:
    fautifs = [
        p.relative_to(RACINE).as_posix()
        for p in fichiers_web()
        if comptages(p.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not fautifs, (
        "compter est un calcul : la grandeur doit venir d'un compteur de l'API "
        f"(`leads_rendus`, `correspondants`, …), pas d'un `.length` — {fautifs}"
    )


def test_le_balayage_voit_bien_des_fichiers() -> None:
    """Un mauvais chemin rendrait les deux verrous muets : verts pour la
    mauvaise raison, ce qui est indistinguable de verts pour la bonne."""
    assert fichiers_web(), "aucun fichier balaye dans web/src"


def test_les_champs_numeriques_sont_DERIVES_et_nombreux() -> None:
    """Un schema mal lu rendrait un ensemble vide, et le premier verrou ne
    garderait plus rien sans que rien ne rougisse.

    On verifie qu'il couvre plusieurs familles : un champ de score, un champ de
    breakdown, un compteur de population. C'est la couverture qui fait la valeur
    du test, pas la presence d'un ensemble.
    """
    champs = champs_numeriques()
    assert len(champs) >= 12, f"seulement {len(champs)} champs numeriques derives"
    assert {"score", "points", "poids"} <= champs, "le scoring doit etre couvert"
    assert {"montant_eur", "jours_ecoules"} <= champs, "les faits aussi"
    assert {"annonces_publiees", "leads_rendus"} <= champs, "les compteurs aussi"
    assert "contenu" not in champs, (
        "`contenu: Record<string, number | string>` n'est pas un champ numerique"
    )


# --- Les verrous ont des dents ------------------------------------------------


@pytest.mark.parametrize(
    ("contenu", "pourquoi"),
    [
        ("const k = lead.montant_eur / 1000;", "une division pour afficher des milliers"),
        ("const t = a.points + b.points;", "une somme de contributions"),
        ("const s = 100 - lead.score;", "un complement de score"),
        ("const n = s.annonces_publiees - s.annonces_rapatriees;", "un ecart de population"),
    ],
)
def test_le_verrou_attrape_un_calcul(contenu: str, pourquoi: str) -> None:
    assert calculs(contenu, champs_numeriques()), pourquoi


def test_le_verrou_attrape_un_comptage() -> None:
    assert comptages("const rendus = reponse.leads.length;")


def test_le_verrou_ne_crie_pas_au_loup() -> None:
    """Trois emplois legitimes qui ressemblent a un calcul.

    Sans ces trois cas le verrou serait invivable, et un verrou invivable est
    desactive dans la semaine — donc equivalent a pas de verrou.
    """
    champs = champs_numeriques()
    assert not calculs("const rang = index + 1;", champs), "un compteur de rang local"
    assert not calculs("<td>{lead.score}</td>", champs), "un champ affiche tel quel"
    assert not calculs("// on n'ecrit pas montant_eur / 1000 ici", champs), "un commentaire"


def test_le_retrait_des_commentaires_ne_cache_pas_la_ligne_entiere() -> None:
    """Le `//` d'une URL n'ouvre pas un commentaire.

    Sans le garde, tout ce qui suit `https://` sur la meme ligne disparaitrait
    du balayage — le retrait des commentaires deviendrait une cachette, et un
    calcul y serait invisible. C'est le mode degrade qui ressemble a un
    resultat, une fois de plus.
    """
    ligne = 'const u = "https://x/y"; const k = lead.montant_eur / 2;'
    assert calculs(ligne, champs_numeriques()) == {"montant_eur"}
