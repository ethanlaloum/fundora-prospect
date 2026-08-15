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


def test_la_version_est_identique_dans_les_deux_manifestes() -> None:
    plugin = json.loads((RACINE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads(
        (RACINE / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert marketplace["plugins"][0]["version"] == plugin["version"]
