"""Enrichissement par SIREN via recherche-entreprises.api.gouv.fr.

Perimetre strict : deux signaux, le statut administratif et le code APE.
Pas d'effectif, pas de forme juridique, pas de dirigeants — ces derniers sont
supprimes a la capture, jamais stockes.

Regle de degradation : **un lead sans enrichissement reste un lead valide.**
L'API peut etre muette, lente ou changer ; le pipeline continue et le motif
apparait dans le breakdown.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from fundora_prospect.enrichment import (
    Enrichissement,
    enrichir,
    projeter,
)
from fundora_prospect.models import StatutEntreprise

FIXTURES = Path(__file__).parent / "fixtures"


def reponses() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "enrichissement_reponses.json").read_text(encoding="utf-8"))


def premiere_avec(etat: str) -> dict[str, Any]:
    for charge in reponses():
        if charge["results"] and charge["results"][0].get("etat_administratif") == etat:
            return charge
    pytest.skip(f"aucune fixture avec etat_administratif={etat}")


# --- Projection de la reponse ------------------------------------------------


def test_societe_active_est_projetee_correctement() -> None:
    enr = projeter(premiere_avec("A"), siren_demande=None)
    assert enr.statut is StatutEntreprise.ACTIVE
    assert enr.code_ape
    assert enr.section_ape
    assert enr.motif


def test_societe_cessee_est_detectee() -> None:
    """Radiee : le cash est descendu aux associes, la personne morale n'existe
    plus. Ce n'est pas un prospect degrade, c'est un non-prospect."""
    enr = projeter(premiere_avec("C"), siren_demande=None)
    assert enr.statut is StatutEntreprise.CESSEE


def test_siren_introuvable_donne_un_statut_inconnu() -> None:
    vide = next(c for c in reponses() if not c["results"])
    enr = projeter(vide, siren_demande="000000000")
    assert enr.statut is StatutEntreprise.INCONNU
    assert enr.code_ape is None
    assert "introuvable" in enr.motif.lower()


def test_entreprise_non_diffusible_est_ecartee() -> None:
    """Opposition INSEE explicite : on ne l'exploite pas."""
    charge = premiere_avec("A")
    modifiee = json.loads(json.dumps(charge))
    modifiee["results"][0]["statut_diffusion"] = "P"
    enr = projeter(modifiee, siren_demande=None)
    assert enr.statut is StatutEntreprise.NON_DIFFUSIBLE
    assert "diffusib" in enr.motif.lower()
    assert "insee" in enr.motif.lower()


def test_la_section_ape_est_lue_et_non_derivee() -> None:
    """L'API sert `section_activite_principale` : la deriver du code serait
    reimplementer une table de correspondance pour rien."""
    enr = projeter(premiere_avec("A"), siren_demande=None)
    assert enr.section_ape is not None
    assert len(enr.section_ape) == 1
    assert enr.section_ape.isalpha()


def test_le_code_naf25_est_conserve_a_part() -> None:
    """Une transition de nomenclature est en cours : on garde les deux codes
    plutot que d'en choisir un et de se tromper."""
    enr = projeter(premiere_avec("A"), siren_demande=None)
    assert enr.code_ape_naf25 is not None
    assert enr.code_ape is not None
    # Les deux codes coexistent comme champs distincts : aucun n'ecrase l'autre.
    assert {"code_ape", "code_ape_naf25"} <= set(Enrichissement.__dataclass_fields__)


def test_aucune_donnee_personnelle_dans_le_resultat() -> None:
    """Le perimetre exclut les dirigeants. Le modele ne doit pas pouvoir les
    porter, meme si l'API les renvoie."""
    champs = set(Enrichissement.__dataclass_fields__)
    assert not champs & {"dirigeants", "siege", "adresse", "nom", "prenom"}


# --- Degradation : l'API ne repond pas ---------------------------------------


def _client(transport: httpx.BaseTransport) -> httpx.Client:
    return httpx.Client(transport=transport)


class TransportEnPanne(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("API injoignable", request=request)


class TransportErreur500(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"erreur": "indisponible"})


class TransportLent(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("trop lent", request=request)


class TransportJsonInvalide(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ceci n'est pas du json")


@pytest.mark.parametrize(
    "transport",
    [TransportEnPanne(), TransportErreur500(), TransportLent(), TransportJsonInvalide()],
    ids=["connexion", "http_500", "timeout", "json_invalide"],
)
def test_l_api_muette_ne_fait_jamais_echouer_l_enrichissement(
    transport: httpx.BaseTransport,
) -> None:
    """Un lead sans enrichissement reste un lead valide."""
    enr = enrichir("852872563", client=_client(transport))
    assert enr.statut is StatutEntreprise.INCONNU
    assert enr.code_ape is None
    assert enr.motif, "le motif doit expliquer pourquoi l'enrichissement a echoue"


def test_siren_invalide_n_appelle_meme_pas_l_api() -> None:
    """Inutile de consommer du quota pour un SIREN mal forme."""

    class TransportSentinelle(httpx.BaseTransport):
        appele = False

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            type(self).appele = True
            return httpx.Response(200, json={"total_results": 0, "results": []})

    sentinelle = TransportSentinelle()
    enr = enrichir("12345", client=_client(sentinelle))
    assert enr.statut is StatutEntreprise.INCONNU
    assert not TransportSentinelle.appele


def test_enrichir_retourne_toujours_un_enrichissement() -> None:
    """Jamais None, jamais d'exception : le type de retour est un contrat."""
    for siren in ("852872563", "", "abc", "000000000"):
        enr = enrichir(siren, client=_client(TransportEnPanne()))
        assert isinstance(enr, Enrichissement)


def test_la_reponse_ne_correspondant_pas_au_siren_demande_est_rejetee() -> None:
    """L'API fait de la recherche plein texte : elle peut rendre une autre
    entreprise. Sans ce controle, on enrichirait un lead avec le statut
    d'une societe qui n'a rien a voir."""
    charge = premiere_avec("A")
    enr = projeter(charge, siren_demande="999999999")
    assert enr.statut is StatutEntreprise.INCONNU
    assert "correspond" in enr.motif.lower()
