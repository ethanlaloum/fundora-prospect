#!/usr/bin/env python3
"""Hook `PreToolUse` — barre les appels reseau de l'AGENT hors whitelist.

C'est le SECOND des deux verrous de la contrainte 2, et il ne remplace pas le
premier :

- **Le transport HTTP** (`fundora_prospect.http.TransportWhitelist`) barre le
  CODE. Un `httpx.get()` vers un domaine interdit leve avant d'ouvrir la
  connexion, quel que soit le chemin de code.
- **Ce hook** barre l'AGENT. Il intercepte les outils que Claude Code utilise —
  `WebFetch`, `WebSearch`, `Bash` — avant leur execution.

Aucun des deux ne suffit seul. Ce hook ne voit PAS un `httpx.get()` ecrit a
l'interieur d'un script Python lance par Bash : la requete part sans jamais
passer par la couche outil. Inversement, le transport ne voit pas un `curl`
tape par l'agent. C'est pourquoi la demonstration montre les deux.

Protocole : la charge du hook arrive en JSON sur stdin. Un code de sortie 2
bloque l'appel et remonte stderr a Claude.
"""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import urlparse

# Repris de `fundora_prospect.http.DOMAINES_AUTORISES`. Le hook doit fonctionner
# meme si le paquet n'est pas importable — il tourne dans l'environnement de
# Claude Code, pas forcement dans le venv du projet. Un test verifie que les
# deux listes sont identiques, pour que la duplication ne puisse pas deriver.
DOMAINES_AUTORISES = frozenset(
    {
        "bodacc-datadila.opendatasoft.com",
        "recherche-entreprises.api.gouv.fr",
    }
)

OUTILS_SURVEILLES = {"WebFetch", "WebSearch", "Bash"}

MOTIF_URL = re.compile(r"https?://[^\s'\"`|;)>]+", re.IGNORECASE)

# Commandes reseau qu'un raccourci pourrait employer sans URL complete.
MOTIF_COMMANDE_RESEAU = re.compile(
    r"\b(curl|wget|nc|ncat|telnet|ssh|scp|rsync|ftp)\b", re.IGNORECASE
)


def hotes_demandes(nom_outil: str, entree: dict) -> list[str]:
    """Hotes que l'appel d'outil cherche a joindre."""
    if nom_outil == "WebSearch":
        # Une recherche web ne designe aucun hote : elle sort du perimetre des
        # deux APIs autorisees par construction.
        if entree.get("query"):
            return ["<recherche web>"]
        return []

    texte = " ".join(
        str(valeur) for valeur in entree.values() if isinstance(valeur, str | int | float)
    )
    hotes = []
    for url in MOTIF_URL.findall(texte):
        hote = urlparse(url).hostname
        if hote:
            hotes.append(hote)

    if nom_outil == "Bash" and not hotes and MOTIF_COMMANDE_RESEAU.search(texte):
        hotes.append("<commande reseau sans URL lisible>")
    return hotes


def message_de_refus(hote: str) -> str:
    """Tient en une hauteur d'ecran, et cite la contrainte par son numero."""
    autorises = sorted(DOMAINES_AUTORISES)
    permis = f"\n{'':<23}".join(autorises)
    return (
        "\n"
        "  APPEL RESEAU REFUSE — contrainte 2 du projet\n"
        "\n"
        f"    domaine demande  : {hote}\n"
        f"    domaines permis  : {permis}\n"
        "\n"
        "  fundora-prospect ne collecte que des publications legales\n"
        "  obligatoires. Un CIF agree AMF ne peut pas exploiter une base\n"
        "  constituee autrement.\n"
        "\n"
        "  Aucune connexion n'a ete ouverte.\n"
    )


def examiner(charge: dict) -> str | None:
    """Rend le motif de refus, ou None si l'appel est autorise."""
    nom_outil = charge.get("tool_name", "")
    if nom_outil not in OUTILS_SURVEILLES:
        return None

    entree = charge.get("tool_input") or {}
    if not isinstance(entree, dict):
        return None

    for hote in hotes_demandes(nom_outil, entree):
        if hote not in DOMAINES_AUTORISES:
            return message_de_refus(hote)
    return None


def main() -> int:
    try:
        charge = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Un hook qui plante ne doit pas bloquer la session.
        return 0

    refus = examiner(charge if isinstance(charge, dict) else {})
    if refus is None:
        return 0

    print(refus, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
