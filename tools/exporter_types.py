"""Genere les types TypeScript du front depuis des reponses REELLES de l'API.

## Pourquoi generer plutot qu'ecrire

Le front a besoin de connaitre la forme des reponses. Trois facons de l'obtenir,
deux mauvaises :

- **Ecrire les types a la main** : une copie du modele Python dans un autre
  langage, qui derivera. C'est la recopie manuelle qui a deja echoue deux fois
  sur ce projet, avec l'exemple de `SKILL.md`.
- **Deduire de l'OpenAPI** : inutilisable ici. Les routes rendent
  `dict[str, Any]`, donc le schema dit `{"type": "object"}` et rien de plus. Y
  remedier demanderait des modeles Pydantic de reponse, c'est-a-dire recopier la
  forme de `serialiser` a un second endroit Python — la divergence qu'on evite.
- **Generer depuis des reponses reelles**, ce module. La source de verite reste
  le code Python qui produit les dicts, et `tests/test_types_web.py` echoue si
  le fichier genere est perime.

## Le piege : un type deduit d'un corpus degenere est faux

Deduire un type d'une instance JSON marche tant que l'instance est
representative. Si `date_acte` vaut `null` dans tous les echantillons, le type
genere est `null` — et le front croira ce champ toujours vide.

C'est **exactement la meme faute qu'une assertion sur un corpus degenere** :
la mesure est correcte, le corpus ne pouvait pas la mettre en defaut. D'ou
`champs_degeneres`, qui refuse un schema ou un champ n'a jamais pris de valeur,
et d'ou un corpus construit pour que chaque champ en prenne une.

Deux formes de degenerescence, et il faut les deux :

- un champ dont le type se reduit a `null` — jamais renseigne ;
- un tableau toujours vide — on n'a rien appris de son element.

## Les dictionnaires a clefs libres

`statistiques.ecartes` est `{motif: compte}`. Deduire un champ par motif ecrirait
**les libelles de refus dans le fichier genere**, c'est-a-dire dans `web/src` —
la duplication de vocabulaire que le front s'interdit. Ces chemins sont declares
`Record<string, T>`, et `tests/test_front_sans_vocabulaire.py` sert de filet :
il balaye `web/src` entier, fichier genere compris.

Usage : `python tools/exporter_types.py [chemin]`
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parent.parent
CIBLE = RACINE / "web" / "src" / "api" / "schema.d.ts"

# Objets dont les CLEFS sont des donnees, pas des champs. Les deduire nommerait
# des motifs de refus dans le fichier genere — voir l'entete.
CHEMINS_DICTIONNAIRES = frozenset(
    {
        "ReponseLeads.statistiques.ecartes",
        "ReponseEvenement.revisions[].contenu",
    }
)

ENTETE = """// GENERE par tools/exporter_types.py — NE PAS EDITER A LA MAIN.
//
// Les types viennent de reponses REELLES de l'API, pas d'une recopie du modele
// Python. `tests/test_types_web.py` regenere ce fichier et echoue s'il differe,
// et refuse un schema deduit d'un corpus qui n'exerce pas tous les champs.
//
// Pour le mettre a jour :  python tools/exporter_types.py
"""


# --- Inference ------------------------------------------------------------------


def inferer(valeur: Any) -> dict[str, Any]:
    """Le type d'une valeur JSON, sous une forme fusionnable."""
    if valeur is None:
        return {"genre": "prim", "noms": {"null"}}
    if isinstance(valeur, bool):
        return {"genre": "prim", "noms": {"boolean"}}
    if isinstance(valeur, int | float):
        return {"genre": "prim", "noms": {"number"}}
    if isinstance(valeur, str):
        return {"genre": "prim", "noms": {"string"}}
    if isinstance(valeur, list):
        element: dict[str, Any] | None = None
        for item in valeur:
            element = inferer(item) if element is None else fusionner(element, inferer(item))
        return {"genre": "tableau", "element": element}
    if isinstance(valeur, dict):
        return {"genre": "objet", "champs": {c: inferer(v) for c, v in valeur.items()}}
    raise TypeError(f"valeur JSON inattendue : {type(valeur).__name__}")


def _membres(type_: dict[str, Any]) -> list[dict[str, Any]]:
    """Aplatit les unions imbriquees : `a | (b | c)` doit rendre `a | b | c`."""
    return list(type_["membres"]) if type_["genre"] == "union" else [type_]


def fusionner(gauche: dict[str, Any], droite: dict[str, Any]) -> dict[str, Any]:
    """Fusionne deux types observes.

    Un champ absent d'un echantillon devient optionnel : `statistiques` gagne
    des clefs quand la collecte est connue, et pretendre qu'elles sont toujours
    la ferait mentir le type.
    """
    if gauche["genre"] != droite["genre"]:
        # Un noeud d'union, pas deux chaines deja rendues : le rendu doit
        # connaitre son indentation, et l'anticiper produisait des objets
        # imbriques colles a la marge gauche.
        membres = [*_membres(gauche), *_membres(droite)]
        return {"genre": "union", "membres": membres}
    if gauche["genre"] == "prim":
        return {"genre": "prim", "noms": gauche["noms"] | droite["noms"]}
    if gauche["genre"] == "tableau":
        elements = [t for t in (gauche["element"], droite["element"]) if t is not None]
        if not elements:
            return {"genre": "tableau", "element": None}
        fusion = elements[0]
        for autre in elements[1:]:
            fusion = fusionner(fusion, autre)
        return {"genre": "tableau", "element": fusion}

    champs: dict[str, Any] = {}
    for nom in {*gauche["champs"], *droite["champs"]}:
        a, b = gauche["champs"].get(nom), droite["champs"].get(nom)
        if a is None or b is None:
            present = a or b
            champs[nom] = {**present, "optionnel": True}
        else:
            champs[nom] = {**fusionner(a, b), "optionnel": a.get("optionnel", False)}
    return {"genre": "objet", "champs": champs}


# --- Le controle du corpus degenere ---------------------------------------------


def _est_nul_seul(type_: dict[str, Any]) -> bool:
    return type_["genre"] == "prim" and type_["noms"] == {"null"}


def champs_degeneres(type_: dict[str, Any], chemin: str = "") -> list[str]:
    """Les chemins dont le corpus n'a rien appris.

    Un champ toujours `null` et un tableau toujours vide sont deux facons de
    produire un type juste sur l'echantillon et faux sur la realite. Ils sont
    signales, pas corriges : c'est le CORPUS qu'il faut enrichir, pas le type
    qu'il faut deviner.
    """
    if type_["genre"] == "union":
        # `null | {...}` n'est PAS degenere : c'est le cas ou le corpus a vu les
        # deux. Le membre `null` est donc de l'information, pas une absence — ne
        # reste degenere qu'une union dont AUCUN membre ne dit rien.
        informatifs = [m for m in type_["membres"] if not _est_nul_seul(m)]
        if not informatifs:
            return [f"{chemin} : jamais renseigne (type deduit `null`)"]
        return [p for m in informatifs for p in champs_degeneres(m, chemin)]
    if type_["genre"] == "prim":
        return [f"{chemin} : jamais renseigne (type deduit `null`)"] if _est_nul_seul(type_) else []
    if type_["genre"] == "tableau":
        if type_["element"] is None:
            return [f"{chemin} : tableau toujours vide, element inconnu"]
        return champs_degeneres(type_["element"], f"{chemin}[]")
    if chemin in CHEMINS_DICTIONNAIRES:
        return []
    return [
        probleme
        for nom, sous in sorted(type_["champs"].items())
        for probleme in champs_degeneres(sous, f"{chemin}.{nom}" if chemin else nom)
    ]


# --- Rendu TypeScript -------------------------------------------------------------


def rendre(type_: dict[str, Any], chemin: str = "", indentation: int = 0) -> str:
    if type_["genre"] == "union":
        rendus = [rendre(m, chemin, indentation) for m in type_["membres"]]
        return " | ".join(sorted(set(rendus), key=lambda s: ("{" in s, s)))
    if type_["genre"] == "prim":
        return " | ".join(sorted(type_["noms"]))
    if type_["genre"] == "tableau":
        if type_["element"] is None:
            return "unknown[]"
        interieur = rendre(type_["element"], f"{chemin}[]", indentation)
        return f"Array<{interieur}>" if "\n" in interieur else f"{interieur}[]"

    if chemin in CHEMINS_DICTIONNAIRES:
        valeurs = [rendre(v, chemin, indentation) for v in type_["champs"].values()]
        return f"Record<string, {' | '.join(sorted(set(valeurs))) or 'unknown'}>"

    marge, interne = "  " * indentation, "  " * (indentation + 1)
    lignes = []
    for nom in sorted(type_["champs"]):
        sous = type_["champs"][nom]
        point = "?" if sous.get("optionnel") else ""
        sous_chemin = f"{chemin}.{nom}" if chemin else nom
        lignes.append(f"{interne}{nom}{point}: {rendre(sous, sous_chemin, indentation + 1)};")
    return "{\n" + "\n".join(lignes) + f"\n{marge}}}"


# --- Le corpus, choisi pour que chaque champ prenne une valeur -------------------


def _annonce(module: Any, identifiant: str, **options: Any) -> Any:
    jour = date.today() - timedelta(days=options.pop("jours", 30))
    prix = module["PrixCession"](
        montant=options.pop("montant", 400_000.0),
        devise="EUR",
        qualification=options.pop("qualification", module["Qualification"].ACHAT),
        methode="test",
        texte_source="",
        confiance=module["Confiance"].ACTE_DATE,
        ecart_acte_jours=0,
    )
    return module["Annonce"](
        id=identifiant,
        date_parution=jour,
        date_acte=options.pop("date_acte", jour),
        departement="06",
        url_publication=f"https://www.bodacc.fr/x/{identifiant}",
        categorie_vente=None,
        activite=None,
        cedant=module["Cedant"](
            denomination=f"CEDANT {identifiant}",
            type_personne=options.pop("type_personne", "pm"),
            siren=options.pop("siren", "852872563"),
        ),
        prix=prix,
    )


def capturer() -> dict[str, list[Any]]:
    """Interroge chaque route sur un corpus **contraste**, et rend les reponses.

    Le corpus n'est pas un echantillon quelconque : chaque cas y est present
    pour qu'un champ precis cesse d'etre toujours nul.

    | Cas | Ce qu'il fait exister |
    |---|---|
    | lead avec acte date | `date_acte`, `date_reference` |
    | lead sans acte date | la variante `null` du meme champ |
    | cedant sans SIREN | `siren`, `code_ape`, `section_ape` a `null` |
    | cedant personne physique | l'autre valeur de `type_cedant` |
    | apport, cession sous le seuil | `ecartes` non vide, deux motifs |
    | **une seule** societe qui cesse | `transitions`, `sorties`, et un lead vivant |
    | second balayage, montant change | `revisions` |
    | hypothese refusee | `motif_refus` non nul |
    | `/collecte` sur un departement vide | `reserve` non nul |
    | `/ecartes` et `/sorties` filtres | `motif` et `depuis` non nuls |

    **Le premier jet faisait cesser TOUTES les societes au second balayage.**
    Consequence : le seul lead restant etait celui sans SIREN, donc sans code
    APE ni section — et `siren`, `code_ape`, `section_ape`, `lead` sortaient
    tous typés `null`. Le controle l'a signale des la premiere execution, ce qui
    est exactement son role : un corpus qui n'exerce pas un champ produit un
    type faux, sans que rien d'autre ne rougisse.
    """
    from fastapi.testclient import TestClient

    from fundora_prospect import api, collecte, entrepot
    from fundora_prospect.bodacc import Annonce, Cedant, ResultatRecherche
    from fundora_prospect.enrichment import Enrichissement
    from fundora_prospect.models import StatutEntreprise
    from fundora_prospect.prix import Confiance, PrixCession, Qualification

    module = {
        "Annonce": Annonce, "Cedant": Cedant, "PrixCession": PrixCession,
        "Qualification": Qualification, "Confiance": Confiance,
    }
    a = lambda i, **o: _annonce(module, i, **o)  # noqa: E731

    # Deux societes : l'une reste active — c'est elle qui porte un lead complet,
    # avec SIREN et code APE — l'autre cesse, et fournit transition, sortie du
    # flux et refus « societe cedante cessee ».
    VIVANTE, SORTANTE = "852872563", "404833048"

    def corpus(montant_variable: float) -> list[Any]:
        return [
            a("AVEC-ACTE", siren=VIVANTE, montant=montant_variable),
            a("SANS-ACTE", siren=VIVANTE, date_acte=None, montant=500_000.0),
            a("SANS-SIREN", siren=None, montant=450_000.0),
            a("PHYSIQUE", siren=SORTANTE, type_personne="pp", montant=420_000.0),
            a("APPORT", siren=VIVANTE, qualification=Qualification.APPORT, montant=600_000.0),
            # Ecarte ET sans acte datable ET sans SIREN : c'est le seul cas
            # qui rende `date_acte` et `siren` nullables du cote des refus.
            # Sans lui, le type les annoncerait toujours presents — le controle
            # ne voit que les champs TOUJOURS nuls, pas ceux jamais nuls.
            a("PETIT", siren=None, date_acte=None, montant=1_000.0),
        ]

    def enrichir(siren: str, sortante_cessee: bool) -> Enrichissement:
        cessee = sortante_cessee and str(siren) == SORTANTE
        return Enrichissement(
            siren=str(siren),
            statut=StatutEntreprise.CESSEE if cessee else StatutEntreprise.ACTIVE,
            code_ape="56.10A",
            section_ape="I",
            motif="unite legale : etat administratif " + ("C" if cessee else "A"),
        )

    with tempfile.TemporaryDirectory() as dossier:
        os.environ[entrepot.VARIABLE_BASE] = str(Path(dossier) / "types.db")
        base = entrepot.ouvrir()
        passages = (
            (date.today(), False, 400_000.0),
            (date.today() + timedelta(days=40), True, 470_000.0),
        )
        for jour, sortie, montant in passages:
            annonces = corpus(montant)
            collecte.balayer(
                base, departements=["06"], aujourdhui=jour,
                rechercher=lambda _a=annonces, **_: ResultatRecherche(
                    annonces=_a, publiees=len(_a), rapatriees=len(_a)
                ),
                enrichir=lambda s, _c=sortie, **_: enrichir(s, _c),
            )
        base.close()

        client = TestClient(api.app)
        commun = {"departement": "06", "mois": 12}
        hier = (date.today() - timedelta(days=1)).isoformat()
        return {
            "ReponseLeads": [
                client.get("/leads", params=commun).json(),
                client.get("/leads", params={**commun, "montant_min": 100_000}).json(),
            ],
            "ReponseEcartes": [
                client.get("/ecartes", params={**commun, "montant_min": 100_000}).json(),
                client.get("/ecartes", params={**commun, "motif": "apport"}).json(),
            ],
            "ReponseEvenement": [
                # Trois cas, trois champs qui cessent d'etre vides : un lead
                # complet, un refus motive, et un cedant dont le statut a
                # bascule — seul le dernier fait exister `transitions`.
                client.get("/evenements/AVEC-ACTE").json(),
                client.get("/evenements/APPORT").json(),
                client.get("/evenements/PHYSIQUE").json(),
            ],
            "ReponseCollecte": [
                client.get("/collecte", params=commun).json(),
                # Un departement jamais collecte : c'est ce qui fait exister
                # `reserve`, qui vaut `null` partout ailleurs.
                client.get("/collecte", params={"departement": "13"}).json(),
            ],
            "ReponseSorties": [
                client.get("/sorties").json(),
                client.get("/sorties", params={"depuis": hier}).json(),
            ],
            "ReponseHypothese": [
                client.post("/hypotheses", json={"montant_eur": 400_000}).json(),
                client.post(
                    "/hypotheses", json={"montant_eur": 400_000, "statut_cedant": "cessee"}
                ).json(),
            ],
        }


def types_captures() -> dict[str, dict[str, Any]]:
    """Un type fusionne par route."""
    types: dict[str, dict[str, Any]] = {}
    for nom, echantillons in capturer().items():
        fusion = inferer(echantillons[0])
        for suivant in echantillons[1:]:
            fusion = fusionner(fusion, inferer(suivant))
        types[nom] = fusion
    return types


def generer() -> str:
    types = types_captures()
    problemes = [p for nom, t in types.items() for p in champs_degeneres(t, nom)]
    if problemes:
        raise SystemExit(
            "corpus degenere — enrichir `capturer()`, pas deviner le type :\n  "
            + "\n  ".join(problemes)
        )
    corps = "\n\n".join(
        f"export interface {nom} {rendre(t, nom)}" for nom, t in sorted(types.items())
    )
    return f"{ENTETE}\n{corps}\n"


def main() -> int:
    cible = Path(sys.argv[1]) if len(sys.argv) > 1 else CIBLE
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(generer(), encoding="utf-8")
    print(f"{cible.relative_to(RACINE)} genere depuis des reponses reelles")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(RACINE / "src"))
    raise SystemExit(main())

