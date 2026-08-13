"""Sonde JETABLE (Phase 0 bis) — deux questions ouvertes avant la Phase 1.

Q1. `origineFonds` peut-il citer une transaction ANTERIEURE plutot que la
    cession en cours ? Les montants en francs sont le revelateur : le franc a
    disparu en 2002, le dataset commence en 2008, donc un montant en francs
    ne PEUT PAS etre le prix de la cession publiee. Si de tels montants
    existent, alors le champ decrit parfois l'historique du fonds — et
    certains montants en euros sont faux de la meme facon.

Q2. Quelle part des annonces porte plusieurs etablissements valorises ?
    Sous 5 %, on marque ambigu ; au-dessus, il faut la somme conditionnelle.

Usage :
    .venv/bin/python explore/probe_origine_fonds.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from typing import Any
from urllib.parse import urlparse

import httpx

ALLOWED_HOSTS = frozenset({"bodacc-datadila.opendatasoft.com"})
BASE = (
    "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1"
    "/catalog/datasets/annonces-commerciales"
)
PACA_DEPTS = ["04", "05", "06", "13", "83", "84"]
DEPTS_CLAUSE = " OR ".join(f'numerodepartement="{d}"' for d in PACA_DEPTS)


def get(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if urlparse(url).hostname not in ALLOWED_HOSTS:
        raise RuntimeError("Domaine non autorise")
    r = httpx.get(url, params=params, timeout=60.0)
    r.raise_for_status()
    return r.json()


def unwrap(v: Any) -> Any:
    if isinstance(v, str) and v.strip()[:1] in "{[":
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v


def etablissements(rec: dict[str, Any]) -> list[dict[str, Any]]:
    node = unwrap(rec.get("listeetablissements")) or {}
    if not isinstance(node, dict):
        return []
    e = node.get("etablissement")
    if isinstance(e, dict):
        return [e]
    return [x for x in e if isinstance(x, dict)] if isinstance(e, list) else []


def origines(rec: dict[str, Any]) -> list[str]:
    return [str(e["origineFonds"]) for e in etablissements(rec) if e.get("origineFonds")]


def fetch(where: str, total: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while len(out) < total:
        page = get(
            f"{BASE}/records",
            params={"where": where, "limit": min(100, total - len(out)), "offset": len(out)},
        )
        res = page.get("results", [])
        if not res:
            break
        out.extend(res)
    return out


def count(where: str) -> int:
    return int(get(f"{BASE}/records", params={"where": where, "limit": 0})["total_count"])


# --- Q1 : montants en francs et transactions anterieures ---------------------

FRANCS_RE = re.compile(r"\b([\d\s.,]+)\s*(francs?|F\b|FRF)\b", re.IGNORECASE)
PRIX_RE = re.compile(r"prix\s+stipul[ée]\s+de\s+([\d\s.,]+?)\s*(euros?|EUR|francs?|F|FRF)\b", re.I)
ANTERIEUR_RE = re.compile(
    r"\b(pr[ée]c[ée]demment|ant[ée]rieur\w*|anciennement|initialement|"
    r"acquis\s+en\s+(?:19|20)\d{2}|depuis\s+(?:19|20)\d{2})\b",
    re.IGNORECASE,
)


def q1_francs() -> None:
    print(f"\n{'=' * 78}\nQ1. MONTANTS EN FRANCS DANS origineFonds\n{'=' * 78}")

    total_vente = count('familleavis="vente"')
    print(f"  Annonces `vente` dans le dataset (national, tout historique) : {total_vente:,}")

    # L'API indexe le texte : on cible directement les annonces citant "francs".
    for terme in ("francs", "FRF"):
        where = f'familleavis="vente" AND listeetablissements LIKE "{terme}"'
        try:
            n = count(where)
        except httpx.HTTPStatusError as exc:
            print(f"  [{terme}] requete refusee ({exc.response.status_code})")
            continue
        pct = 100 * n / total_vente if total_vente else 0
        print(f"  origineFonds citant '{terme}' : {n:,} ({pct:.4f} %)")
        if not n:
            continue
        for rec in fetch(where, 3):
            print(f"\n  --- {rec.get('id')} | parution {rec.get('dateparution')} ---")
            for txt in origines(rec):
                print(f"      origineFonds : {txt}")
                for m in PRIX_RE.finditer(txt):
                    print(f"        -> prix detecte : {m.group(1).strip()} {m.group(2)}")


def q1_anterieur(records: list[dict[str, Any]]) -> None:
    """Le champ decrit-il parfois autre chose que la transaction en cours ?"""
    print(f"\n{'-' * 78}\n  Indices de transaction anterieure (n={len(records)} annonces PACA)\n")

    multi_prix = 0
    anterieur = 0
    exemples: list[str] = []
    for rec in records:
        for txt in origines(rec):
            prix = PRIX_RE.findall(txt)
            if len(prix) > 1:
                multi_prix += 1
                if len(exemples) < 3:
                    exemples.append(f"[{rec.get('id')}] {txt}")
            if ANTERIEUR_RE.search(txt):
                anterieur += 1
                if len(exemples) < 3:
                    exemples.append(f"[{rec.get('id')}] {txt}")

    print(f"    origineFonds avec PLUSIEURS 'prix stipule'   : {multi_prix}")
    print(f"    origineFonds avec marqueur d'anteriorite     : {anterieur}")
    for ex in exemples:
        print(f"      {ex}")
    if not multi_prix and not anterieur:
        print("      (aucun) -> le champ decrit bien la transaction en cours")

    # Longueur du champ : un texte court ne peut pas raconter deux histoires.
    longueurs = [len(t) for rec in records for t in origines(rec)]
    if longueurs:
        longueurs.sort()
        print(
            f"\n    longueur origineFonds : min={longueurs[0]} "
            f"median={longueurs[len(longueurs) // 2]} max={longueurs[-1]}"
        )
        print(f"      le plus long : {max((t for r in records for t in origines(r)), key=len)}")


# --- Q2 : annonces multi-etablissements --------------------------------------


def q2_multi(records: list[dict[str, Any]]) -> None:
    barre = "=" * 78
    print(f"\n{barre}\nQ2. ANNONCES MULTI-ETABLISSEMENTS (n={len(records)}, PACA 12 mois)\n{barre}")

    nb_etabs: Counter[int] = Counter()
    nb_valorises: Counter[int] = Counter()
    partiels = 0
    for rec in records:
        etabs = etablissements(rec)
        nb_etabs[len(etabs)] += 1
        valorises = sum(1 for e in etabs if PRIX_RE.search(str(e.get("origineFonds", ""))))
        nb_valorises[valorises] += 1
        if len(etabs) > 1 and 0 < valorises < len(etabs):
            partiels += 1

    n = len(records)
    print("\n  Nombre d'etablissements par annonce :")
    for k in sorted(nb_etabs):
        print(f"    {k} etablissement(s) : {nb_etabs[k]:>5} ({100 * nb_etabs[k] / n:.1f} %)")

    multi = sum(v for k, v in nb_etabs.items() if k > 1)
    multi_val = sum(v for k, v in nb_valorises.items() if k > 1)
    for label, k in (
        ("Annonces a plusieurs etablissements", multi),
        ("Annonces a plusieurs prix valorises", multi_val),
        ("dont valorisation PARTIELLE", partiels),
    ):
        print(f"  {label:<42} {k:>5} ({100 * k / n:.1f} %)")
    print(f"\n  => seuil de decision : 5 % — mesure = {100 * multi_val / n:.1f} %")


def sample_12_months(per_month: int = 100) -> list[dict[str, Any]]:
    from datetime import date

    today = date.today()
    out: list[dict[str, Any]] = []
    for i in range(12):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        end_y, end_m = (y + 1, 1) if m == 12 else (y, m + 1)
        where = (
            f'familleavis="vente" AND ({DEPTS_CLAUSE}) '
            f"AND dateparution >= date'{y:04d}-{m:02d}-01' "
            f"AND dateparution < date'{end_y:04d}-{end_m:02d}-01'"
        )
        out.extend(get(f"{BASE}/records", params={"where": where, "limit": per_month})["results"])
    return out


def main() -> int:
    q1_francs()
    records = sample_12_months()
    q1_anterieur(records)
    q2_multi(records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
