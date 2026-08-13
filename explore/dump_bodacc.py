"""Script JETABLE d'exploration de l'API BODACC (Phase 0).

Objectif : comprendre la donnee avant d'ecrire la moindre ligne de `src/`.
Ce fichier n'est importe par rien, n'est pas teste, et sera supprime a la fin
du projet. Il ne doit contenir aucune logique qu'on veut garder.

Trois etapes :
  1. Structure du dataset : liste des champs exposes par l'API.
  2. Anatomie d'une annonce de vente/cession : arbre complet des cles, y compris
     les sous-objets encodes en JSON-string.
  3. Taux de presence du prix de cession sur un echantillon reel PACA.
     C'est LE chiffre qui conditionne la viabilite du projet.

Usage :
    .venv/bin/python explore/dump_bodacc.py [--sample 400]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

# --- Whitelist (contrainte non negociable 2) ---------------------------------
# Meme dans un script jetable : tout appel hors de ce domaine leve.
ALLOWED_HOSTS = frozenset({"bodacc-datadila.opendatasoft.com"})

DATASET = "annonces-commerciales"
BASE = f"https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/{DATASET}"

# Provence-Alpes-Cote d'Azur
PACA_DEPTS = ["04", "05", "06", "13", "83", "84"]

# Les dumps bruts contiennent des donnees personnelles reelles (noms, adresses).
# Ils sont ecrits HORS du depot : la protection ne doit pas dependre du
# .gitignore, qui protege du commit mais pas d'une archive ou d'un partage
# d'ecran du repertoire de travail.
OUT_DIR = Path.home() / ".cache" / "fundora-prospect"


def get(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET avec verification de la whitelist avant emission de la requete."""
    host = urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        raise RuntimeError(f"Domaine non autorise : {host!r}. Autorises : {sorted(ALLOWED_HOSTS)}")
    resp = httpx.get(url, params=params, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


# --- Etape 1 : structure du dataset ------------------------------------------


def dump_dataset_fields() -> list[str]:
    meta = get(BASE)
    fields = meta.get("fields", [])
    print(f"\n{'=' * 78}\n1. CHAMPS DU DATASET '{DATASET}' ({len(fields)} champs)\n{'=' * 78}")
    names = []
    for f in fields:
        name = f.get("name", "?")
        names.append(name)
        print(f"  {name:<32} {f.get('type', '?'):<10} {f.get('label', '')}")
    return names


def dump_facets(facet: str) -> None:
    """Valeurs possibles d'un champ a facettes : sert a trouver le bon filtre."""
    data = get(f"{BASE}/facets", params={"facet": facet})
    print(f"\n--- Valeurs de '{facet}' ---")
    for group in data.get("facets", []):
        for item in group.get("facets", []):
            print(f"  {item.get('name'):<40} {item.get('count'):>10,}")


# --- Etape 2 : anatomie d'une annonce ----------------------------------------


def maybe_json(value: Any) -> Any:
    """L'API encode certains sous-objets en JSON-string. On les deplie."""
    if isinstance(value, str):
        s = value.strip()
        if s.startswith(("{", "[")):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return value
    return value


def walk(node: Any, prefix: str, acc: dict[str, list[Any]]) -> None:
    node = maybe_json(node)
    if isinstance(node, dict):
        for k, v in node.items():
            walk(v, f"{prefix}.{k}" if prefix else k, acc)
    elif isinstance(node, list):
        for item in node[:3]:
            walk(item, f"{prefix}[]", acc)
    else:
        acc[prefix].append(node)


def describe_structure(records: list[dict[str, Any]]) -> None:
    print(f"\n{'=' * 78}\n2. ANATOMIE DES ANNONCES DE VENTE/CESSION (n={len(records)})\n{'=' * 78}")
    acc: dict[str, list[Any]] = defaultdict(list)
    for rec in records:
        walk(rec, "", acc)

    for path in sorted(acc):
        values = [v for v in acc[path] if v not in (None, "")]
        fill = f"{len(values)}/{len(records)}"
        example = ""
        if values:
            ex = str(values[0])
            example = ex if len(ex) <= 90 else ex[:87] + "..."
        print(f"  {path:<46} {fill:>8}  {example}")


def dump_raw(records: list[dict[str, Any]], n: int) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "annonces_brutes.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  [{len(records)} annonces brutes ecrites dans {path} — gitignore]")

    for rec in records[:n]:
        print(f"\n--- ANNONCE BRUTE {rec.get('id')} ---")
        printable = {k: maybe_json(v) for k, v in rec.items() if v not in (None, "", [])}
        print(json.dumps(printable, ensure_ascii=False, indent=2))


# --- Etape 3 : taux de presence du prix ---------------------------------------

# Volontairement large et naif : on veut mesurer la PRESENCE d'un montant,
# pas encore le parser proprement (c'est le travail de la Phase 1).
MONTANT_RE = re.compile(
    r"(\d[\d\s .,]{2,})\s*(?:€|EUR\b|euros?\b)",
    re.IGNORECASE,
)


def haystack(rec: dict[str, Any]) -> str:
    """Concatene tout le texte de l'annonce ou un prix pourrait se cacher."""
    parts: list[str] = []

    def collect(node: Any) -> None:
        node = maybe_json(node)
        if isinstance(node, dict):
            for v in node.values():
                collect(v)
        elif isinstance(node, list):
            for v in node:
                collect(v)
        elif isinstance(node, str):
            parts.append(node)

    collect(rec)
    return " | ".join(parts)


def measure_price_coverage(records: list[dict[str, Any]]) -> None:
    print(f"\n{'=' * 78}\n3. TAUX DE PRESENCE D'UN MONTANT (n={len(records)}, PACA)\n{'=' * 78}")

    with_amount = 0
    field_hits: Counter[str] = Counter()
    samples: list[tuple[str, str]] = []

    for rec in records:
        text = haystack(rec)
        m = MONTANT_RE.search(text)
        if m:
            with_amount += 1
            if len(samples) < 12:
                start = max(0, m.start() - 70)
                samples.append((rec.get("id", "?"), text[start : m.end() + 20].replace("\n", " ")))
        # ou le montant apparait-il, champ par champ
        for key, value in rec.items():
            if MONTANT_RE.search(haystack({key: value})):
                field_hits[key] += 1

    pct = 100 * with_amount / len(records) if records else 0
    print(
        f"\n  Annonces contenant au moins un montant : {with_amount}/{len(records)} ({pct:.1f} %)"
    )

    print("\n  Champs porteurs du montant :")
    for field, count in field_hits.most_common():
        print(f"    {field:<40} {count:>5} ({100 * count / len(records):.1f} %)")

    print("\n  Extraits (contexte autour du montant detecte) :")
    for rec_id, snippet in samples:
        print(f"    [{rec_id}] ...{snippet}...")


# --- Recuperation -------------------------------------------------------------


def fetch_records(where: str, total: int, order_by: str = "dateparution DESC") -> list[dict]:
    """Pagine l'API (limit max 100 par requete)."""
    out: list[dict[str, Any]] = []
    while len(out) < total:
        page = get(
            f"{BASE}/records",
            params={
                "where": where,
                "limit": min(100, total - len(out)),
                "offset": len(out),
                "order_by": order_by,
            },
        )
        results = page.get("results", [])
        if not out:
            print(f"  total_count API = {page.get('total_count'):,}")
        if not results:
            break
        out.extend(results)
    return out


# --- Etape 4 : echantillon non biaise sur 12 mois -----------------------------

# Le prix apparait sous une forme tres reguliere. On la capture ici pour
# estimer le volume ; le parsing robuste (devises, formats, apports partiels)
# reste le travail de la Phase 1.
PRIX_STIPULE_RE = re.compile(
    r"prix\s+stipul[ée]\s+de\s+([\d\s .,]+?)\s*(euros?|EUR|F|francs?)\b",
    re.IGNORECASE,
)


def to_float(raw: str) -> float | None:
    s = raw.strip().replace(" ", "").replace(" ", "").replace("\xa0", "")
    s = s.replace(",", ".") if s.count(",") == 1 and s.count(".") == 0 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def sample_12_months(per_month: int) -> list[dict[str, Any]]:
    """Echantillon reparti sur 12 mois glissants, pour eviter le biais d'un
    ordre par date decroissante qui ne ramene qu'une seule parution."""
    from datetime import date

    today = date.today()
    depts = " OR ".join(f'numerodepartement="{d}"' for d in PACA_DEPTS)
    out: list[dict[str, Any]] = []
    print(f"\n{'=' * 78}\n4. ECHANTILLON REPARTI SUR 12 MOIS (PACA)\n{'=' * 78}")

    for i in range(12):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        start = f"{y:04d}-{m:02d}-01"
        end_y, end_m = (y + 1, 1) if m == 12 else (y, m + 1)
        end = f"{end_y:04d}-{end_m:02d}-01"
        where = (
            f'familleavis="vente" AND ({depts}) '
            f"AND dateparution >= date'{start}' AND dateparution < date'{end}'"
        )
        page = get(f"{BASE}/records", params={"where": where, "limit": per_month})
        results = page.get("results", [])
        print(f"  {start}  total_count={page.get('total_count'):>6,}  echantillon={len(results)}")
        out.extend(results)
    return out


def analyse_12_months(records: list[dict[str, Any]]) -> None:
    print(f"\n  --- Repartition (n={len(records)}) ---")
    for field in ("typeavis_lib", "publicationavis"):
        counts = Counter(r.get(field) for r in records)
        print(f"\n  {field} :")
        for value, count in counts.most_common(8):
            print(f"    {str(value):<52} {count:>5} ({100 * count / len(records):.1f} %)")

    cats: Counter[str] = Counter()
    for rec in records:
        acte = maybe_json(rec.get("acte")) or {}
        vente = acte.get("vente") if isinstance(acte, dict) else None
        if isinstance(vente, dict):
            cats[str(vente.get("categorieVente"))] += 1
    print("\n  acte.vente.categorieVente :")
    for value, count in cats.most_common(10):
        print(f"    {value:<52} {count:>5} ({100 * count / len(records):.1f} %)")

    montants: list[float] = []
    sans_prix = 0
    for rec in records:
        m = PRIX_STIPULE_RE.search(haystack(rec))
        value = to_float(m.group(1)) if m else None
        if value is None:
            sans_prix += 1
        else:
            montants.append(value)

    n = len(records)
    print(f"\n  --- Prix extrait par le motif 'prix stipule de X' (n={n}) ---")
    print(f"    extrait          : {len(montants):>5} ({100 * len(montants) / n:.1f} %)")
    print(f"    non extrait      : {sans_prix:>5} ({100 * sans_prix / n:.1f} %)")
    if montants:
        montants.sort()

        def pct(p: float) -> float:
            return montants[min(len(montants) - 1, int(p * len(montants)))]

        print(f"    min / med / max  : {montants[0]:,.0f} / {pct(0.5):,.0f} / {montants[-1]:,.0f}")
        print(f"    p90 / p99        : {pct(0.90):,.0f} / {pct(0.99):,.0f}")
        for seuil in (0, 1, 10_000, 100_000, 200_000, 500_000):
            k = sum(1 for v in montants if v > seuil)
            print(f"    > {seuil:>9,} EUR : {k:>5} ({100 * k / n:.1f} % de l'echantillon)")


def as_personnes(node: Any) -> list[dict[str, Any]]:
    """`listeprecedentproprietaire.personne` est tantot un objet, tantot une liste."""
    node = maybe_json(node) or {}
    if not isinstance(node, dict):
        return []
    p = node.get("personne")
    if isinstance(p, dict):
        return [p]
    if isinstance(p, list):
        return [x for x in p if isinstance(x, dict)]
    return []


def analyse_cedants(records: list[dict[str, Any]]) -> None:
    """Le prospect n'est pas l'annonceur (l'acheteur) mais le PRECEDENT
    proprietaire. On mesure si on peut l'identifier et l'enrichir."""
    print(f"\n{'=' * 78}\n5. QUI EST LE CEDANT ? (n={len(records)})\n{'=' * 78}")

    stats: Counter[str] = Counter()
    avec_siren_pp = 0
    exemples: list[str] = []

    for rec in records:
        personnes = as_personnes(rec.get("listeprecedentproprietaire"))
        if not personnes:
            stats["aucun precedent proprietaire"] += 1
            continue
        if len(personnes) > 1:
            stats["cedants multiples (indivision)"] += 1
        for p in personnes:
            type_p = p.get("typePersonne")
            siren = (p.get("numeroImmatriculation") or {}).get("numeroIdentification")
            if type_p == "pp":
                stats["personne physique (prospect direct)"] += 1
                if siren:
                    avec_siren_pp += 1
                if len(exemples) < 5:
                    nom = f"{p.get('nom', '?')} {p.get('prenom', '')}".strip()
                    exemples.append(f"pp  {nom:<34} siren={siren or '-'}")
            elif type_p == "pm":
                stats["personne morale (cedant societe)"] += 1
                if len(exemples) < 5:
                    exemples.append(
                        f"pm  {str(p.get('denomination'))[:34]:<34} siren={siren or '-'}"
                    )
            else:
                stats[f"typePersonne={type_p!r}"] += 1

    for label, count in stats.most_common():
        print(f"    {label:<44} {count:>5} ({100 * count / len(records):.1f} %)")
    pp = stats["personne physique (prospect direct)"]
    if pp:
        print(f"\n    dont personnes physiques avec SIREN exploitable : {avec_siren_pp}/{pp}")
    print("\n  Exemples (donnees publiques BODACC, non commitees) :")
    for line in exemples:
        print(f"    {line}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=400, help="taille de l'echantillon etape 3")
    parser.add_argument("--raw", type=int, default=2, help="nb d'annonces brutes affichees")
    parser.add_argument("--per-month", type=int, default=100, help="echantillon mensuel etape 4")
    args = parser.parse_args()

    dump_dataset_fields()
    dump_facets("familleavis_lib")

    depts = " OR ".join(f'numerodepartement="{d}"' for d in PACA_DEPTS)
    where = f'familleavis="vente" AND ({depts})'
    print(f"\n  Filtre : {where}")

    records = fetch_records(where, args.sample)
    if not records:
        print("  AUCUN RESULTAT — le filtre est mauvais, voir les facettes ci-dessus.")
        return 1

    describe_structure(records[:50])
    dump_raw(records, args.raw)
    measure_price_coverage(records)

    annuel = sample_12_months(args.per_month)
    analyse_12_months(annuel)
    analyse_cedants(annuel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
