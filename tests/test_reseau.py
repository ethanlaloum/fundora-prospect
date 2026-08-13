"""Tests reseau — exclus par defaut, lances par `pytest -m network`.

Ils mesurent le taux de parsing sur des donnees reelles. La mesure est le gate
de la Phase 1 : elle doit etre reproductible et affichee, pas affirmee.

Reference etablie en Phase 0 sur le sous-ensemble cedant personne morale,
avec un motif naif : 99,8 %. C'est ce chiffre qu'il faut au moins egaler.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pytest

from fundora_prospect.bodacc import (
    DEPARTEMENTS_PACA,
    Annonce,
    compter,
    construire_annonce,
    construire_where,
    rechercher_brut,
)
from fundora_prospect.http import creer_client
from fundora_prospect.prix import Qualification

pytestmark = pytest.mark.network

TAILLE_ECHANTILLON = 600


@pytest.fixture(scope="module")
def echantillon() -> list[dict]:
    """Echantillon reparti sur 12 mois : un tri par date decroissante ne
    ramenerait qu'une seule journee de parution et biaiserait la mesure."""
    aujourdhui = date.today()
    brut: list[dict] = []
    with creer_client() as client:
        for i in range(12):
            fin = date(aujourdhui.year, aujourdhui.month, 1) - timedelta(days=31 * i)
            debut = date(fin.year, fin.month, 1)
            suivant = date(
                debut.year + (debut.month == 12),
                1 if debut.month == 12 else debut.month + 1,
                1,
            )
            where = construire_where(DEPARTEMENTS_PACA, debut, suivant)
            brut.extend(rechercher_brut(client, where, TAILLE_ECHANTILLON // 12))
    return brut


@pytest.fixture(scope="module")
def annonces(echantillon: list[dict]) -> list[Annonce]:
    return [a for b in echantillon if (a := construire_annonce(b)) is not None]


def test_le_taux_de_parsing_sur_cedants_personne_morale(annonces: list[Annonce]) -> None:
    """Le segment principal porte tout le volume : c'est lui qui compte."""
    morales = [a for a in annonces if a.cedant.type_personne == "pm"]
    assert morales, "echantillon vide — l'API a-t-elle change ?"

    avec_montant = [a for a in morales if a.prix.montant is not None]
    taux = 100 * len(avec_montant) / len(morales)

    print(f"\n  cedants personne morale        : {len(morales)}")
    print(f"  montant extrait                : {len(avec_montant)} ({taux:.1f} %)")

    assert taux >= 95.0, f"taux de parsing tombe a {taux:.1f} % (reference Phase 0 : 99,8 %)"


def test_ventilation_des_motifs_de_rejet(annonces: list[Annonce]) -> None:
    """Un rejet motive est auditable ; un zero silencieux ne l'est pas."""
    motifs = Counter(a.prix.qualification for a in annonces)
    total = len(annonces)

    print(f"\n  Ventilation sur {total} annonces avec cedant :")
    for qualification, nombre in motifs.most_common():
        print(f"    {qualification.value:<22} {nombre:>5} ({100 * nombre / total:.1f} %)")

    retenues = motifs[Qualification.ACHAT]
    print(f"\n  retenues comme cession au comptant : {retenues} ({100 * retenues / total:.1f} %)")
    assert retenues > 0


def test_les_filtres_sans_cedant_et_sans_etablissement_ne_sont_pas_redondants(
    echantillon: list[dict],
) -> None:
    """Question laissee ouverte en Phase 0 : 13 % d'annonces sans cedant,
    12,7 % sans etablissement — les memes ou non ?"""
    from fundora_prospect.bodacc import etablissements, personnes_precedentes

    sans_cedant = {b["id"] for b in echantillon if not personnes_precedentes(b)}
    sans_etab = {b["id"] for b in echantillon if not etablissements(b)}

    print(f"\n  sans cedant          : {len(sans_cedant)}")
    print(f"  sans etablissement   : {len(sans_etab)}")
    print(f"  les deux             : {len(sans_cedant & sans_etab)}")
    print(f"  sans etab MAIS avec cedant : {len(sans_etab - sans_cedant)}")
    print(f"  sans cedant MAIS avec etab : {len(sans_cedant - sans_etab)}")


def test_volume_reel_des_cessions_au_dessus_de_200k(annonces: list[Annonce]) -> None:
    """Le chiffre du README : volume mesure, pas estime."""
    retenues = [a for a in annonces if a.prix.retenu and a.prix.montant]
    grosses = [a for a in retenues if a.prix.montant and a.prix.montant > 200_000]
    morales = [a for a in grosses if a.cedant.type_personne == "pm"]

    with creer_client() as client:
        aujourdhui = date.today()
        total_12_mois = compter(
            client,
            construire_where(
                DEPARTEMENTS_PACA,
                aujourdhui - timedelta(days=365),
                aujourdhui,
            ),
        )

    part = len(morales) / len(annonces) if annonces else 0
    print(f"\n  annonces `vente` PACA sur 12 mois     : {total_12_mois:,}")
    print(f"  echantillon exploite                  : {len(annonces)}")
    print(f"  cessions > 200 k EUR, cedant pm       : {len(morales)} ({100 * part:.1f} %)")
    print(f"  => extrapolation annuelle PACA        : ~{round(total_12_mois * part):,}")

    assert retenues, "aucune cession retenue — le parser a regresse"
