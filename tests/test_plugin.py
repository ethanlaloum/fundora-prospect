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

from fundora_prospect import mcp_server

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


# Statistiques de la mesure du 2026-08-17 — 06, six mois, > 300 k EUR,
# `limite=25`. Elles servent a REGENERER l'exemple de SKILL.md depuis le code.
_STATS_DE_REFERENCE = {
    "annonces_publiees": 668,
    "annonces_rapatriees": 600,
    "annonces_exploitables": 460,
    "sans_cedant_ou_illisibles": 140,
    "plafond_atteint": True,
    "candidats_avant_enrichissement": 116,
    "enrichis": 50,
    "candidats_non_enrichis": 66,
    "classables_parmi_les_enrichis": 49,
    "leads_rendus": 25,
    "ecartes": {
        "sous le montant minimum": 334,
        "apport": 6,
        "absent": 2,
        "acte trop ancien": 2,
        "societe cedante cessee": 1,
    },
}


def test_l_exemple_de_la_competence_est_le_vrai_format_de_sortie() -> None:
    """SKILL.md est du PROMPT, pas de la documentation : c'est lui qui dit au
    modele a quoi ressemble le resume et comment le presenter. Un exemple perime
    y est pire qu'ailleurs — il apprend au modele un format qui n'existe plus.

    Il en citait un date de deux renommages : « 458 annonces examinees, 5
    classables ». `annonces_examinees` avait disparu en Phase 3 bis, et
    `classables` a pris son referent le 2026-08-17. Aucun test ne le gardait,
    donc la derive a survecu aux deux corrections — quatrieme occurrence du
    mecanisme « un chiffre survit au changement de sa source ».

    Le test REGENERE l'exemple depuis `_resume` et exige l'egalite. Recopier a
    la main rouvrirait la meme porte : c'est la source qui doit produire
    l'exemple, pas la bonne volonte du relecteur.
    """
    attendu = mcp_server._resume(dict(_STATS_DE_REFERENCE))
    texte = (RACINE / "skills" / "scan-liquidity-events" / "SKILL.md").read_text(encoding="utf-8")

    # L'exemple est une citation markdown : on la reconstitue en une ligne.
    citation = " ".join(
        ligne.lstrip("> ").strip()
        for ligne in texte.splitlines()
        if ligne.startswith(">")
    ).strip()

    assert citation == attendu, (
        "l'exemple de SKILL.md a derive du format reel.\n"
        f"  dans SKILL.md : {citation}\n"
        f"  produit par _resume : {attendu}"
    )


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


def test_l_acte_synthetique_de_la_demo_se_declare_a_l_ecran() -> None:
    """L'acte 4 fabrique son `LiquidityEvent` a la main — il le faut, on ne peut
    pas compter sur le reseau pour livrer un lead casse. Mais l'ecran annonce
    « les quatre champs que porte CHAQUE lead » : sans mention, le spectateur
    croit voir un lead reel.

    La question a ete posee en direct — « peut-etre que la demo n'utilise pas
    l'API, tout est ecrit en dur ». Elle visait l'acte 1, qui est bien un appel
    reel ; mais elle est exacte pour l'acte 4. Un recruteur technique la posera
    aussi, et il vaut mieux que la reponse soit deja a l'ecran.
    """
    texte = (RACINE / "demo.sh").read_text(encoding="utf-8")
    acte4 = texte.split("ACTE 4", 1)[1]
    # La BANNIERE seule — les `echo` avant le premier bloc Python. Chercher dans
    # tout l'acte laissait la mutation passer : le mot figure aussi dans un
    # `print` du heredoc, et en retirer un exemplaire laissait l'autre verdir le
    # test. Ce qui compte est ce que le spectateur lit AVANT le resultat.
    banniere = acte4.split("$PYTHON", 1)[0].lower()
    assert "synthetique" in banniere, "l'acte 4 doit s'annoncer fabrique avant d'afficher"
    assert "reelles" in banniere, "et dire quels actes portent du reel"


def test_la_demo_dit_qu_elle_n_affiche_pas_tous_les_leads() -> None:
    """La demo enrichit a `limite` mais n'imprime qu'une poignee de leads :
    25 leads font 75 lignes, soit plusieurs ecrans.

    C'est une troncature d'AFFICHAGE, et elle tombe sous la meme regle que
    toutes les autres coupes du projet — « un tri en amont est un filtre », et
    son corollaire : le compte rendu doit dire la troncature. Le resume juste
    au-dessus annonce « 25 rendus » ; si l'ecran en montre 5 sans le dire, les
    deux nombres se contredisent sous les yeux du spectateur.

    Le test cherche un `print` qui porte LES DEUX nombres. Se contenter de
    verifier que les identifiants apparaissent quelque part ne mordait pas :
    ils survivent dans la decoupe `leads[:AFFICHES]` et dans l'affectation de
    `rendus`, donc supprimer l'affichage laissait le test vert. Ce qui compte
    n'est pas que le script connaisse l'ecart, c'est qu'il le dise.
    """
    texte = (RACINE / "demo.sh").read_text(encoding="utf-8")
    acte1 = texte.split("ACTE 1", 1)[1].split("ACTE 2", 1)[0]
    impressions = [
        ligne
        for ligne in acte1.splitlines()
        if "print(" in ligne or ligne.lstrip().startswith('f"')
    ]
    assert any("AFFICHES" in ligne and "rendus" in ligne for ligne in impressions), (
        "aucun print ne compare les leads affiches au nombre rendu"
    )


def test_l_acte_reel_de_la_demo_n_avale_pas_ses_erreurs() -> None:
    """`2>/dev/null` sur l'acte 1 masquait le bruit des logs — et avec lui un
    incident reseau. On verrait alors des chiffres plus faibles sans savoir
    pourquoi, dans le seul acte qui pretend mesurer le reel.

    Le filtre doit etre etroit : taire les logs, pas les erreurs.

    On ne regarde que les lignes de COMMANDE : la redirection est un fait
    d'execution, pas une chaine de caracteres. Chercher partout ferait echouer
    le test sur le commentaire qui explique le retrait — un test ne doit pas
    interdire de documenter sa propre raison d'etre.
    """
    texte = (RACINE / "demo.sh").read_text(encoding="utf-8")
    acte1 = texte.split("ACTE 1", 1)[1].split("ACTE 2", 1)[0]
    commandes = [
        ligne for ligne in acte1.splitlines() if not ligne.lstrip().startswith("#")
    ]
    assert not any("2>/dev/null" in ligne for ligne in commandes), (
        "l'acte 1 ne doit pas jeter sa sortie d'erreur"
    )


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


def _commande_de_mcp_json(racine_copie: Path) -> str:
    """La commande exacte lue dans `.mcp.json`, resolue sur la copie."""
    charge = json.loads((racine_copie / ".mcp.json").read_text(encoding="utf-8"))
    modele = charge["mcpServers"]["fundora-prospect"]["command"]
    commande = modele.replace("${CLAUDE_PLUGIN_ROOT}", str(racine_copie))
    assert Path(commande).is_file(), f"{commande} n'existe pas dans la copie"
    return commande


# Les binaires externes dont `bin/fundora-prospect-mcp` a besoin : `dirname`
# pour resoudre sa propre racine, `cat` pour imprimer le message d'echec. Tout
# le reste est un builtin de `sh`. Les lister ici permet de fabriquer un PATH
# qui contient le strict necessaire — et surtout AUCUN Python.
UTILITAIRES_DU_WRAPPER = ("dirname", "cat")


def _environnement_de_tiers(tmp_path: Path) -> dict[str, str]:
    """L'environnement d'un tiers qui vient de cloner : aucun Python utilisable.

    Trois variables sont retirees parce qu'un tiers ne les a pas :
    `FUNDORA_PYTHON` (l'echappatoire), `PYTHONPATH` et `VIRTUAL_ENV` (poses par
    le venv qui fait tourner pytest). Et le PATH est reduit a un repertoire qui
    ne contient que `dirname` et `cat` : `command -v python3` n'y trouve rien.

    Sans cette reduction, le test dependrait de la machine — sur une machine de
    developpement, un `python3` du PATH porte souvent les dependances, et le
    test passe pour une raison qui n'a rien a voir avec ce qu'il pretend
    verifier.
    """
    import os
    import shutil

    bac = tmp_path / "bin-sans-python"
    bac.mkdir(exist_ok=True)
    for utilitaire in UTILITAIRES_DU_WRAPPER:
        source = shutil.which(utilitaire)
        assert source, f"{utilitaire} introuvable — le wrapper ne peut pas tourner"
        cible = bac / utilitaire
        if not cible.exists():
            cible.symlink_to(source)

    env = dict(os.environ, PATH=str(bac))
    for variable in ("FUNDORA_PYTHON", "PYTHONPATH", "CLAUDE_PLUGIN_ROOT", "VIRTUAL_ENV"):
        env.pop(variable, None)

    # Le garde-fou du garde-fou : si un Python restait joignable, les deux
    # tests ci-dessous ne prouveraient plus rien.
    assert shutil.which("python3", path=str(bac)) is None
    return env


def _poser_le_venv_conventionnel(racine_copie: Path) -> Path:
    """Cree un vrai venv a `<racine>/.venv`, l'emplacement que cherche le wrapper.

    Le venv est cree sans pip — installer les dependances par le reseau dans un
    test unitaire serait lent et fragile. Elles sont rendues visibles par un
    `.pth` qui pointe le site-packages de l'interpreteur courant. Le resultat
    est un venv authentique : `bin/python` reel, `pyvenv.cfg` reel, et les trois
    dependances importables.
    """
    import subprocess
    import sys
    import sysconfig

    venv = racine_copie / ".venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)],
        capture_output=True,
        timeout=120,
        check=True,
    )
    site_packages = next(venv.glob("lib/python*/site-packages"))
    (site_packages / "dependances-du-test.pth").write_text(
        sysconfig.get_paths()["purelib"] + "\n", encoding="utf-8"
    )
    assert (venv / "bin" / "python").exists()
    return venv


POIGNEE_MCP = (
    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
    '{"protocolVersion":"2024-11-05","capabilities":{},'
    '"clientInfo":{"name":"test","version":"1"}}}\n'
)


def _exiger_un_handshake(resultat) -> None:
    assert '"jsonrpc"' in resultat.stdout, (
        f"pas de reponse MCP.\nstdout: {resultat.stdout[:400]}\nstderr: {resultat.stderr[:600]}"
    )
    reponse = json.loads(resultat.stdout.splitlines()[0])
    assert reponse["id"] == 1
    assert "capabilities" in reponse["result"]
    assert reponse["result"]["serverInfo"]["name"] == "fundora-prospect"


def test_un_tiers_sans_interprete_utilisable_obtient_un_echec_qui_se_repare(tmp_path) -> None:
    """Branche 3 de `trouver_interprete` : la recherche sur le PATH echoue.

    C'est la situation reelle constatee le 2026-08-16 : le serveur MCP du
    plugin installe repondait « Connection closed » a Claude Code parce
    qu'aucun Python du PATH ne portait `httpx`, `pydantic` et `mcp`, et que le
    cache du plugin n'a pas de `.venv`.

    Un serveur MCP qui meurt en silence est indiagnosticable depuis Claude
    Code : le message doit nommer les paquets manquants ET la commande a taper.
    """
    import shutil
    import subprocess

    racine_copie = _copier_plugin_sans_venv(tmp_path / "plugin")
    resultat = subprocess.run(
        [_commande_de_mcp_json(racine_copie)],
        input=POIGNEE_MCP,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=_environnement_de_tiers(tmp_path),
        timeout=120,
        check=False,
    )

    assert resultat.returncode != 0, "un echec doit se voir dans le code de sortie"
    assert '"jsonrpc"' not in resultat.stdout, "aucun handshake ne doit sortir"

    message = resultat.stderr
    assert "aucun interpreteur" in message.lower()
    for paquet in ("httpx", "pydantic", "mcp"):
        assert paquet in message, f"le message doit nommer le paquet manquant {paquet!r}"
    for reparation in ("pip install", "venv", "FUNDORA_PYTHON"):
        assert reparation in message, f"le message doit donner la reparation {reparation!r}"

    shutil.rmtree(racine_copie, ignore_errors=True)


def test_un_tiers_avec_le_venv_conventionnel_obtient_un_handshake(tmp_path) -> None:
    """Branche 2 de `trouver_interprete` : `<racine>/.venv/bin/python`.

    Meme environnement appauvri que le test precedent — pas de
    `FUNDORA_PYTHON`, pas de Python sur le PATH. La seule difference est le
    venv pose a l'emplacement conventionnel. Si le handshake passe ici et
    echoue au-dessus, c'est bien ce venv qui a ete trouve, et rien d'autre.
    """
    import shutil
    import subprocess

    racine_copie = _copier_plugin_sans_venv(tmp_path / "plugin")
    _poser_le_venv_conventionnel(racine_copie)

    resultat = subprocess.run(
        [_commande_de_mcp_json(racine_copie)],
        input=POIGNEE_MCP,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=_environnement_de_tiers(tmp_path),
        timeout=120,
        check=False,
    )

    _exiger_un_handshake(resultat)
    shutil.rmtree(racine_copie, ignore_errors=True)


def test_l_echappatoire_fundora_python_repond_hors_du_depot(tmp_path) -> None:
    """Branche 1 de `trouver_interprete` : la surcharge explicite.

    ATTENTION a ce que ce test ne prouve PAS. En posant `FUNDORA_PYTHON`, il se
    donne l'interpreteur qui porte les dependances : il valide le wrapper *a
    condition qu'on lui tende un interpreteur utilisable*. Il ne dit rien de la
    recherche sur le PATH, qui est la branche qu'emprunte reellement Claude
    Code — et qui a echoue en production le 2026-08-16 pendant que ce test
    etait vert.

    Le commentaire qui figurait ici affirmait que sans `FUNDORA_PYTHON` le
    wrapper « chercherait sur le PATH — ce qui marche aussi ». C'etait une
    garantie jamais mesuree, et fausse sur la machine de developpement. Un
    commentaire qui rassure sur une garantie non verifiee est pire que pas de
    commentaire : il decourage precisement le test qui manque.

    Les deux branches non couvertes ici le sont par les deux tests au-dessus.
    """
    import os
    import shutil
    import subprocess
    import sys

    racine_copie = _copier_plugin_sans_venv(tmp_path / "plugin")
    commande = _commande_de_mcp_json(racine_copie)

    env = dict(os.environ, FUNDORA_PYTHON=sys.executable)
    env.pop("PYTHONPATH", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    resultat = subprocess.run(
        [commande],
        input=POIGNEE_MCP,
        capture_output=True,
        text=True,
        cwd=tmp_path,  # repertoire arbitraire, sans rapport avec le plugin
        env=env,
        timeout=120,
        check=False,
    )

    _exiger_un_handshake(resultat)
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
