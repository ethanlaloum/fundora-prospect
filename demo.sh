#!/bin/sh
# Demonstration end-to-end, en une commande :  ./demo.sh
#
# Quatre actes :
#   1. le pipeline complet sur donnees reelles
#   2. le hook PreToolUse barre l'AGENT
#   3. le transport HTTP barre le CODE
#   4. la provenance barre la SORTIE
#
# Les actes 2 et 3 sont indissociables : aucun des deux verrous ne suffit
# seul, et le montrer vaut mieux que de laisser croire l'inverse. L'acte 4
# est un verrou d'une autre nature — il ne barre pas une collecte, il barre
# une sortie — et tient volontairement en quelques lignes.

set -e
cd "$(dirname "$0")"

PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || { echo "venv absent — lancer d'abord : python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'"; exit 1; }

# La demo ne doit dependre d'aucun mode d'installation : elle tourne depuis un
# simple checkout, installe ou non. C'est une demo, elle n'a pas le droit de
# tomber devant un recruteur pour une histoire de sys.path.
PYTHONPATH="src:${PYTHONPATH:-}"
export PYTHONPATH

trait() { printf '\n%s\n' "────────────────────────────────────────────────────────────────────"; }

trait
echo "  ACTE 1 — le pipeline, sur donnees reelles"
echo "  « trouve-moi les cessions de plus de 300 k EUR dans le 06 sur 6 mois »"
trait

$PYTHON - <<'PY' 2>/dev/null
import logging
logging.disable(logging.INFO)
from fundora_prospect.mcp_server import search_liquidity_events

r = search_liquidity_events(departement="06", mois=6, montant_min=300_000, limite=5)
print(f"\n  {r['resume']}\n")
for i, lead in enumerate(r["leads"], 1):
    print(f"  {i}. {lead['score']:>5.1f}/100  {lead['cedant'][:40]}")
    print(f"       {lead['montant_eur']:>12,.0f} EUR   SIREN {lead['siren']}   "
          f"acte {lead['date_acte'] or 'non datable'}   {lead['statut_cedant']}")
    print(f"       {lead['url_publication']}")
if r["leads"]:
    print("\n  Detail du premier — chaque point est justifie :")
    for c in r["leads"][0]["breakdown"]:
        print(f"       {c['critere']:<12} {c['points']:>6.2f} / {c['poids']:<4.0f}  {c['motif'][:76]}")
PY

trait
echo "  ACTE 2 — le hook PreToolUse barre l'AGENT"
echo "  Ce que tenterait un commercial presse : aller chercher le dirigeant"
echo "  sur un reseau social."
trait

printf '%s' '{"tool_name":"WebFetch","tool_input":{"url":"https://www.linkedin.com/in/quelquun"}}' \
  | $PYTHON hooks/whitelist_domaines.py || echo "  [le hook a rendu le code $? : appel BLOQUE]"

trait
echo "  ACTE 3 — le transport HTTP barre le CODE"
echo "  Le hook ne voit pas une URL cachee dans un fichier .py."
echo "  Le transport, lui, verifie au moment d'ouvrir la connexion."
trait

$PYTHON - <<'PY'
from fundora_prospect.http import DomaineNonAutoriseError, creer_client

try:
    with creer_client(sans_cache=True) as client:
        client.get("https://www.linkedin.com/in/quelquun")
except DomaineNonAutoriseError as refus:
    print(f"\n  DomaineNonAutoriseError levee AVANT toute connexion :\n\n    {refus}\n")
PY

trait
echo "  Deux verrous, deux perimetres. Aucun des deux ne suffit seul :"
echo "    - le hook ne voit pas un httpx.get() enfoui dans un fichier"
echo "    - le transport ne voit pas un curl tape par l'agent"

trait
echo "  ACTE 4 — la provenance barre la SORTIE"
echo "  Les actes 2 et 3 barrent ce qui ENTRE. Celui-ci barre ce qui SORT."
trait

$PYTHON - <<'PY'
from datetime import date

from pydantic import ValidationError

from fundora_prospect import provenance
from fundora_prospect.models import Evaluation, LiquidityEvent, StatutEntreprise, TypeCedant

def evenement(url: str) -> LiquidityEvent:
    return LiquidityEvent(
        id="DEMO", date_parution=date.today(), date_acte=date.today(),
        departement="06", url_publication=url, montant_eur=420_000.0, devise="EUR",
        qualification="achat", retenu=True, cedant_denomination="CEDANT DEMO",
        cedant_type=TypeCedant.PERSONNE_MORALE, cedant_siren="852872563",
        statut_cedant=StatutEntreprise.ACTIVE,
    )

note = Evaluation(event_id="DEMO", classable=True, score=78.4)
lead = provenance.assembler(evenement("https://www.bodacc.fr/x/DEMO"), note)

print("\n  Les quatre champs que porte chaque lead (contrainte 3) :\n")
for cle, valeur in provenance.serialiser(lead)["provenance"].items():
    print(f"    {cle:<16} {str(valeur)[:88]}")

print("\n  Le meme lead, prive de son URL de publication :\n")
try:
    provenance.assembler(evenement(""), note)
except ValidationError as refus:
    print(f"    ValidationError : {refus.errors()[0]['msg'][:96]}")

print("\n  Un lead sans les quatre champs ne sort pas. Il n'est pas rendu")
print("  sans provenance, il est compte dans les refus avec son motif.\n")
PY

trait
