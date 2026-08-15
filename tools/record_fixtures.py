"""Capture des fixtures BODACC avec substitution AVANT ecriture disque.

Contrainte 4 : aucune donnee personnelle reelle ne doit jamais exister dans le
repertoire de travail. Le flux est donc : reponse API en memoire -> substitution
-> ecriture. Il n'y a pas d'etape intermediaire ou un fichier brut existerait,
meme temporairement, meme gitignore.

Les fixtures conservent la FORME de l'API (sous-objets encodes en JSON-string)
pour que les tests exercent le depliage reel, et non une structure pre-machee.

Usage :
    .venv/bin/python tools/record_fixtures.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_RACINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_RACINE), str(_RACINE / "src")]

from fundora_prospect.http import creer_client  # noqa: E402
from tools.vocabulaire import GABARITS, SUBSTITUTIONS, VALEURS_AUTORISEES  # noqa: E402

BASE = (
    "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1"
    "/catalog/datasets/annonces-commerciales"
)
PACA = ("04", "05", "06", "13", "83", "84")
DEPTS = " OR ".join(f'numerodepartement="{d}"' for d in PACA)
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


# --- Substitution -------------------------------------------------------------


def _choisir(valeur: str, options: tuple[str, ...]) -> str:
    """Choix deterministe : deux valeurs reelles distinctes restent distinctes,
    sans qu'on puisse remonter a l'originale."""
    graine = int(hashlib.sha256(valeur.encode("utf-8")).hexdigest()[:8], 16)
    return options[graine % len(options)]


def _descriptif_synthetique(texte: str) -> str | None:
    """Reconstruit `acte.descriptif` en ne gardant que les dates.

    La date d'acte est indispensable au garde de fraicheur du parser ; elle
    n'est pas une donnee personnelle. Tout le reste de la phrase (etude,
    notaire, lieu d'enregistrement) est jete.
    """
    dates = DATE_RE.findall(texte)
    if not dates:
        return None
    if len(dates) == 1:
        return f"Acte en date du {dates[0]}."
    return f"Acte en date du {dates[0]} enregistre le {dates[1]}."


def anonymiser(noeud: Any, chemin: str = "") -> Any:
    """Substitue en profondeur. Les sous-objets JSON-string sont deplies,
    traites, puis re-encodes pour preserver la forme de l'API."""
    if isinstance(noeud, str) and noeud.strip()[:1] in "{[":
        try:
            interne = json.loads(noeud)
        except json.JSONDecodeError:
            pass
        else:
            return json.dumps(anonymiser(interne, chemin), ensure_ascii=False)

    if isinstance(noeud, dict):
        resultat: dict[str, Any] = {}
        for cle, valeur in noeud.items():
            sous_chemin = f"{chemin}.{cle}" if chemin else cle
            traite = anonymiser(valeur, sous_chemin)
            if traite is not None:
                resultat[cle] = traite
        return resultat

    if isinstance(noeud, list):
        return [anonymiser(element, chemin) for element in noeud]

    if not isinstance(noeud, str):
        return noeud

    normalise = chemin.replace("[]", "")

    if normalise == "acte.descriptif":
        return _descriptif_synthetique(noeud)
    if normalise in SUBSTITUTIONS:
        return SUBSTITUTIONS[normalise]

    feuille = normalise.rsplit(".", 1)[-1]
    if feuille in VALEURS_AUTORISEES:
        return _choisir(noeud, VALEURS_AUTORISEES[feuille])

    return noeud


# --- Selection des cas --------------------------------------------------------


def deplier(valeur: Any) -> Any:
    if isinstance(valeur, str) and valeur.strip()[:1] in "{[":
        try:
            return json.loads(valeur)
        except json.JSONDecodeError:
            return valeur
    return valeur


def etablissements(rec: dict[str, Any]) -> list[dict[str, Any]]:
    noeud = deplier(rec.get("listeetablissements")) or {}
    if not isinstance(noeud, dict):
        return []
    e = noeud.get("etablissement")
    if isinstance(e, dict):
        return [e]
    return [x for x in e if isinstance(x, dict)] if isinstance(e, list) else []


def origines(rec: dict[str, Any]) -> list[str]:
    return [str(e["origineFonds"]) for e in etablissements(rec) if e.get("origineFonds")]


def personnes_precedentes(rec: dict[str, Any]) -> list[dict[str, Any]]:
    noeud = deplier(rec.get("listeprecedentproprietaire")) or {}
    if not isinstance(noeud, dict):
        return []
    p = noeud.get("personne")
    if isinstance(p, dict):
        return [p]
    return [x for x in p if isinstance(x, dict)] if isinstance(p, list) else []


def type_cedant(rec: dict[str, Any]) -> str:
    types = {p.get("typePersonne") for p in personnes_precedentes(rec)}
    if not types:
        return "absent"
    return "pp" if "pp" in types else ("pm" if "pm" in types else "autre")


# Chaque cas est un predicat sur l'annonce brute. Les fixtures doivent couvrir
# les cas limites du parser, pas un echantillon representatif.
CAS: dict[str, Any] = {
    "achat_cedant_pm": lambda r: (
        type_cedant(r) == "pm"
        and any("prix stipul" in o.lower() and "euro" in o.lower() for o in origines(r))
    ),
    "achat_cedant_pp": lambda r: (
        type_cedant(r) == "pp"
        and any("prix stipul" in o.lower() and "euro" in o.lower() for o in origines(r))
    ),
    "devise_francs": lambda r: any(
        re.search(r"francs?\b|FRF", o, re.IGNORECASE) for o in origines(r)
    ),
    "apport_en_nature": lambda r: any("valu" in o.lower() for o in origines(r)),
    "sans_cedant": lambda r: type_cedant(r) == "absent",
    "sans_prix": lambda r: (
        bool(origines(r))
        and not any(re.search(r"prix stipul|montant .valu", o, re.I) for o in origines(r))
    ),
    "sans_etablissement": lambda r: not etablissements(r),
    "cedants_multiples": lambda r: len(personnes_precedentes(r)) > 1,
    "multi_etablissements": lambda r: len(etablissements(r)) > 1,
    "format_nombre_exotique": lambda r: any(
        re.search(r"\d+[.\s]\d{3}[,.]\d{2}", o) for o in origines(r)
    ),
    # Cas MODAL en production, et pourtant le dernier couvert : une annonce
    # recente dont l'acte est datable. Sans lui, le garde de fraicheur et le
    # calcul de l'ecart acte -> parution ne sont jamais exerces de bout en bout.
    "acte_datable_recent": lambda r: (
        bool(re.search(r"[Aa]cte en date du \d{2}/\d{2}/\d{4}", str(deplier(r.get("acte")) or {})))
        and type_cedant(r) == "pm"
        and any("prix stipul" in o.lower() for o in origines(r))
    ),
}

MAX_PAR_CAS = 3


def rassembler(client: Any) -> list[dict[str, Any]]:
    """Constitue le vivier : PACA recent + requetes ciblees sur les cas rares."""
    vivier: dict[str, dict[str, Any]] = {}

    # `order_by` compte : sans lui l'API rend les annonces les plus anciennes,
    # et aucune fixture ne couvrirait le cas modal — une cession recente dont
    # l'acte est datable.
    requetes = [
        (f'familleavis="vente" AND ({DEPTS})', 400, "dateparution DESC"),
        (f'familleavis="vente" AND ({DEPTS})', 200, None),
        ('familleavis="vente" AND listeetablissements LIKE "francs"', 100, None),
        ('familleavis="vente" AND listeetablissements LIKE "FRF"', 50, None),
        ('familleavis="vente" AND listeetablissements LIKE "apport"', 100, None),
    ]
    for where, total, ordre in requetes:
        for offset in range(0, total, 100):
            params: dict[str, Any] = {"where": where, "limit": 100, "offset": offset}
            if ordre:
                params["order_by"] = ordre
            reponse = client.get(f"{BASE}/records", params=params)
            reponse.raise_for_status()
            resultats = reponse.json().get("results", [])
            if not resultats:
                break
            for rec in resultats:
                vivier[rec["id"]] = rec
    return list(vivier.values())


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with creer_client() as client:
        vivier = rassembler(client)
    print(f"vivier : {len(vivier)} annonces (en memoire, jamais ecrites brutes)")

    total = 0
    for nom, predicat in CAS.items():
        retenues = [r for r in vivier if predicat(r)][:MAX_PAR_CAS]
        if not retenues:
            print(f"  {nom:<24} AUCUNE ANNONCE — cas non couvert")
            continue
        anonymes = [anonymiser(r) for r in retenues]
        (FIXTURES / f"{nom}.json").write_text(
            json.dumps(anonymes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        total += len(anonymes)
        print(f"  {nom:<24} {len(anonymes)} annonce(s)")

    print(f"\n{total} fixtures ecrites dans {FIXTURES}")
    print("Gabarits declares :", ", ".join(sorted(GABARITS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
