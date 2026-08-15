"""Transport HTTP whiteliste et cache disque.

Contrainte non negociable 2 : seuls deux domaines sont joignables. La
verification est faite **au niveau du transport httpx**, pas dans une fonction
utilitaire — a cet endroit, aucun chemin de code du projet ne peut l'eviter, y
compris un appel ecrit plus tard par distraction, une redirection HTTP, ou une
URL construite dynamiquement.

C'est le premier des deux verrous de la whitelist. Le second est le hook
`PreToolUse` de la Phase 5, qui couvre un perimetre different : ce que l'agent
fait, la ou celui-ci couvre ce que le code fait. Aucun des deux ne remplace
l'autre.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import httpx

DOMAINES_AUTORISES = frozenset(
    {
        "bodacc-datadila.opendatasoft.com",
        "recherche-entreprises.api.gouv.fr",
    }
)

VARIABLE_CACHE = "FUNDORA_CACHE_DIR"


def repertoire_cache() -> Path:
    """Repertoire du cache HTTP, surchargeable par `FUNDORA_CACHE_DIR`.

    Les reponses en cache contiennent des donnees personnelles reelles issues
    du BODACC. Elles vivent HORS du depot : le .gitignore protege du commit,
    pas d'une archive du repertoire de travail (contrainte 4).

    La variable d'environnement existe pour qu'on puisse verifier une mesure
    a froid — sans elle, la seule facon de vider le cache etait de detourner
    `HOME`, ce qui n'est ni documentable ni sur.
    """
    force = os.environ.get(VARIABLE_CACHE)
    if force:
        return Path(force).expanduser()
    return Path.home() / ".cache" / "fundora-prospect" / "http"


class DomaineNonAutoriseError(RuntimeError):
    """Levee avant toute connexion vers un domaine hors whitelist."""

    def __init__(self, hote: str | None, autorises: frozenset[str]) -> None:
        self.hote = hote
        self.autorises = autorises
        super().__init__(
            f"Domaine non autorise : {hote!r}. "
            f"Ce projet ne peut joindre que : {', '.join(sorted(autorises))}. "
            "Aucune connexion n'a ete ouverte."
        )


class TransportWhitelist(httpx.BaseTransport):
    """Refuse toute requete hors whitelist avant de la deleguer.

    La correspondance est **exacte** : `evil.bodacc-datadila.opendatasoft.com`
    est refuse, un test de suffixe laisserait passer n'importe quel
    sous-domaine controle par un tiers.
    """

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        domaines: frozenset[str] = DOMAINES_AUTORISES,
    ) -> None:
        self._transport = transport if transport is not None else httpx.HTTPTransport()
        self._domaines = domaines

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        hote = request.url.host
        if hote not in self._domaines:
            raise DomaineNonAutoriseError(hote, self._domaines)
        return self._transport.handle_request(request)

    def close(self) -> None:
        self._transport.close()


class TransportCache(httpx.BaseTransport):
    """Cache disque des GET 200, pour ne pas retaper l'API a chaque iteration.

    Les mesures de volume portent sur des milliers d'annonces : sans cache, les
    tests reseau et le calcul du volume 12 mois epuiseraient le quota anonyme.
    """

    def __init__(self, transport: httpx.BaseTransport, repertoire: Path | None = None) -> None:
        self._transport = transport
        self._repertoire = repertoire if repertoire is not None else repertoire_cache()
        self._repertoire.mkdir(parents=True, exist_ok=True)

    def _chemin(self, request: httpx.Request) -> Path:
        cle = hashlib.sha256(f"{request.method} {request.url}".encode()).hexdigest()
        return self._repertoire / f"{cle}.json"

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return self._transport.handle_request(request)

        chemin = self._chemin(request)
        if chemin.exists():
            charge = json.loads(chemin.read_text(encoding="utf-8"))
            return httpx.Response(
                charge["status"],
                content=charge["content"].encode("utf-8"),
                headers={"content-type": charge.get("content_type", "application/json")},
                request=request,
            )

        reponse = self._transport.handle_request(request)
        if reponse.status_code == 200:
            reponse.read()
            chemin.write_text(
                json.dumps(
                    {
                        "status": reponse.status_code,
                        "content": reponse.text,
                        "content_type": reponse.headers.get("content-type", "application/json"),
                    }
                ),
                encoding="utf-8",
            )
        return reponse

    def close(self) -> None:
        self._transport.close()


def creer_client(
    *,
    cache: Path | None = None,
    sans_cache: bool = False,
    timeout: float = 30.0,
    domaines: frozenset[str] = DOMAINES_AUTORISES,
) -> httpx.Client:
    """Le seul constructeur de client du projet. Whitelist non optionnelle.

    L'ordre des transports compte : la whitelist est **au-dessus** du cache,
    donc un domaine interdit est refuse meme si une reponse tramaine en cache.
    """
    transport: httpx.BaseTransport = httpx.HTTPTransport()
    if not sans_cache:
        transport = TransportCache(transport, cache)
    return httpx.Client(
        transport=TransportWhitelist(transport, domaines),
        timeout=timeout,
        follow_redirects=True,
    )
