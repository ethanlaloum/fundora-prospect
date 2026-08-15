"""Client BODACC : depliage, extraction du cedant, filtres.

Les fixtures viennent des vraies APIs puis sont anonymisees — pas de mock
invente a la main. Elles conservent la FORME de l'API (sous-objets encodes en
JSON-string) pour que le depliage soit reellement exerce.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fundora_prospect.bodacc import (
    Annonce,
    construire_annonce,
    deplier,
    etablissements,
    extraire_cedant,
    normaliser_siren,
    personnes_precedentes,
)
from fundora_prospect.prix import Qualification

FIXTURES = Path(__file__).parent / "fixtures"


def cas(nom: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / f"{nom}.json").read_text(encoding="utf-8"))


# --- Depliage des sous-objets JSON-string ------------------------------------


def test_deplier_decode_les_sous_objets_encodes() -> None:
    assert deplier('{"a": 1}') == {"a": 1}
    assert deplier('[{"a": 1}]') == [{"a": 1}]


def test_deplier_laisse_passer_le_texte_ordinaire() -> None:
    assert deplier("Etablissement principal") == "Etablissement principal"
    assert deplier(None) is None
    assert deplier(42) == 42


def test_deplier_ne_casse_pas_sur_un_json_malforme() -> None:
    assert deplier("{ceci n'est pas du json") == "{ceci n'est pas du json"


# --- `etablissement` : tantot objet, tantot liste ----------------------------


def test_etablissement_unique_est_normalise_en_liste() -> None:
    annonce = cas("achat_cedant_pm")[0]
    assert isinstance(etablissements(annonce), list)
    assert len(etablissements(annonce)) == 1


def test_etablissements_multiples_sont_tous_retournes() -> None:
    for annonce in cas("multi_etablissements"):
        assert len(etablissements(annonce)) > 1


def test_annonce_sans_etablissement_donne_une_liste_vide() -> None:
    for annonce in cas("sans_etablissement"):
        assert etablissements(annonce) == []


# --- SIREN -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("325 662 559", "325662559"),
        ("325662559", "325662559"),
        (" 338 233 091 ", "338233091"),
        ("", None),
        (None, None),
        ("12345", None),  # trop court
        ("ABC123456", None),  # non numerique
    ],
)
def test_normaliser_siren(brut: str | None, attendu: str | None) -> None:
    assert normaliser_siren(brut) == attendu


# --- Cedant ------------------------------------------------------------------


def test_cedant_personne_morale() -> None:
    cedant = extraire_cedant(cas("achat_cedant_pm")[0])
    assert cedant is not None
    assert cedant.type_personne == "pm"
    assert cedant.denomination


def test_cedant_personne_physique_est_identifie_comme_tel() -> None:
    """Segment secondaire : base legale distincte, il doit rester distinguable."""
    cedant = extraire_cedant(cas("achat_cedant_pp")[0])
    assert cedant is not None
    assert cedant.type_personne == "pp"


def test_absence_de_cedant_donne_none() -> None:
    for annonce in cas("sans_cedant"):
        assert extraire_cedant(annonce) is None


def test_personne_en_liste_est_geree() -> None:
    """`listeprecedentproprietaire.personne` est tantot un objet, tantot une
    liste (indivision, 1,6 % du flux)."""
    for annonce in cas("cedants_multiples"):
        assert len(personnes_precedentes(annonce)) > 1
        assert extraire_cedant(annonce) is not None


# --- Construction de l'annonce ------------------------------------------------


def test_annonce_sans_cedant_est_ecartee() -> None:
    """13 % du flux : des mises en activite, pas des cessions. Aucun cedant,
    donc aucun prospect."""
    for annonce in cas("sans_cedant"):
        assert construire_annonce(annonce) is None


def test_annonce_complete_porte_sa_provenance() -> None:
    """Contrainte 3 : tracabilite. `url_complete` est fournie nativement."""
    annonce = construire_annonce(cas("achat_cedant_pm")[0])
    assert isinstance(annonce, Annonce)
    assert annonce.url_publication.startswith("https://www.bodacc.fr/")
    assert annonce.id
    assert isinstance(annonce.date_parution, date)
    assert annonce.departement


def test_le_prix_est_qualifie_dans_l_annonce() -> None:
    annonce = construire_annonce(cas("achat_cedant_pm")[0])
    assert annonce is not None
    assert annonce.prix.qualification is Qualification.ACHAT
    assert annonce.prix.montant is not None


def test_apport_donne_une_annonce_non_retenue() -> None:
    retenues = [
        a for brut in cas("apport_en_nature") if (a := construire_annonce(brut)) is not None
    ]
    assert retenues, "les fixtures d'apport doivent produire des annonces"
    assert all(not a.prix.retenu for a in retenues)


def test_francs_donne_une_annonce_non_retenue() -> None:
    for brut in cas("devise_francs"):
        annonce = construire_annonce(brut)
        if annonce is None or annonce.prix.qualification is Qualification.ABSENT:
            continue
        assert not annonce.prix.retenu


def test_multi_etablissements_est_marque_ambigu() -> None:
    """0,1 % du flux : sous le seuil de 5 %, on marque et on passe plutot que
    d'implementer la somme conditionnelle."""
    for brut in cas("multi_etablissements"):
        annonce = construire_annonce(brut)
        if annonce is None:
            continue
        assert annonce.ambigu
        assert not annonce.prix.retenu


def test_annonce_mono_etablissement_n_est_pas_ambigue() -> None:
    annonce = construire_annonce(cas("achat_cedant_pm")[0])
    assert annonce is not None
    assert not annonce.ambigu


def test_la_date_d_acte_est_remontee_quand_elle_existe() -> None:
    """Elle sert au garde du parser, et a la fraicheur du scoring en Phase 2.

    La fixture `acte_datable_recent` existe pour que ce test ne puisse pas
    passer a vide : sans elle, la liste etait vide et l'assertion jamais
    evaluee — un test vacuous qui donnait l'illusion d'une couverture.
    """
    datees = [
        a for brut in cas("acte_datable_recent") if (a := construire_annonce(brut)) is not None
    ]
    assert datees, "la fixture acte_datable_recent doit produire des annonces"
    for annonce in datees:
        assert isinstance(annonce.date_acte, date), f"{annonce.id} sans date d'acte"
        assert annonce.prix.ecart_acte_jours is not None
        assert annonce.prix.retenu


def test_toutes_les_fixtures_se_construisent_sans_exception() -> None:
    """Aucun cas limite du corpus ne doit faire planter le client."""
    for fichier in sorted(FIXTURES.glob("*.json")):
        for brut in json.loads(fichier.read_text(encoding="utf-8")):
            construire_annonce(brut)
