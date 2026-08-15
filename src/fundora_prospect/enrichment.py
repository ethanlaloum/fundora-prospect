"""Enrichissement par SIREN via `recherche-entreprises.api.gouv.fr`.

**Perimetre strict : deux signaux.**

1. **Le statut administratif de la societe cedante** — l'usage prioritaire.
   Active, la tresorerie de cession est encore au bilan : c'est le prospect.
   Cessee, le cash est descendu aux associes et la personne morale n'existe
   plus. Ce seul champ vaut plus que tout le reste de l'enrichissement.
2. **Le code APE**, qui rend le critere secteur techniquement operant.

Pas d'effectif, pas de forme juridique, **pas de dirigeants** : la reponse de
l'API en contient (noms, prenoms, annees de naissance), ils sont hors perimetre
et sont supprimes des la capture des fixtures. Le modele ci-dessous ne peut pas
les porter, ce qu'un test verifie.

**Regle de degradation : un lead sans enrichissement reste un lead valide.**
Aucune fonction de ce module ne leve. Toute panne — connexion, HTTP 500,
timeout, JSON invalide, SIREN introuvable — rend un `Enrichissement` de statut
`INCONNU` portant son motif. Le pipeline continue, le breakdown explique.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from fundora_prospect.http import creer_client
from fundora_prospect.models import StatutEntreprise

RECHERCHE_ENTREPRISES = "https://recherche-entreprises.api.gouv.fr/search"

# L'API documente 7 requetes par seconde. Le cache disque absorbe les
# repetitions ; cet intervalle protege les appels frais.
INTERVALLE_MINIMAL_S = 0.15

TIMEOUT_S = 5.0

_dernier_appel = 0.0


@dataclass(frozen=True)
class Enrichissement:
    """Les deux signaux du perimetre, et le motif de ce qu'on n'a pas obtenu.

    Aucun champ nominatif : le perimetre exclut les dirigeants, et ce qui n'est
    pas dans le modele ne peut pas fuiter dans un export.
    """

    siren: str
    statut: StatutEntreprise
    code_ape: str | None = None
    section_ape: str | None = None
    code_ape_naf25: str | None = None
    motif: str = ""

    @property
    def exploitable(self) -> bool:
        return self.statut is StatutEntreprise.ACTIVE


def siren_valide(brut: str | None) -> bool:
    return bool(brut) and len(str(brut)) == 9 and str(brut).isdigit()


def projeter(charge: dict[str, Any], *, siren_demande: str | None) -> Enrichissement:
    """Transforme la reponse brute en `Enrichissement`. Ne leve jamais.

    `siren_demande` sert a verifier que l'API a bien rendu l'entreprise
    demandee : c'est un moteur de recherche plein texte, il peut rendre autre
    chose. Sans ce controle on enrichirait un lead avec le statut d'une societe
    sans rapport.
    """
    resultats = charge.get("results") or []
    if not resultats:
        return Enrichissement(
            siren=siren_demande or "",
            statut=StatutEntreprise.INCONNU,
            motif="SIREN introuvable dans la base entreprises",
        )

    premier = resultats[0]
    siren_rendu = str(premier.get("siren") or "")

    if siren_demande is not None and siren_rendu != siren_demande:
        return Enrichissement(
            siren=siren_demande,
            statut=StatutEntreprise.INCONNU,
            motif=(
                f"la reponse ne correspond pas au SIREN demande "
                f"(demande {siren_demande}, rendu {siren_rendu or 'aucun'})"
            ),
        )

    if str(premier.get("statut_diffusion") or "O") != "O":
        return Enrichissement(
            siren=siren_rendu,
            statut=StatutEntreprise.NON_DIFFUSIBLE,
            motif="entreprise non diffusible : opposition INSEE explicite, non exploitee",
        )

    etat = str(premier.get("etat_administratif") or "")
    if etat == "A":
        statut, motif = StatutEntreprise.ACTIVE, "societe active : tresorerie de cession au bilan"
    elif etat == "C":
        statut, motif = (
            StatutEntreprise.CESSEE,
            "societe cessee : le produit de cession est descendu aux associes",
        )
    else:
        statut, motif = (
            StatutEntreprise.INCONNU,
            f"etat administratif non reconnu : {etat!r}",
        )

    return Enrichissement(
        siren=siren_rendu,
        statut=statut,
        code_ape=premier.get("activite_principale"),
        section_ape=premier.get("section_activite_principale"),
        code_ape_naf25=premier.get("activite_principale_naf25"),
        motif=motif,
    )


def _throttle() -> None:
    global _dernier_appel
    ecoule = time.monotonic() - _dernier_appel
    if ecoule < INTERVALLE_MINIMAL_S:
        time.sleep(INTERVALLE_MINIMAL_S - ecoule)
    _dernier_appel = time.monotonic()


def enrichir(siren: str | None, *, client: httpx.Client | None = None) -> Enrichissement:
    """Enrichit un SIREN. **Ne leve jamais, ne rend jamais None.**

    Une seule tentative : en cas d'echec le lead reste valide sans
    enrichissement, ce qui est preferable a une cascade de retries qui
    ralentirait tout le pipeline pour un signal secondaire.
    """
    identifiant = str(siren or "")
    if not siren_valide(identifiant):
        return Enrichissement(
            siren=identifiant,
            statut=StatutEntreprise.INCONNU,
            motif="SIREN absent ou mal forme : aucun appel emis",
        )

    propre = client is None
    client = client or creer_client(timeout=TIMEOUT_S)
    try:
        _throttle()
        reponse = client.get(RECHERCHE_ENTREPRISES, params={"q": identifiant, "per_page": 1})
        if reponse.status_code != 200:
            return Enrichissement(
                siren=identifiant,
                statut=StatutEntreprise.INCONNU,
                motif=f"API entreprises indisponible (HTTP {reponse.status_code})",
            )
        return projeter(reponse.json(), siren_demande=identifiant)
    except (httpx.HTTPError, ValueError) as exc:
        return Enrichissement(
            siren=identifiant,
            statut=StatutEntreprise.INCONNU,
            motif=f"API entreprises injoignable : {type(exc).__name__}",
        )
    finally:
        if propre:
            client.close()
