"""Hook `PreToolUse` — le second verrou de la contrainte 2.

Ce hook barre l'AGENT ; le transport HTTP barre le CODE. Aucun des deux ne
suffit seul, et ces tests verrouillent aussi cette limite : le hook ne voit pas
un appel reseau ecrit a l'interieur d'un script Python.

Il doit etre demontrable en direct, donc le message de refus est teste comme un
livrable : longueur, mention de la contrainte, domaines cites.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from fundora_prospect.http import DOMAINES_AUTORISES

RACINE = Path(__file__).resolve().parents[1]
HOOK = RACINE / "hooks" / "whitelist_domaines.py"

sys.path.insert(0, str(RACINE / "hooks"))

from whitelist_domaines import (  # noqa: E402
    DOMAINES_AUTORISES as WHITELIST_HOOK,
)
from whitelist_domaines import (  # noqa: E402
    examiner,
    message_de_refus,
)

# Domaine de demonstration : ce qu'un commercial presse tenterait vraiment.
DOMAINE_DEMO = "www.linkedin.com"


def appel(nom_outil: str, entree: dict) -> dict:
    return {"tool_name": nom_outil, "tool_input": entree}


# --- La duplication de la whitelist ne doit pas deriver ----------------------


def test_la_whitelist_du_hook_est_identique_a_celle_du_code() -> None:
    """Le hook duplique la liste parce qu'il tourne dans l'environnement de
    Claude Code, ou le paquet n'est pas forcement importable. Ce test est ce
    qui empeche les deux copies de diverger."""
    assert WHITELIST_HOOK == DOMAINES_AUTORISES


# --- Refus -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outil", "entree"),
    [
        ("WebFetch", {"url": f"https://{DOMAINE_DEMO}/in/quelquun"}),
        ("WebFetch", {"url": "https://www.societe.com/societe/exemple.html"}),
        ("WebFetch", {"url": "https://www.pagesjaunes.fr/annuaire"}),
        ("Bash", {"command": f"curl -s https://{DOMAINE_DEMO}/api"}),
        ("Bash", {"command": "wget https://www.verif.com/liste.csv -O /tmp/x"}),
        ("WebSearch", {"query": "dirigeants boulangerie Marseille email"}),
    ],
)
def test_les_appels_hors_whitelist_sont_refuses(outil: str, entree: dict) -> None:
    assert examiner(appel(outil, entree)) is not None


def test_un_sous_domaine_ne_passe_pas() -> None:
    """La correspondance est exacte : un sous-domaine tiers serait une porte."""
    faux = "https://evil.bodacc-datadila.opendatasoft.com/records"
    assert examiner(appel("WebFetch", {"url": faux})) is not None


def test_un_domaine_autorise_en_userinfo_ne_trompe_pas() -> None:
    piege = "https://bodacc-datadila.opendatasoft.com@collecte.example/x"
    assert examiner(appel("WebFetch", {"url": piege})) is not None


def test_une_commande_reseau_sans_url_lisible_est_refusee() -> None:
    assert examiner(appel("Bash", {"command": "curl $CIBLE"})) is not None


# --- Autorisations -----------------------------------------------------------


@pytest.mark.parametrize("domaine", sorted(DOMAINES_AUTORISES))
def test_les_deux_domaines_du_projet_passent(domaine: str) -> None:
    assert examiner(appel("WebFetch", {"url": f"https://{domaine}/api/x"})) is None


def test_une_commande_sans_reseau_passe() -> None:
    assert examiner(appel("Bash", {"command": "pytest -q"})) is None


def test_les_outils_non_surveilles_passent() -> None:
    assert examiner(appel("Read", {"file_path": "/etc/hosts"})) is None
    assert examiner(appel("Edit", {"file_path": "x", "old_string": "http://a.b"})) is None


# --- Le message est un livrable de demo --------------------------------------


def test_le_message_tient_en_une_hauteur_d_ecran() -> None:
    """Un pavé qu'on scrolle en direct rate son effet."""
    lignes = message_de_refus(DOMAINE_DEMO).strip().splitlines()
    assert len(lignes) <= 14, f"{len(lignes)} lignes, trop long pour une demo"
    assert all(len(ligne) <= 80 for ligne in lignes)


def test_le_message_cite_la_contrainte_par_son_numero() -> None:
    """Le refus vient de la spec, pas d'un garde-fou improvise."""
    assert "contrainte 2" in message_de_refus(DOMAINE_DEMO).lower()


def test_le_message_nomme_le_domaine_refuse_et_les_domaines_permis() -> None:
    message = message_de_refus(DOMAINE_DEMO)
    assert DOMAINE_DEMO in message
    for domaine in DOMAINES_AUTORISES:
        assert domaine in message


def test_le_message_donne_la_raison_metier() -> None:
    message = message_de_refus(DOMAINE_DEMO).lower()
    assert "cif" in message and "amf" in message


# --- Le hook comme processus --------------------------------------------------


def _lancer(charge: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(charge),
        capture_output=True,
        text=True,
        check=False,
    )


def test_le_hook_sort_en_code_2_et_ecrit_sur_stderr() -> None:
    """Code 2 : Claude Code bloque l'appel et remonte stderr au modele."""
    resultat = _lancer(appel("WebFetch", {"url": f"https://{DOMAINE_DEMO}/x"}))
    assert resultat.returncode == 2
    assert "contrainte 2" in resultat.stderr.lower()
    assert resultat.stdout == ""


def test_le_hook_laisse_passer_en_code_0() -> None:
    resultat = _lancer(appel("WebFetch", {"url": "https://bodacc-datadila.opendatasoft.com/api"}))
    assert resultat.returncode == 0


def test_un_hook_casse_ne_bloque_pas_la_session() -> None:
    """Une charge illisible ne doit pas rendre Claude Code inutilisable."""
    resultat = subprocess.run(
        [sys.executable, str(HOOK)],
        input="ceci n'est pas du json",
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultat.returncode == 0


# --- La limite du hook, verrouillee par un test ------------------------------


def test_le_hook_attrape_une_url_en_clair_meme_dans_un_python_c() -> None:
    """Le hook lit tout le texte de la commande : une URL en clair est vue,
    meme enfouie dans un `python -c`."""
    script = "python -c \"import httpx; httpx.get('https://www.linkedin.com')\""
    assert examiner(appel("Bash", {"command": script})) is not None


def test_le_hook_ne_voit_PAS_une_url_cachee_dans_un_FICHIER() -> None:
    """LIMITE STRUCTURELLE, testee pour qu'elle reste vraie et visible.

    Le hook n'inspecte que l'appel d'outil. Si l'URL vit a l'interieur d'un
    fichier `.py`, la commande executee ne contient aucun domaine et le hook
    n'a rien a examiner. La requete part sans jamais passer par la couche
    outil.

    C'est LA raison pour laquelle le transport HTTP existe : lui verifie au
    moment d'ouvrir la connexion, donc il attrape ce cas. Pretendre que le
    hook protege tout serait une demo de vendeur — un recruteur technique
    verrait le trou avant nous.
    """
    assert examiner(appel("Bash", {"command": "python collecte_annuaire.py"})) is None, (
        "si ce test echoue un jour, c'est que le hook est devenu plus large — "
        "verifier alors que la documentation de la demo dit toujours vrai"
    )


def test_le_transport_lui_arrete_ce_que_le_hook_laisse_passer() -> None:
    """L'autre moitie de la demonstration : les deux verrous se completent."""
    import httpx

    from fundora_prospect.http import DomaineNonAutoriseError, creer_client

    with creer_client(sans_cache=True) as client, pytest.raises(DomaineNonAutoriseError):
        client.get(f"https://{DOMAINE_DEMO}/in/quelquun")
    assert httpx  # le client existe bien, ce n'est pas une erreur d'import
