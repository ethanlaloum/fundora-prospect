"""Le filtrage partage : `motif_ecart` et `repartir`.

## Pourquoi ces tests existent

Cette etape est le seul endroit ou se decide **pourquoi une annonce n'est pas
un candidat**. Elle est partagee par la recherche en direct et par le job de
collecte, precisement pour que les deux ne puissent pas diverger.

Or ce qui divergerait n'est pas la boucle — trois `if` — c'est le
**vocabulaire des motifs** et l'**ordre des tests**. Et ce vocabulaire n'etait
garde par rien : au moment de l'extraction, une mutation remplacant
`str(prix.qualification)` par la chaine `"ecarte"` a laisse les 436 tests
verts. Les tests existants verifiaient que `ecartes` etait non vide et que sa
somme etait positive, jamais ce qu'il y avait dedans.

Un motif ecrit « apport en nature » d'un cote et « apport » de l'autre casserait
tout comptage agregeant les deux sources, sans qu'aucun test ne rougisse. Ces
tests-ci ferment ce trou.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from fundora_prospect.bodacc import Annonce, Cedant
from fundora_prospect.pipeline import motif_ecart, repartir
from fundora_prospect.prix import Confiance, PrixCession, Qualification


def fabriquer_annonce(
    identifiant: str,
    montant: float | None,
    qualification: Qualification = Qualification.ACHAT,
    aberrant: bool = False,
) -> Annonce:
    jour = date.today() - timedelta(days=10)
    return Annonce(
        id=identifiant,
        date_parution=jour,
        date_acte=jour,
        departement="06",
        url_publication=f"https://www.bodacc.fr/x/{identifiant}",
        categorie_vente=None,
        activite=None,
        cedant=Cedant(denomination=identifiant, type_personne="pm", siren="852872563"),
        prix=PrixCession(
            montant=montant,
            devise="EUR",
            qualification=qualification,
            methode="test",
            texte_source="",
            confiance=Confiance.ACTE_DATE,
            ecart_acte_jours=0,
            aberrant=aberrant,
        ),
    )


# --- Le vocabulaire des motifs ------------------------------------------------


@pytest.mark.parametrize(
    ("qualification", "motif_attendu"),
    [
        (Qualification.APPORT, "apport"),
        (Qualification.DEVISE_OBSOLETE, "devise obsolete"),
        (Qualification.ACTE_TROP_ANCIEN, "acte trop ancien"),
        (Qualification.ABSENT, "absent"),
    ],
)
def test_chaque_qualification_non_retenue_a_son_motif_exact(
    qualification: Qualification, motif_attendu: str
) -> None:
    """Le motif est une CHAINE PUBLIQUE : elle sort dans le resume MCP, elle
    servira de valeur en base, et elle agrege des comptages venus de deux
    chemins. La verrouiller mot pour mot n'est pas du zele — c'est la seule
    facon d'empecher que les deux chemins comptent sous deux noms."""
    annonce = fabriquer_annonce("X", 300_000, qualification=qualification)
    assert motif_ecart(annonce) == motif_attendu


def test_un_achat_au_dessus_du_seuil_n_est_pas_ecarte() -> None:
    assert motif_ecart(fabriquer_annonce("X", 300_000), montant_min=200_000) is None


def test_le_motif_du_montant_aberrant_est_distinct() -> None:
    """Un montant aberrant n'est pas « absent » : on ignore s'il est juste, ce
    qui n'est pas la meme chose que ne pas l'avoir trouve."""
    annonce = fabriquer_annonce("X", 99_000_000, aberrant=True)
    assert motif_ecart(annonce) == "montant aberrant"


# --- L'ordre des tests --------------------------------------------------------


def test_un_apport_sous_le_seuil_est_compte_comme_apport() -> None:
    """L'ordre decide quel motif est compte quand une annonce en cumule
    plusieurs. Un apport a 3 000 EUR est un APPORT — le cedant recoit des parts
    sociales, pas du cash (contrainte 6) — et non un montant insuffisant.

    Compter l'inverse rangerait un refus de regle metier dans une categorie
    reglable, et relever le seuil ferait disparaitre le motif reel.
    """
    annonce = fabriquer_annonce("X", 3_000, qualification=Qualification.APPORT)
    assert motif_ecart(annonce, montant_min=200_000) == "apport"


def test_un_montant_aberrant_prime_sur_le_seuil() -> None:
    annonce = fabriquer_annonce("X", 99_000_000, aberrant=True)
    assert motif_ecart(annonce, montant_min=200_000) == "montant aberrant"


# --- La repartition -----------------------------------------------------------


def test_rien_ne_se_perd_entre_les_candidats_et_les_ecartes() -> None:
    """L'invariant qui rend le decompte opposable : toute annonce entree
    ressort d'un cote ou de l'autre. Une annonce qui disparaitrait des deux
    serait invisible — ni retenue, ni refusee, ni comptee."""
    corpus = [
        fabriquer_annonce("RETENUE-1", 300_000),
        fabriquer_annonce("RETENUE-2", 800_000),
        fabriquer_annonce("APPORT", 500_000, qualification=Qualification.APPORT),
        fabriquer_annonce("FRANCS", 400_000, qualification=Qualification.DEVISE_OBSOLETE),
        fabriquer_annonce("PETITE", 50_000),
    ]
    candidats, ecartes = repartir(corpus, montant_min=200_000)

    assert len(candidats) + sum(ecartes.values()) == len(corpus)
    assert {a.id for a in candidats} == {"RETENUE-1", "RETENUE-2"}
    assert ecartes == {"apport": 1, "devise obsolete": 1, "sous le montant minimum": 1}


def test_sans_seuil_aucune_annonce_n_est_ecartee_sur_le_montant() -> None:
    """C'est le mode du job de collecte : il ramasse tout, et le seuil devient
    un filtre de LECTURE. Sinon relever le seuil imposerait une recollecte."""
    corpus = [fabriquer_annonce("PETITE", 1_500), fabriquer_annonce("GROSSE", 900_000)]
    candidats, ecartes = repartir(corpus)

    assert len(candidats) == 2
    assert "sous le montant minimum" not in ecartes
