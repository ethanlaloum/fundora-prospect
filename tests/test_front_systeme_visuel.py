"""Les valeurs de design vivent dans `theme.css`, et nulle part ailleurs.

## Pourquoi un verrou plutot qu'une intention

« Le systeme est dans un fichier de variables, on n'ecrit rien en dur ailleurs »
a exactement la forme des regles que ce projet a deja vues echouer : ecrite dans
un commentaire, elle est vraie le jour ou on l'ecrit et fausse trois commits
plus tard. Personne ne relit une feuille de style en comptant les valeurs.

Et la derive est indolore, ce qui est le pire cas. Un `13px` ecrit en clair rend
exactement comme `var(--taille-13)` — jusqu'au jour ou l'echelle bouge, ou l'un
des deux suit et pas l'autre. C'est le defaut signature du projet, le parametre
recopie qui derive de sa source, applique cette fois a la mise en forme.

## Quatre regles, et une seule exception

1. **Aucune couleur en clair.** Un hex, un `rgb(`, un nom de couleur : la
   palette est fermee a cinq gris, un accent et deux etats. Une sixieme couleur
   ne doit pas pouvoir naitre sans passer par le fichier qui les compte.
2. **Aucune duree en clair.** Quatre durees existent, toutes sous 200 ms. Un
   `300ms` ecrit dans une regle est precisement ce que la consigne interdit, et
   il ne se verrait sur aucune capture.
3. **Toute longueur en px est un multiple de 4.** C'est l'exception assumee :
   les largeurs de colonne d'une grille n'ont pas de jeton — il en faudrait un
   par colonne — mais elles restent sur le pas. Un `7px` se voit a l'ecran sans
   que personne sache dire quoi.
4. **Toute taille de texte est un jeton.** L'echelle a cinq valeurs ; un
   `font-size: 14px` en ajoute une sixieme en silence.

## Ce que ce verrou ne garde pas

Il lit du texte, il ne rend pas la page. Un jeton mal choisi — `--pas-32` la ou
il fallait `--pas-8` — passe sans rien dire, et c'est normal : ca se voit a
l'ecran, la ou un `#f3f3f3` de plus ne se voit pas. Le verrou garde la
fermeture des echelles, pas le gout.

Meme limite que partout ici, et elle est le prix de ne pas crier au loup.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
WEB = RACINE / "web" / "src"

# Le fichier de jetons est le seul endroit ou une valeur de design est ecrite :
# c'est tout l'objet du verrou.
JETONS = "theme.css"

IGNORES = {"node_modules", "dist", ".vite"}

# `white`, `black` et consorts contournent le motif hexadecimal sans effort.
NOMS_DE_COULEUR = ("white", "black", "silver", "gray", "grey", "red", "orange")


def sans_commentaires(texte: str) -> str:
    """Un commentaire ne peint pas.

    Meme raisonnement que dans le verrou de recalcul : la propriete gardee est
    ce que la feuille FAIT. Citer une valeur dans une explication est utile — le
    commentaire de `--etat-signal-fond` en cite une — et l'interdire couterait
    des reformulations sans rien garantir.
    """
    return re.sub(r"/\*.*?\*/", " ", texte, flags=re.S)


def couleurs(texte: str) -> set[str]:
    code = sans_commentaires(texte)
    trouvees = set(re.findall(r"#[0-9a-fA-F]{3,8}\b", code))
    trouvees |= {m.group(0) for m in re.finditer(r"\b(?:rgba?|hsla?)\(", code)}
    for nom in NOMS_DE_COULEUR:
        # Le nom doit etre en position de VALEUR, apres un deux-points : sans
        # ca, une classe `.bloc-orange` serait signalee alors qu'elle ne peint
        # rien par elle-meme.
        if re.search(rf":[^;{{}}]*\b{nom}\b", code, flags=re.IGNORECASE):
            trouvees.add(nom)
    return trouvees


def durees(texte: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:\.\d+)?m?s\b", sans_commentaires(texte)))


def longueurs_hors_grille(texte: str) -> set[str]:
    """Les px qui ne tombent pas sur le pas de 4, et toute autre unite.

    Le `rem` et le `em` sont refuses en bloc plutot que tolerés sur une grille :
    ils n'ont pas de pas commun avec les px, donc melanger les deux rend la
    grille invérifiable — et c'est comme ca que la feuille etait ecrite avant.
    """
    code = sans_commentaires(texte)
    fautives = {
        f"{valeur}px"
        for valeur in re.findall(r"\b(\d+)px\b", code)
        if int(valeur) % 4
    }
    fautives |= set(re.findall(r"\b\d+(?:\.\d+)?r?em\b", code))
    return fautives


def tailles_hors_echelle(texte: str) -> set[str]:
    """Les `font-size` qui ne citent pas un jeton de l'echelle."""
    code = sans_commentaires(texte)
    return {
        valeur.strip()
        for valeur in re.findall(r"font-size:\s*([^;{}]+);", code)
        if not re.fullmatch(r"var\(--taille-\d+\)|inherit", valeur.strip())
    }


def feuilles(base: Path | None = None) -> list[Path]:
    """Le repertoire est un PARAMETRE, jamais une globale substituee — meme
    raison que dans les deux autres verrous du front : un `monkeypatch` qui rate
    sa cible laisse les tests de dents verts sur un repertoire vide."""
    base = base or WEB
    if not base.exists():
        return []
    return sorted(
        p
        for p in base.rglob("*.css")
        if not (set(p.parts) & IGNORES) and p.name != JETONS
    )


# --- Le depot est propre ------------------------------------------------------


@pytest.mark.parametrize(
    ("regle", "quoi"),
    [
        (couleurs, "couleur"),
        (durees, "duree"),
        (longueurs_hors_grille, "longueur hors de la grille de 4 px"),
        (tailles_hors_echelle, "taille de texte hors de l'echelle"),
    ],
)
def test_aucune_valeur_de_design_hors_du_fichier_de_jetons(regle, quoi: str) -> None:
    fautifs = {
        p.relative_to(RACINE).as_posix(): trouves
        for p in feuilles()
        if (trouves := regle(p.read_text(encoding="utf-8", errors="ignore")))
    }
    assert not fautifs, (
        f"{quoi} ecrite en clair hors de `{JETONS}` — le systeme visuel doit "
        "avoir une seule source :\n"
        + "\n".join(f"  {f} : {sorted(t)}" for f, t in sorted(fautifs.items()))
    )


def jetons_de_duree(texte: str) -> dict[str, int]:
    """Les durees declarees, en millisecondes, quel que soit le nom du jeton.

    Le motif ne cible PAS un prefixe. Une premiere version ne lisait que
    `--duree-*` : le jour ou une temporisation est arrivee sous un autre nom,
    elle echappait au plafond comme a la neutralisation, sans que rien ne le
    dise. Un verrou qui ne garde que les noms qu'on a prevus ne garde rien —
    c'est la liste ecrite a la main, deplacee dans une expression reguliere.
    """
    return {
        nom: int(float(valeur) * (1000 if unite == "s" else 1))
        for nom, valeur, unite in re.findall(
            r"(--[\w-]+):\s*(\d+(?:\.\d+)?)(m?s)\s*;", sans_commentaires(texte)
        )
    }


# Une BOUCLE n'est pas une revelation. Un indicateur indetermine doit tourner
# assez lentement pour se lire, donc au-dessus du plafond ; le plafond, lui,
# protege les transitions et les apparitions, celles qu'on subit a chaque geste.
# L'exemption est nommee par un prefixe plutot que par une liste de jetons, pour
# qu'elle reste une categorie et ne devienne pas une porte de sortie.
PREFIXE_BOUCLE = "--boucle-"


REDUIT = r"@media\s*\(prefers-reduced-motion:\s*reduce\s*\)\s*\{.*\}"


def declarations(texte: str) -> tuple[str, str]:
    """Separe les declarations NOMINALES du bloc `prefers-reduced-motion`.

    **La separation est le test, pas une commodite.** La premiere version lisait
    le fichier entier : le bloc reduit redeclare chaque duree a `0ms`, donc
    c'est ce zero qui l'emportait, et un jeton porte a 240 ms passait le plafond
    sans etre vu. La mutation l'a montre — elle a survecu.

    C'est le corpus degenere du projet, deplace dans un analyseur : deux
    populations melangees dans une meme lecture, et la seconde masquant la
    premiere.
    """
    sans = sans_commentaires(texte)
    bloc = re.search(REDUIT, sans, flags=re.S)
    return re.sub(REDUIT, "", sans, flags=re.S), bloc.group(0) if bloc else ""


def test_aucune_animation_ne_depasse_200_ms() -> None:
    """Le plafond est une decision, pas une habitude.

    Une animation qu'on remarque est trop longue : elle lie un etat au suivant,
    elle n'est pas regardee. Le plafond ne se verifie pas a l'oeil — 240 ms et
    180 ms sont indiscernables sur une capture, et se distinguent tres bien a
    l'usage.
    """
    nominales, _ = declarations((WEB / JETONS).read_text(encoding="utf-8"))
    durees_declarees = jetons_de_duree(nominales)
    assert durees_declarees, "aucune duree lue : le motif ne trouve plus les jetons"
    trop_longues = {
        n: v
        for n, v in durees_declarees.items()
        if v > 200 and not n.startswith(PREFIXE_BOUCLE)
    }
    assert not trop_longues, f"au-dessus du plafond de 200 ms : {trop_longues}"


def test_l_exemption_des_boucles_NE_dispense_pas_du_reste() -> None:
    """Les deux moities de l'exemption, parce qu'une exemption dont on ne teste
    que le cote permissif finit par tout justifier.

    Cote permissif : une boucle a le droit de durer. Cote restrictif : elle doit
    quand meme s'arreter sous `prefers-reduced-motion` — une animation
    perpetuelle est justement le pire cas pour qui a demande le calme — et un
    jeton qui n'est pas une boucle n'est pas dispense pour autant.
    """
    assert PREFIXE_BOUCLE.startswith("--"), "l'exemption porte sur un prefixe de jeton"

    nominales, bloc = declarations((WEB / JETONS).read_text(encoding="utf-8"))
    boucles = {n for n in jetons_de_duree(nominales) if n.startswith(PREFIXE_BOUCLE)}
    assert boucles, "aucune boucle declaree : l'exemption ne garde rien"
    neutralisees = {n for n, v in jetons_de_duree(bloc).items() if v == 0}
    assert boucles <= neutralisees, "une boucle doit s'arreter comme le reste"


def test_chaque_duree_tombe_a_zero_sous_prefers_reduced_motion() -> None:
    """La liste des durees neutralisees est DERIVEE, jamais recopiee.

    Verifier qu'un bloc `prefers-reduced-motion` existe ne dit rien de ce qu'il
    contient — presence contre contenu, le mecanisme que ce projet a paye six
    fois. Ce qu'il faut garder, c'est qu'AUCUNE duree n'y manque : une cinquieme
    ajoutee demain et oubliee ici rouvrirait une animation a quelqu'un qui a
    demande qu'il n'y en ait pas, et rien ne le signalerait.
    """
    nominales, bloc = declarations((WEB / JETONS).read_text(encoding="utf-8"))
    assert bloc, "aucun bloc `prefers-reduced-motion` dans le fichier de jetons"

    neutralisees = {n for n, v in jetons_de_duree(bloc).items() if v == 0}
    manquantes = set(jetons_de_duree(nominales)) - neutralisees
    assert not manquantes, f"durees jamais remises a zero : {sorted(manquantes)}"


def test_les_deux_lectures_de_duree_SE_SEPARENT() -> None:
    """Les deux tests precedents ne doivent pas lire la meme chose.

    S'ils lisaient tous deux le fichier entier, le zero du bloc reduit
    masquerait la valeur nominale — c'est exactement ce qui est arrive. Le
    corpus de ce test est choisi pour que les deux grandeurs different : une
    duree nominale non nulle, la meme a zero dans le bloc.
    """
    nominales, bloc = declarations(
        ":root { --duree-x: 180ms; }\n"
        "@media (prefers-reduced-motion: reduce) { :root { --duree-x: 0ms; } }"
    )
    assert jetons_de_duree(nominales) == {"--duree-x": 180}, "la valeur nominale"
    assert jetons_de_duree(bloc) == {"--duree-x": 0}, "et sa neutralisation"


def test_le_balayage_voit_bien_des_feuilles() -> None:
    """Un mauvais chemin rendrait le verrou muet — vert pour la mauvaise raison,
    ce qui est indistinguable de vert pour la bonne."""
    assert feuilles(), "aucune feuille de style balayee dans web/src"


def test_le_fichier_de_jetons_est_EXCLU_et_existe() -> None:
    """L'exclusion doit porter sur un fichier reel.

    Si `theme.css` etait renomme, l'exclusion ne designerait plus rien : le
    verrou signalerait alors chaque jeton du systeme, deviendrait invivable, et
    « un audit qui crie au loup est desactive dans la semaine ».
    """
    assert (WEB / JETONS).exists(), f"`{JETONS}` introuvable"
    assert (WEB / JETONS) not in feuilles(), "le fichier de jetons doit etre exclu"
    assert couleurs((WEB / JETONS).read_text(encoding="utf-8")), (
        "le fichier de jetons doit bien contenir les couleurs en clair — sinon "
        "elles sont ailleurs"
    )


# --- Le verrou a des dents ----------------------------------------------------


@pytest.mark.parametrize(
    ("regle", "contenu", "pourquoi"),
    [
        (couleurs, ".x { color: #f3f3f3; }", "une sixieme couleur en hex"),
        (couleurs, ".x { background: rgb(20 20 20); }", "la meme, en rgb"),
        (couleurs, ".x { border-color: white; }", "la meme, par son nom"),
        (durees, ".x { transition: opacity 300ms ease; }", "une duree au-dessus de 200 ms"),
        (durees, ".x { animation: a 0.4s; }", "la meme, en secondes"),
        (longueurs_hors_grille, ".x { padding: 7px; }", "une longueur hors grille"),
        (longueurs_hors_grille, ".x { margin: 1.5rem; }", "une longueur sans pas commun"),
        (tailles_hors_echelle, ".x { font-size: 14px; }", "une sixieme taille de texte"),
        (tailles_hors_echelle, ".x { font-size: 0.9rem; }", "la meme, en rem"),
    ],
)
def test_le_verrou_attrape_une_valeur_en_dur(regle, contenu: str, pourquoi: str) -> None:
    assert regle(contenu), pourquoi


def test_le_verrou_attrape_une_valeur_cachee_dans_un_fichier_quelconque(
    tmp_path: Path,
) -> None:
    """Les dents du balayage lui-meme, pas seulement des motifs.

    Une feuille ajoutee demain a cote de `styles.css` doit etre vue. Le
    repertoire est passe en parametre, donc le test exerce le vrai chemin.
    """
    faux = tmp_path / "src"
    faux.mkdir()
    (faux / "autre.css").write_text(".x { color: #abcdef; }", encoding="utf-8")

    trouvees = {p: couleurs(p.read_text(encoding="utf-8")) for p in feuilles(faux)}
    assert trouvees and all(trouvees.values())


def test_le_verrou_ne_crie_pas_au_loup() -> None:
    """Ce qui doit passer sans discussion.

    Sans ces cas, le verrou refuserait la feuille telle qu'elle doit s'ecrire —
    des jetons, des largeurs de grille sur le pas, et les rares valeurs qui
    n'ont pas d'echelle.
    """
    propre = """
    /* un commentaire qui cite #1f6f5c et 180ms sans les appliquer */
    .x {
      padding: var(--pas-8) var(--pas-16);
      grid-template-columns: 56px minmax(160px, 2fr);
      width: 100%;
      opacity: 0.72;
      font-size: var(--taille-13);
      transition: background var(--duree-survol) var(--sortie);
      outline-offset: calc(-1 * var(--marque));
    }
    """
    assert not couleurs(propre), "une couleur citee dans un commentaire"
    assert not durees(propre), "une duree citee dans un commentaire"
    assert not longueurs_hors_grille(propre), "des largeurs de grille sur le pas"
    assert not tailles_hors_echelle(propre), "une taille de texte prise au systeme"
