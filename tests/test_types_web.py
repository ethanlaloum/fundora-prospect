"""Les types du front sont-ils a jour, et deduits d'un corpus qui les exerce ?

Deux proprietes distinctes, et la seconde est la moins evidente :

1. **`web/src/api/schema.d.ts` n'est pas perime.** Il est genere depuis des
   reponses reelles ; le regenerer et comparer est la seule facon de savoir
   qu'il decrit encore l'API. La recopie manuelle a deja echoue deux fois sur
   ce projet — voir l'exemple de `SKILL.md`.

2. **Le corpus de generation exerce chaque champ.** Un type deduit d'un corpus
   degenere est faux exactement comme une assertion l'etait : la deduction est
   correcte, l'echantillon ne pouvait pas la mettre en defaut. Un champ toujours
   `null` sort typé `null`, et le front croira ce champ vide pour toujours.

La limite, ecrite parce qu'elle est reelle : le controle voit les champs
**toujours nuls**, pas les champs **jamais nuls**. Un champ nullable dans la
realite mais renseigne partout dans le corpus sortira non-nullable, et rien ne
le signalera. C'est au corpus d'etre ecrit pour exercer la nullabilite la ou
elle existe — `capturer()` le fait explicitement, cas par cas.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.exporter_types import (
    CIBLE,
    champs_degeneres,
    fusionner,
    generer,
    inferer,
    types_captures,
)


def test_le_schema_genere_n_est_pas_perime() -> None:
    """Le fichier sur disque doit etre exactement ce que le generateur produit
    aujourd'hui. S'il differe, l'API a bouge et le front la decrit mal."""
    assert CIBLE.exists(), f"{CIBLE} absent — lancer python tools/exporter_types.py"
    assert CIBLE.read_text(encoding="utf-8") == generer(), (
        "schema.d.ts est perime — relancer : python tools/exporter_types.py"
    )


def test_aucun_champ_n_est_deduit_d_un_corpus_degenere() -> None:
    """Le controle sur le vrai corpus. Il a signale sept champs a sa premiere
    execution, dont `siren` et `code_ape` : le second balayage faisait cesser
    TOUTES les societes, et le seul lead restant etait celui sans SIREN."""
    problemes = [p for nom, t in types_captures().items() for p in champs_degeneres(t, nom)]
    assert not problemes, "corpus degenere :\n  " + "\n  ".join(problemes)


def test_le_schema_ne_nomme_aucun_motif_de_refus() -> None:
    """`statistiques.ecartes` est `{motif: compte}` : deduire un champ par motif
    ecrirait les libelles de refus DANS le fichier genere, donc dans `web/src`.
    Ils doivent sortir en `Record<string, …>`."""
    schema = CIBLE.read_text(encoding="utf-8")
    assert "Record<string, number>" in schema, "les dictionnaires a clefs libres"
    assert "apport" not in schema.lower()


# --- Le controle a des dents --------------------------------------------------


@pytest.mark.parametrize(
    ("echantillon", "attendu"),
    [
        ({"champ": None}, "champ"),
        ({"objet": {"dedans": None}}, "objet.dedans"),
        ({"liste": []}, "liste"),
        ({"liste": [{"dedans": None}]}, "liste[].dedans"),
    ],
)
def test_le_controle_attrape_un_champ_jamais_exerce(
    echantillon: dict[str, object], attendu: str
) -> None:
    """Quatre formes de degenerescence, dont deux imbriquees : le controle doit
    descendre dans les objets et dans les elements de tableau, sinon il ne voit
    que la surface."""
    problemes = champs_degeneres(inferer(echantillon))
    assert any(p.startswith(attendu) for p in problemes), problemes


def test_un_champ_parfois_nul_n_est_PAS_degenere() -> None:
    """**L'autre moitie, et sans elle le controle refuserait tout.**

    `null | string` est le resultat d'un corpus qui a vu les deux cas — c'est
    exactement ce qu'on veut. Un controle qui le signalerait pousserait a
    supprimer les cas nuls du corpus, donc a fabriquer des types faux.
    """
    fusion = fusionner(inferer({"date": None}), inferer({"date": "2026-08-18"}))
    assert champs_degeneres(fusion) == []


def test_un_tableau_non_vide_n_est_pas_degenere() -> None:
    assert champs_degeneres(inferer({"liste": [{"dedans": 1}]})) == []


def test_deux_objets_separes_par_un_nul_FUSIONNENT_quand_meme() -> None:
    """**Le defaut trouve en enrichissant le corpus de `/evenements`.**

    `lead` valait un objet, puis `null`, puis `null`, puis un autre objet.
    Chaque fusion voyait des genres differents, empilait un membre de plus, et
    les deux objets ne se rencontraient jamais : le type devenait
    `null | {…} | {…}` — deux formes pour un meme champ.

    Le corpus separe les deux objets sur chaque champ : l'un renseigne ce que
    l'autre laisse nul. Deux objets identiques ne departageraient rien, et un
    seul champ ne dirait pas si la fusion est partielle.
    """
    fusion = inferer({"lead": {"siren": "852872563", "ape": "56.10A"}})
    for suivant in (
        {"lead": None},
        {"lead": None},
        {"lead": {"siren": None, "ape": None}},
    ):
        fusion = fusionner(fusion, inferer(suivant))

    lead = fusion["champs"]["lead"]
    objets = [m for m in lead["membres"] if m["genre"] == "objet"]
    assert len(objets) == 1, f"{len(objets)} formes d'objet pour un meme champ"
    assert objets[0]["champs"]["siren"]["noms"] == {"string", "null"}
    assert objets[0]["champs"]["ape"]["noms"] == {"string", "null"}


def test_le_message_du_controle_n_accuse_pas_le_corpus_a_tort() -> None:
    """Le symptome du defaut precedent etait trompeur.

    Le controle annoncait « champ jamais renseigne », c'est-a-dire un reproche
    au CORPUS — alors que le corpus exercait bien le champ et que c'est
    l'agregation qui perdait l'information. On aurait pu passer longtemps a
    enrichir un corpus deja suffisant.
    """
    fusion = inferer({"lead": {"siren": "852872563"}})
    for suivant in ({"lead": None}, {"lead": {"siren": None}}):
        fusion = fusionner(fusion, inferer(suivant))

    assert champs_degeneres(fusion) == []


def test_le_controle_rend_le_CHEMIN_du_champ_fautif(tmp_path: Path) -> None:
    """Un controle qui dirait « corpus degenere » sans dire ou obligerait a
    chercher a la main dans une reponse de plusieurs centaines de lignes."""
    problemes = champs_degeneres(inferer({"a": {"b": {"c": None}}}), "Reponse")
    assert problemes == ["Reponse.a.b.c : jamais renseigne (type deduit `null`)"]
