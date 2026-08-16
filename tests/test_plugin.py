"""Structure du plugin Claude Code.

**`skills/`, `hooks/` et `agents/` vont a la RACINE du plugin, jamais dans
`.claude-plugin/`.** Seul `plugin.json` y va. C'est l'erreur la plus frequente,
et elle echoue SILENCIEUSEMENT : le plugin se charge, mais les competences et
les hooks sont ignores. Un test vaut mieux qu'une relecture.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[1]


# --- Le piege d'arborescence ---------------------------------------------------


# Les deux seuls manifestes qui ont leur place dans `.claude-plugin/`.
# `marketplace.json` s'y ajoute parce que le depot est son propre marketplace :
# `/plugin install <chemin>` n'existe pas, l'installation passe forcement par
# `/plugin marketplace add`.
MANIFESTES_AUTORISES = {"plugin.json", "marketplace.json"}

# Ce qui ne doit JAMAIS s'y trouver. C'est le vrai piege : place ici, le
# contenu est ignore en silence — le plugin se charge, les competences non.
DOSSIERS_INTERDITS_DANS_CLAUDE_PLUGIN = ("skills", "hooks", "agents", "commands")


def test_claude_plugin_ne_contient_que_des_manifestes() -> None:
    contenu = {p.name for p in (RACINE / ".claude-plugin").iterdir()}
    intrus = contenu - MANIFESTES_AUTORISES
    assert not intrus, (
        f"`.claude-plugin/` ne doit contenir que {sorted(MANIFESTES_AUTORISES)}, "
        f"trouve en plus : {sorted(intrus)}"
    )
    assert "plugin.json" in contenu


@pytest.mark.parametrize("interdit", DOSSIERS_INTERDITS_DANS_CLAUDE_PLUGIN)
def test_aucun_dossier_de_composants_dans_claude_plugin(interdit: str) -> None:
    """L'erreur la plus frequente, et elle echoue SILENCIEUSEMENT."""
    assert not (RACINE / ".claude-plugin" / interdit).exists(), (
        f"{interdit}/ est dans .claude-plugin/ — il doit etre a la RACINE du plugin. "
        "Place ici, il est ignore sans message d'erreur."
    )


@pytest.mark.parametrize("dossier", ["skills", "hooks"])
def test_les_dossiers_sont_a_la_racine_pas_dans_claude_plugin(dossier: str) -> None:
    assert (RACINE / dossier).is_dir(), f"{dossier}/ doit exister a la racine"
    assert not (RACINE / ".claude-plugin" / dossier).exists(), (
        f"{dossier}/ ne doit PAS etre dans .claude-plugin/ — echec silencieux"
    )


def test_aucun_dossier_commands_legacy() -> None:
    """`commands/` est un format legacy : on n'en cree pas."""
    assert not (RACINE / "commands").exists()


# --- Manifestes ----------------------------------------------------------------


def test_plugin_json_est_valide() -> None:
    manifeste = json.loads((RACINE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifeste["name"] == "fundora-prospect"
    assert manifeste["version"]
    assert len(manifeste["description"]) > 60


def test_mcp_json_pointe_le_serveur() -> None:
    charge = json.loads((RACINE / ".mcp.json").read_text(encoding="utf-8"))
    serveurs = charge["mcpServers"]
    assert "fundora-prospect" in serveurs
    commande = serveurs["fundora-prospect"]["command"]
    assert "CLAUDE_PLUGIN_ROOT" in commande, "le chemin doit etre relatif au plugin"
    assert commande.endswith("fundora-prospect-mcp")


def test_hooks_json_declare_le_pretooluse() -> None:
    charge = json.loads((RACINE / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entrees = charge["hooks"]["PreToolUse"]
    assert entrees, "aucun hook PreToolUse declare"
    matcher = entrees[0]["matcher"]
    for outil in ("WebFetch", "Bash"):
        assert outil in matcher, f"{outil} doit etre surveille"
    commande = entrees[0]["hooks"][0]["command"]
    assert "CLAUDE_PLUGIN_ROOT" in commande
    assert commande.endswith("whitelist_domaines.py")


def test_le_script_du_hook_existe_et_est_executable() -> None:
    script = RACINE / "hooks" / "whitelist_domaines.py"
    assert script.is_file()
    assert os.stat(script).st_mode & stat.S_IXUSR, "le hook doit etre executable"
    assert script.read_text(encoding="utf-8").startswith("#!")


# --- Competences ---------------------------------------------------------------


@pytest.mark.parametrize("nom", ["scan-liquidity-events", "score-lead"])
def test_chaque_skill_a_un_frontmatter_exploitable(nom: str) -> None:
    """La description du frontmatter est ce qui declenche la competence : c'est
    du prompt, pas de la documentation."""
    fichier = RACINE / "skills" / nom / "SKILL.md"
    assert fichier.is_file(), f"{fichier} manquant"

    texte = fichier.read_text(encoding="utf-8")
    assert texte.startswith("---\n"), "frontmatter YAML manquant"
    entete = yaml.safe_load(texte.split("---")[1])

    assert entete["name"] == nom
    assert len(entete["description"]) > 100, "description trop courte pour declencher"
    assert "quand" in entete["description"].lower(), (
        "la description doit dire QUAND utiliser la competence"
    )


def test_la_competence_de_recherche_donne_l_exemple_de_la_demo() -> None:
    texte = (RACINE / "skills" / "scan-liquidity-events" / "SKILL.md").read_text(encoding="utf-8")
    assert '"06"' in texte, "le format du departement doit etre explicite"
    assert "search_liquidity_events" in texte


def test_les_competences_rappellent_le_cadrage() -> None:
    """Trois choses qu'un modele ne doit jamais dire de travers."""
    scan = (RACINE / "skills" / "scan-liquidity-events" / "SKILL.md").read_text(encoding="utf-8")
    assert "cedante" in scan.lower() or "cedant" in scan.lower()
    assert "liste d'appel" in scan.lower(), "l'outil n'est pas un carnet d'adresses"

    score = (RACINE / "skills" / "score-lead" / "SKILL.md").read_text(encoding="utf-8")
    assert "dire d'expert" in score.lower(), "le score n'est pas une prediction"


# --- Demo ----------------------------------------------------------------------


def test_la_demo_est_une_seule_commande_executable() -> None:
    demo = RACINE / "demo.sh"
    assert demo.is_file()
    assert os.stat(demo).st_mode & stat.S_IXUSR
    texte = demo.read_text(encoding="utf-8")
    # Les trois actes : le pipeline, le hook, le transport.
    assert "ACTE 1" in texte and "ACTE 2" in texte and "ACTE 3" in texte
    assert "linkedin" in texte.lower(), "le domaine de demo doit etre evocateur"


# --- Marketplace ---------------------------------------------------------------


def test_marketplace_json_est_valide() -> None:
    charge = json.loads(
        (RACINE / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert charge["name"] == "fundora"
    assert charge["owner"]["name"]
    assert len(charge["plugins"]) == 1


def test_le_marketplace_pointe_la_racine_du_depot() -> None:
    """Le depot EST le plugin : la source pointe sur sa propre racine."""
    charge = json.loads(
        (RACINE / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert charge["plugins"][0]["source"] == "."


def test_le_nom_du_plugin_est_identique_dans_les_deux_manifestes() -> None:
    """Une divergence rendrait `plugin install <nom>@fundora` introuvable."""
    plugin = json.loads((RACINE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads(
        (RACINE / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert marketplace["plugins"][0]["name"] == plugin["name"]


def _versions_declarees() -> dict[str, str]:
    """Les QUATRE endroits ou la version du plugin est ecrite.

    Les deux manifestes ne suffisent pas. `pyproject.toml` decide de la version
    du paquet, et `__version__` est ce que le serveur MCP annonce au client dans
    `serverInfo.version` — c'est la seule des quatre qu'un tiers voit a
    l'execution. Une divergence est donc visible de l'exterieur.

    Mesure du 2026-08-16 : les manifestes portaient 0.2.0, `pyproject.toml` et
    `__version__` etaient restes a 0.1.0. Le serveur MCP annoncait 0.1.0 pendant
    que le cache des plugins l'indexait sous 0.2.0. Les deux tests d'egalite de
    l'epoque ne comparaient que les manifestes entre eux : ils passaient.
    """
    import tomllib

    from fundora_prospect import __version__

    plugin = json.loads((RACINE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads(
        (RACINE / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    pyproject = tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))

    return {
        "plugin.json": plugin["version"],
        "marketplace.json": marketplace["plugins"][0]["version"],
        "pyproject.toml": pyproject["project"]["version"],
        "__version__": __version__,
    }


def test_la_version_est_identique_dans_les_quatre_sources() -> None:
    versions = _versions_declarees()
    distinctes = set(versions.values())
    assert len(distinctes) == 1, f"versions divergentes : {versions}"


# --- Lancement du serveur MCP hors du depot -----------------------------------


def _copier_plugin_sans_venv(destination: Path) -> Path:
    """Copie le plugin comme le ferait une installation, MAIS sans `.venv`.

    C'est la situation reelle d'un tiers : le depot versionne ne contient
    aucun environnement virtuel.
    """
    import shutil

    shutil.copytree(
        RACINE,
        destination,
        ignore=shutil.ignore_patterns(
            ".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache"
        ),
    )
    assert not (destination / ".venv").exists()
    return destination


def test_la_commande_de_mcp_json_repond_sans_venv_dans_l_arborescence(tmp_path) -> None:
    """LE test qui manquait en Phase 4.

    On ne verifie pas qu'un chemin existe : on lance la commande exacte lue
    dans `.mcp.json`, depuis une copie du plugin PRIVEE de `.venv`, placee
    dans un repertoire arbitraire — et on exige un vrai handshake MCP.

    Le defaut precedent (`${CLAUDE_PLUGIN_ROOT}/.venv/bin/...`) passait tous
    les tests de l'epoque et ne resolvait sur aucune machine tierce.
    """
    import os
    import shutil
    import subprocess
    import sys

    racine_copie = _copier_plugin_sans_venv(tmp_path / "plugin")

    charge = json.loads((racine_copie / ".mcp.json").read_text(encoding="utf-8"))
    modele = charge["mcpServers"]["fundora-prospect"]["command"]
    commande = modele.replace("${CLAUDE_PLUGIN_ROOT}", str(racine_copie))
    assert Path(commande).is_file(), f"{commande} n'existe pas dans la copie"

    # `FUNDORA_PYTHON` designe l'interpreteur qui porte les dependances. Sans
    # lui, le wrapper chercherait sur le PATH — ce qui marche aussi, mais
    # dependrait de la machine de test.
    env = dict(os.environ, FUNDORA_PYTHON=sys.executable)
    env.pop("PYTHONPATH", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    poignee = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
        '{"protocolVersion":"2024-11-05","capabilities":{},'
        '"clientInfo":{"name":"test","version":"1"}}}\n'
    )
    resultat = subprocess.run(
        [commande],
        input=poignee,
        capture_output=True,
        text=True,
        cwd=tmp_path,  # repertoire arbitraire, sans rapport avec le plugin
        env=env,
        timeout=60,
        check=False,
    )

    assert '"jsonrpc"' in resultat.stdout, (
        f"pas de reponse MCP.\nstdout: {resultat.stdout[:400]}\nstderr: {resultat.stderr[:600]}"
    )
    reponse = json.loads(resultat.stdout.splitlines()[0])
    assert reponse["id"] == 1
    assert "capabilities" in reponse["result"]
    assert reponse["result"]["serverInfo"]["name"] == "fundora-prospect"

    shutil.rmtree(racine_copie, ignore_errors=True)


def test_le_wrapper_echoue_en_nommant_la_reparation(tmp_path) -> None:
    """Sans interpreteur utilisable, le message doit dire quoi taper.

    Un serveur MCP qui meurt en silence est indiagnosticable depuis Claude
    Code : on ne voit qu'un « Connection closed ».
    """
    import os
    import subprocess

    faux = tmp_path / "python-sans-dependances"
    faux.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    faux.chmod(0o755)

    resultat = subprocess.run(
        [str(RACINE / "bin" / "fundora-prospect-mcp")],
        input="",
        capture_output=True,
        text=True,
        env=dict(os.environ, FUNDORA_PYTHON=str(faux)),
        timeout=60,
        check=False,
    )

    assert resultat.returncode != 0
    message = resultat.stderr
    assert "aucun interpreteur" in message.lower()
    for attendu in ("httpx", "pydantic", "mcp", "pip install", "FUNDORA_PYTHON"):
        assert attendu in message, f"le message doit mentionner {attendu!r}"


def test_mcp_json_ne_suppose_aucun_venv() -> None:
    """Garde-fou de regression : le chemin ne doit plus jamais citer `.venv`."""
    texte = (RACINE / ".mcp.json").read_text(encoding="utf-8")
    assert ".venv" not in texte, (
        "`.mcp.json` ne doit pas dependre d'un venv — il n'est pas versionne "
        "et n'existe pas dans une installation tierce"
    )
    assert "bin/fundora-prospect-mcp" in texte
