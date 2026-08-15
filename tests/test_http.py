"""La whitelist de domaines (contrainte 2) est appliquee AU TRANSPORT.

Un `if` dans une fonction utilitaire se contourne par distraction : il suffit
d'ecrire un `httpx.get()` ailleurs. Au niveau transport, aucun chemin de code
du projet ne peut emettre une requete hors whitelist.

Ces tests n'ouvrent aucune connexion : le refus doit intervenir AVANT.
"""

from __future__ import annotations

import httpx
import pytest

from fundora_prospect.http import (
    DOMAINES_AUTORISES,
    DomaineNonAutoriseError,
    TransportWhitelist,
    creer_client,
)


class TransportSentinelle(httpx.BaseTransport):
    """Transport interne qui echoue si on l'atteint : prouve que le refus a eu
    lieu en amont, sans reseau."""

    def __init__(self) -> None:
        self.appels: list[httpx.URL] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.appels.append(request.url)
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def sentinelle() -> TransportSentinelle:
    return TransportSentinelle()


@pytest.fixture
def client(sentinelle: TransportSentinelle) -> httpx.Client:
    return httpx.Client(transport=TransportWhitelist(sentinelle))


def test_les_deux_domaines_de_la_spec_sont_autorises() -> None:
    attendus = frozenset({"bodacc-datadila.opendatasoft.com", "recherche-entreprises.api.gouv.fr"})
    assert attendus == DOMAINES_AUTORISES


@pytest.mark.parametrize(
    "url",
    [
        "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/x/records",
        "https://recherche-entreprises.api.gouv.fr/search?q=x",
    ],
)
def test_domaine_autorise_passe(client: httpx.Client, sentinelle: TransportSentinelle, url) -> None:
    assert client.get(url).status_code == 200
    assert len(sentinelle.appels) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://www.bodacc.fr/annonces",
        # sous-domaine non autorise : la correspondance est exacte, pas un suffixe
        "https://evil.bodacc-datadila.opendatasoft.com/",
        # domaine autorise place en userinfo pour tromper un parsing naif
        "https://bodacc-datadila.opendatasoft.com@evil.com/",
        # port different, hote non autorise
        "http://localhost:8080/",
    ],
)
def test_domaine_refuse_leve_avant_toute_connexion(
    client: httpx.Client, sentinelle: TransportSentinelle, url: str
) -> None:
    with pytest.raises(DomaineNonAutoriseError):
        client.get(url)
    assert sentinelle.appels == [], "le transport interne n'aurait pas du etre atteint"


def test_le_message_d_erreur_nomme_le_domaine_et_les_autorises(client: httpx.Client) -> None:
    """Le hook de la Phase 5 doit etre demontrable en live : le message compte."""
    with pytest.raises(DomaineNonAutoriseError) as exc:
        client.get("https://example.com/")
    message = str(exc.value)
    assert "example.com" in message
    assert "bodacc-datadila.opendatasoft.com" in message


def test_creer_client_est_whiteliste_par_defaut() -> None:
    """Le client fourni par le module ne peut pas etre construit sans whitelist."""
    with creer_client(sans_cache=True) as c, pytest.raises(DomaineNonAutoriseError):
        c.get("https://example.com/")


def test_redirection_vers_un_domaine_non_autorise_est_bloquee(
    sentinelle: TransportSentinelle,
) -> None:
    """Une 302 vers l'exterieur ne doit pas contourner la whitelist."""

    class TransportRedirection(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "https://example.com/"})

    client = httpx.Client(
        transport=TransportWhitelist(TransportRedirection()),
        follow_redirects=True,
    )
    with pytest.raises(DomaineNonAutoriseError):
        client.get("https://bodacc-datadila.opendatasoft.com/x")


# --- Repertoire du cache ------------------------------------------------------


def test_le_cache_est_hors_du_depot_par_defaut(monkeypatch) -> None:
    """Les reponses en cache contiennent des donnees personnelles reelles : le
    .gitignore protege du commit, pas d'une archive du repertoire de travail."""
    from pathlib import Path

    from fundora_prospect.http import repertoire_cache

    monkeypatch.delenv("FUNDORA_CACHE_DIR", raising=False)
    chemin = repertoire_cache()
    assert chemin.is_relative_to(Path.home())
    assert "fundora-prospect" in str(chemin)


def test_le_cache_est_surchargeable_par_variable(monkeypatch, tmp_path) -> None:
    """Sans cette variable, la seule facon de verifier une mesure a froid etait
    de detourner HOME — ni documentable ni sur."""
    from fundora_prospect.http import repertoire_cache

    monkeypatch.setenv("FUNDORA_CACHE_DIR", str(tmp_path / "froid"))
    assert repertoire_cache() == tmp_path / "froid"


def test_sans_cache_n_ecrit_rien_sur_disque(monkeypatch, tmp_path) -> None:
    vide = tmp_path / "jamais-cree"
    monkeypatch.setenv("FUNDORA_CACHE_DIR", str(vide))
    with creer_client(sans_cache=True):
        pass
    assert not vide.exists()
