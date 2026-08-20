"""Aucune clef d'API dans le depot.

## Pourquoi ce verrou arrive maintenant

Jusqu'a la troisieme voie, le projet n'avait aucun secret : les deux APIs
publiques s'interrogent sans authentification. `api.anthropic.com` en demande
une, et une clef commitee une fois **reste exposee** — git conserve
l'historique, et la supprimer au commit suivant ne la retire pas du depot. La
seule protection utile intervient AVANT l'ecriture de l'objet, comme pour les
donnees personnelles.

## Une liste de FORMES, pas de valeurs

Chercher une clef connue ne garderait que celle-la. Les motifs decrivent la
**forme** des jetons — `sk-ant-…`, `sk-…`, un bloc de clef privee — et
attrapent donc ceux qu'on n'a pas anticipes. C'est le meme raisonnement que la
liste blanche des fixtures, applique dans l'autre sens : ici on ne peut pas
enumerer le legitime, alors on decrit l'interdit et on le fait large.

## Le hook execute ce fichier

`.githooks/pre-commit` lance ce test avec celui de l'anonymisation. Il reste
contournable par `--no-verify` : c'est un filet, la garantie est la suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent

# Ce qui n'est pas du code ecrit ici : environnements, caches, dependances.
IGNORES = {".venv", ".git", "node_modules", "dist", "__pycache__", ".pytest_cache",
           ".ruff_cache", ".vite"}

EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".json", ".toml", ".md", ".sh", ".yaml",
              ".yml", ".css", ".html", ".txt", ""}

# Les FORMES, pas les valeurs. Le premier motif est celui d'Anthropic ; les
# autres couvrent ce que le projet pourrait acquerir demain sans qu'on repense
# a ce fichier.
MOTIFS = {
    "clef Anthropic": re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    "clef generique sk-": re.compile(r"\bsk-[A-Za-z0-9]{32,}"),
    "jeton GitHub": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "clef privee": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    # Une affectation en dur, quelle que soit la forme du jeton. C'est le cas
    # qu'un motif de forme laisserait passer si le fournisseur changeait de
    # prefixe : `CLEF = "…"` est suspect independamment de ce qu'il y a dedans.
    # `["\']?` avant le separateur : en JSON la clef est elle-meme entre
    # guillemets (`"api_key": "…"`), et sans ce caractere optionnel le motif
    # ne voyait que la forme Python. Le cas a ete trouve par le test de dents.
    "clef assignee en dur": re.compile(
        r"""(?i)\b(?:api[_-]?key|secret[_-]?key|auth[_-]?token)["']?\s*[:=]\s*["'][A-Za-z0-9_\-]{20,}["']"""
    ),
}


def fichiers_du_depot(base: Path | None = None) -> list[Path]:
    """Le repertoire est un PARAMETRE — meme raison qu'ailleurs : un test de
    dents qui raterait sa cible serait vert sur un repertoire vide."""
    base = base or RACINE
    if not base.exists():
        return []
    return sorted(
        chemin
        for chemin in base.rglob("*")
        if chemin.is_file()
        and not (set(chemin.parts) & IGNORES)
        and chemin.suffix in EXTENSIONS
    )


def secrets_trouves(texte: str) -> list[str]:
    return [nom for nom, motif in MOTIFS.items() if motif.search(texte)]


# --- Le depot est propre --------------------------------------------------------


def test_aucune_clef_d_api_dans_le_depot() -> None:
    fautifs = {
        chemin.relative_to(RACINE).as_posix(): trouves
        for chemin in fichiers_du_depot()
        if (trouves := secrets_trouves(chemin.read_text(encoding="utf-8", errors="ignore")))
    }
    assert not fautifs, (
        "secret detecte — git conserve l'historique, une clef commitee reste "
        "exposee meme supprimee ensuite :\n"
        + "\n".join(f"  {f} : {sorted(t)}" for f, t in sorted(fautifs.items()))
    )


def test_le_balayage_voit_bien_des_fichiers() -> None:
    """Un mauvais chemin rendrait le verrou muet : vert pour la mauvaise raison,
    indistinguable d'un vert pour la bonne."""
    assert len(fichiers_du_depot()) > 50


def test_la_clef_se_lit_dans_l_environnement_et_nulle_part_ailleurs() -> None:
    """Le complement du balayage : la seule source de la clef est
    `ANTHROPIC_API_KEY`, lue par le SDK. Le front n'appelle jamais Anthropic —
    le navigateur ne parle qu'a `/api`."""
    agent = (RACINE / "src" / "fundora_prospect" / "agent.py").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" in agent, "le motif doit etre ecrit quelque part"
    assert "api_key=" not in agent, "la clef ne se passe pas en argument"

    web = [c for c in fichiers_du_depot(RACINE / "web" / "src")]
    for chemin in web:
        contenu = chemin.read_text(encoding="utf-8", errors="ignore")
        assert "anthropic" not in contenu.lower(), f"{chemin} parle a Anthropic"


# --- Le verrou a des dents --------------------------------------------------------
#
# Les chaines d'essai sont ASSEMBLEES, jamais ecrites en clair. Le premier jet
# les ecrivait telles quelles, et le verrou a signale son propre fichier de
# tests — justement. Exclure ce fichier du balayage aurait cree une cachette
# permanente pour un vrai secret ; assembler coute une concatenation.
PEM = "-----BEGIN " + "PRIVATE KEY-----"


@pytest.mark.parametrize(
    ("contenu", "pourquoi"),
    [
        ('CLEF = "sk-ant-api03-' + "a" * 40 + '"', "une clef Anthropic en dur"),
        ('export ANTHROPIC_API_KEY=sk-ant-' + "x" * 30, "une clef dans un script shell"),
        ('{"api_key": "' + "b" * 40 + '"}', "une clef dans un JSON de configuration"),
        (PEM + "\nMIIE\n", "une clef privee"),
        ('token = "ghp_' + "c" * 36 + '"', "un jeton GitHub"),
    ],
)
def test_le_verrou_attrape_un_secret(tmp_path: Path, contenu: str, pourquoi: str) -> None:
    """**Les dents.** Cinq formes, dont trois qu'aucun motif de prefixe seul
    n'attraperait."""
    (tmp_path / "fichier.py").write_text(contenu, encoding="utf-8")
    trouves = [
        nom
        for chemin in fichiers_du_depot(tmp_path)
        for nom in secrets_trouves(chemin.read_text(encoding="utf-8"))
    ]
    assert trouves, pourquoi


def test_le_verrou_ne_crie_pas_au_loup() -> None:
    """Un verrou qui signalerait du code ordinaire serait desactive dans la
    semaine. Le nom de la variable d'environnement, un exemple tronque et une
    URL doivent passer."""
    assert not secrets_trouves('cle = os.environ["ANTHROPIC_API_KEY"]')
    assert not secrets_trouves('# la clef a la forme sk-ant-...')
    assert not secrets_trouves('BASE = "https://api.anthropic.com"')
    assert not secrets_trouves('"id": "A20260151266"')
