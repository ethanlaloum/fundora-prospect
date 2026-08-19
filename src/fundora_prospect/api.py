"""La surface web : elle LIT la base, elle ne calcule rien.

## Ce qu'elle n'est pas

Elle n'appelle pas l'API Claude pour executer le pipeline — un score qui
traverse un LLM cesse d'etre reproductible, ce qui detruit l'argument central
du projet. Elle n'appelle pas non plus le BODACC : **aucune route ne touche au
reseau.** Le job de collecte balaye sans contrainte de temps de reponse ; ici on
relit ce qu'il a ecrit. Une route d'enrichissement rouvrirait un appel API dans
le temps de reponse, c'est-a-dire exactement ce que la base supprime.

## Pourquoi 127.0.0.1, et pourquoi ce n'est pas du confort

Cette surface sert `cedant_denomination`, qui **est un nom de personne** sur les
~20 % de cedants personne physique — contrainte 4. Le fichier SQLite vit deja
hors du depot pour cette raison ; l'exposer sur `0.0.0.0` annulerait la decision
d'un cran plus loin. Pas d'authentification non plus : une surface injoignable
vaut mieux qu'une surface joignable mal protegee.

## Ce qui reste ici, et ce qui n'y descend jamais

Le meme partage que `mcp_server` : valider les arguments, appeler le coeur,
mettre en forme. Aucune regle metier.

FastAPI absorbe nativement la validation que `mcp_server` fait a la main
(`_borne`, `_date`) : bornes en `Query(ge=, le=)`, dates en `date`. D'ou une
surface plus courte que l'autre — **126 lignes de code contre 172** — alors
qu'elle rend une route de plus.

### Le garde-fou etait « dix lignes par route », et il a mal vieilli

Deux corps le depassent : `leads` a 17 lignes, `evenement` a 14. Mesure faite
avant de conclure, parce que le nombre ne dit pas de quoi il est fait :

| Route | Lignes | Decisions | Lignes de litteral dict |
|---|---|---|---|
| `leads` | 17 | **0** | 9 |
| `evenement` | 14 | 5 | 8 |
| `collecte` | 7 | 1 | 5 |
| `sorties` | 6 | 2 | 5 |
| `hypothese` | 1 | 0 | 0 |

`leads` est long et ne decide **rien** : trois affectations, un appel au coeur,
une enveloppe de neuf lignes. Compter les lignes y mesure la taille de la
reponse, pas la quantite de logique.

`evenement` est le seul a brancher, et c'est la que le garde-fou a servi — pas
en signalant sa longueur, mais en faisant regarder ses branches. L'une d'elles,
`transitions(...) if siren else []`, n'etait gardee par aucun test : sans le
`if`, un evenement sans cedant identifie recuperait le journal de TOUTES les
societes. Pas une fuite hors du systeme, une attribution fausse — pire dans une
fiche d'audit qu'une absence.

**Le bon critere n'est donc pas la longueur, c'est le nombre de decisions.**
Une route qui assemble un gros dict reste une route ; une route qui teste
trois conditions commence a juger. La longueur reste utile comme declencheur de
relecture, pas comme verdict.

## Population : cette surface ne voit pas la meme que le MCP

Ecart **assume et documente** (voir CLAUDE.md, « l'asymetrie de population entre
les deux surfaces »). Meme grille, meme provenance, memes motifs de refus — mais
le MCP juge au mieux `2 x limite` candidats enrichis, la base les porte tous.
Aucune divergence de jugement, une divergence de population.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from fundora_prospect import __version__, entrepot, pipeline
from fundora_prospect.models import (
    StatutEntreprise,
    presenter_ecarte,
    presenter_evaluation,
)
from fundora_prospect.pipeline import (
    LIMITE_DEFAUT,
    LIMITE_MAX,
    MOIS_MAX,
    fenetre,
    normaliser_departements,
)

# Voir l'entete : ce defaut est une decision de conformite, pas un reglage.
HOTE_DEFAUT = "127.0.0.1"
PORT_DEFAUT = 8000

app = FastAPI(
    title="fundora-prospect",
    version=__version__,
    description=(
        "Lecture des cessions de fonds de commerce collectees depuis le BODACC. "
        "Le prospect est la SOCIETE CEDANTE, celle qui encaisse. Les scores sont "
        "recalcules a chaque lecture : la fraicheur decroit des le premier jour, "
        "donc un score stocke serait faux le lendemain."
    ),
)


def connexion() -> Iterator[sqlite3.Connection]:
    """Une connexion par requete.

    Les connexions `sqlite3` ne traversent pas les threads, et FastAPI execute
    les routes synchrones dans un pool. Une connexion de module serait un bug
    intermittent, c'est-a-dire le pire genre.
    """
    cnx = entrepot.ouvrir()
    try:
        yield cnx
    finally:
        cnx.close()


Base = Annotated[sqlite3.Connection, Depends(connexion)]


@app.exception_handler(ValueError)
def _argument_invalide(_: Request, exc: ValueError) -> JSONResponse:
    """Le vocabulaire du domaine leve `ValueError` — un code departement
    illisible, par exemple. C'est une faute de l'appelant, pas du serveur :
    422 et le message tel quel, qui dit deja la forme attendue."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def _rediger_refus(erreurs: list[Any]) -> str:
    """Les erreurs de validation, en une phrase lisible.

    Trois choses y figurent, et il faut les trois : **le champ** (l'appelant en
    a saisi quatre, lui dire « valeur invalide » le laisse deviner lequel), **le
    motif** de la bibliotheque, et **la valeur recue** — sans elle le message se
    lit comme une regle generale alors qu'il parle d'une saisie precise.

    `loc` commence par l'origine (`query`, `body`) : on la retire pour nommer le
    champ tel que l'appelant l'a ecrit, en gardant le repli si elle est seule.

    Le motif est celui de pydantic, **verbatim et en anglais**. Le traduire
    demanderait une table de correspondance vers des messages qu'on ne controle
    pas : elle serait muette au premier type d'erreur nouveau, et personne ne le
    verrait. Un message de bibliotheque exact vaut mieux qu'une traduction qui
    derive.
    """
    morceaux = []
    for erreur in erreurs:
        chemin = [str(part) for part in erreur.get("loc", ())]
        champ = ".".join(chemin[1:]) or (chemin[0] if chemin else "requete")
        morceaux.append(f"{champ} : {erreur.get('msg', '')} (recu {erreur.get('input')!r})")
    return " ; ".join(morceaux)


@app.exception_handler(RequestValidationError)
def _validation_invalide(_: Request, exc: RequestValidationError) -> JSONResponse:
    """**Le second chemin de refus, et il ne ressemblait pas au premier.**

    FastAPI rend nativement `detail` sous forme de LISTE d'objets. Meme clef,
    meme code HTTP, autre forme — et un consommateur qui attend une chaine
    tombe sur son repli sans savoir pourquoi.

    Constate en usage reel : une recherche « 06 / Avril / 300k / 500k » faisait
    afficher « /leads : reponse 422 » a la surface web, alors que l'API savait
    parfaitement que trois champs etaient en cause et lesquels. Le front n'y
    pouvait rien : il recevait une chaine la moitie du temps.

    **La forme du refus fait partie du contrat**, au meme titre que celle du
    succes. `detail` est desormais une chaine sur les deux chemins, et un test
    parametre sur les deux gestionnaires le verrouille — un corpus qui ne
    couvrirait qu'un seul d'entre eux resterait vert sur l'autre.
    """
    return JSONResponse(status_code=422, content={"detail": _rediger_refus(exc.errors())})


def _transition(t: entrepot.Transition) -> dict[str, Any]:
    return {
        "siren": t.siren,
        "observe_a": t.observe_a.isoformat(),
        "statut_avant": str(t.statut_avant),
        "statut_apres": str(t.statut_apres),
        "motif": t.motif,
        "sortie_du_flux": t.sortie_du_flux,
    }


def _revision(r: entrepot.Revision) -> dict[str, Any]:
    return {
        "remplacee_a": r.remplacee_a.isoformat(),
        "contenu": r.contenu,
    }


@app.get("/leads")
def leads(
    base: Base,
    departement: str = Query("PACA", description='Codes separes par des virgules, ou "PACA".'),
    mois: int = Query(12, ge=1, le=MOIS_MAX),
    montant_min: float = Query(0.0, ge=0),
    limite: int = Query(LIMITE_DEFAUT, ge=1, le=LIMITE_MAX),
) -> dict[str, Any]:
    """Les leads classes, du meilleur au moins bon, avec le decompte des refus."""
    departements = normaliser_departements(departement)
    fin = date.today()
    debut = fenetre(mois, fin)
    resultat = pipeline.lire(
        entrepot.evenements(base, departements=departements, depuis=debut, jusqu_a=fin),
        montant_min=montant_min,
        limite=limite,
        collecte=entrepot.compteurs_de_collecte(base, departements=departements),
    )
    return {
        "resume": pipeline.resumer(resultat.statistiques),
        "departements": departements,
        "periode": {"debut": debut.isoformat(), "fin": fin.isoformat()},
        "montant_min_eur": resultat.montant_min,
        "statistiques": resultat.statistiques,
        "leads": resultat.leads,
    }


@app.get("/ecartes")
def ecartes(
    base: Base,
    departement: str = Query("PACA", description='Codes separes par des virgules, ou "PACA".'),
    mois: int = Query(12, ge=1, le=MOIS_MAX),
    montant_min: float = Query(0.0, ge=0),
    motif: str | None = Query(None, description="Filtre sur un motif de refus exact."),
    limite: int = Query(LIMITE_DEFAUT, ge=1, le=LIMITE_MAX),
) -> dict[str, Any]:
    """Les evenements REFUSES, avec leur motif. L'auditabilite ne s'arrete pas
    au comptage.

    Passe par le meme `pipeline.lire` que `/leads`, sur les memes parametres :
    les motifs y sont donc les memes objets, pas deux vocabulaires qui se
    ressemblent. Un test compare quand meme les deux routes — c'est la troisieme
    surface a nommer ces refus.
    """
    departements = normaliser_departements(departement)
    fin = date.today()
    debut = fenetre(mois, fin)
    resultat = pipeline.lire(
        entrepot.evenements(base, departements=departements, depuis=debut, jusqu_a=fin),
        montant_min=montant_min,
        limite=1,
    )
    retenus = [e for e in resultat.ecartes if motif is None or e.motif == motif]
    return {
        "departements": departements,
        "periode": {"debut": debut.isoformat(), "fin": fin.isoformat()},
        "montant_min_eur": resultat.montant_min,
        "motif": motif,
        # Deux grandeurs, deux noms : ce qui correspond au filtre, et ce que la
        # coupe a laisse passer. Une coupe qui ne se declare pas se lit comme un
        # resultat.
        "correspondants": len(retenus),
        "rendus": min(len(retenus), limite),
        "ecartes": [presenter_ecarte(e.event, e.motif) for e in retenus[:limite]],
    }


@app.get("/evenements/{evenement_id}")
def evenement(evenement_id: str, base: Base) -> dict[str, Any]:
    """Un cas isole, **ecarte compris** — la seule route qui reponde a
    « pourquoi celui-la a-t-il ete refuse ? ». Avec ses revisions et les
    transitions de statut de son cedant.

    ## `ecarte` a remplace `motif_ecart`, et ce n'est pas un renommage

    La route ne rendait qu'un motif : une fiche de refus n'avait donc ni cedant,
    ni montant, ni `url_publication` — c'est-a-dire rien de ce qui rend le refus
    verifiable. Un lecteur y voyait « apport » et aucun moyen de le contredire.

    Elle rend maintenant la meme vue que `/ecartes`, montee par la meme
    `presenter_ecarte`. Le motif y figure, une fois : deux champs le portant
    seraient deux sources, donc une divergence a venir.

    **Exactement un des deux est renseigne**, et un test le verrouille dans les
    deux sens. Une route qui rendrait les deux nuls laisserait une fiche muette
    sans que rien ne le signale ; une route qui rendrait les deux ferait
    coexister a l'ecran un prospect et son refus.
    """
    stockes = entrepot.evenements(base, evenement_id=evenement_id)
    if not stockes:
        raise HTTPException(status_code=404, detail=f"aucun evenement {evenement_id!r} en base")
    resultat = pipeline.lire(stockes, limite=1)
    refuse = resultat.ecartes[0] if resultat.ecartes else None
    siren = stockes[0].event.cedant_siren
    return {
        "lead": resultat.leads[0] if resultat.leads else None,
        "ecarte": presenter_ecarte(refuse.event, refuse.motif) if refuse else None,
        "revisions": [_revision(r) for r in entrepot.revisions(base, evenement_id=evenement_id)],
        "transitions": [_transition(t) for t in entrepot.transitions(base, siren=siren)]
        if siren
        else [],
    }


@app.get("/collecte")
def collecte(base: Base, departement: str = Query("PACA")) -> dict[str, Any]:
    """Ce que la base sait, et quand elle a regarde.

    `compteurs` a `None` n'est pas une erreur : une base peut exister sans avoir
    jamais ete remplie. Repondre 404 laisserait croire a un probleme de route.
    """
    departements = normaliser_departements(departement)
    compteurs = entrepot.compteurs_de_collecte(base, departements=departements)
    return {
        "departements": departements,
        "compteurs": compteurs,
        "reserve": None if compteurs else "aucune collecte enregistree pour ces departements",
    }


@app.get("/sorties")
def sorties(base: Base, depuis: date | None = None) -> dict[str, Any]:
    """Les cedants qui ont cesse, dates — le signal metier du journal.

    `transitions_observees` compte TOUTES les bascules, `sorties` seulement
    celles qui font sortir du flux. Deux grandeurs, deux noms : les confondre
    ferait passer un `inconnu -> active` pour un prospect perdu.
    """
    toutes = entrepot.transitions(base, depuis=depuis)
    return {
        "depuis": depuis.isoformat() if depuis else None,
        "transitions_observees": len(toutes),
        "sorties": [_transition(t) for t in toutes if t.sortie_du_flux],
    }


class Hypothese(BaseModel):
    """Une cession decrite a la main. **Pas un lead** : elle n'a pas d'URL de
    publication, donc elle ne peut pas etre serialisee (contrainte 3)."""

    montant_eur: float = Field(gt=0)
    date_acte: date | None = None
    date_parution: date | None = None
    departement: str = "13"
    statut_cedant: StatutEntreprise = StatutEntreprise.INCONNU
    code_ape: str | None = None


@app.post("/hypotheses")
def hypothese(corps: Hypothese) -> dict[str, Any]:
    """Le score d'une cession decrite explicitement, avec le detail du calcul.

    **Ce n'est pas un modele predictif** : les poids sont des hypotheses
    commerciales a dire d'expert, sans donnee de conversion pour les calibrer.
    """
    return presenter_evaluation(pipeline.evaluer_hypothese(**corps.model_dump()))


def main() -> None:
    """Point d'entree local. `HOTE_DEFAUT` n'est pas surchargeable ici : le
    rendre configurable ferait de l'exposition un reglage, alors que c'est une
    decision de conformite. Qui veut l'exposer passera par un reverse proxy et
    saura ce qu'il fait."""
    import uvicorn

    uvicorn.run(app, host=HOTE_DEFAUT, port=PORT_DEFAUT)


if __name__ == "__main__":
    main()
