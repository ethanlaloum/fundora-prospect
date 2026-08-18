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

from fundora_prospect.bodacc import Annonce, Cedant, ResultatRecherche
from fundora_prospect.enrichment import Enrichissement
from fundora_prospect.entrepot import EvenementStocke
from fundora_prospect.models import LiquidityEvent, StatutEntreprise
from fundora_prospect.pipeline import (
    executer,
    lire,
    motif_ecart,
    motif_ecart_evenement,
    repartir,
    resumer,
)
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


# --- Les compteurs comptent bien leur population ------------------------------


def test_les_exploitables_ne_sont_pas_les_candidats() -> None:
    """`annonces_exploitables` n'etait asserte que sur un corpus ou TOUTES les
    annonces etaient des candidates. Les deux grandeurs y sont egales, donc le
    test ne pouvait pas les distinguer : remplacer `len(annonces)` par
    `len(candidats)` laissait les 446 tests verts.

    Un test qui ne peut pas distinguer deux valeurs ne garde ni l'une ni
    l'autre. Il faut construire le cas ou elles different — ici deux apports,
    exploitables mais jamais candidats.

    L'enjeu n'est pas theorique : c'est le compteur ne au constat que
    `annonces_examinees` annoncait 458 pour une population de 662.
    """
    corpus = [
        fabriquer_annonce("VENTE-1", 300_000),
        fabriquer_annonce("VENTE-2", 400_000),
        fabriquer_annonce("VENTE-3", 500_000),
        fabriquer_annonce("APPORT-1", 600_000, qualification=Qualification.APPORT),
        fabriquer_annonce("APPORT-2", 700_000, qualification=Qualification.APPORT),
    ]
    resultat = executer(
        departements=["06"],
        rechercher=lambda **_: ResultatRecherche(
            annonces=corpus, publiees=len(corpus), rapatriees=len(corpus)
        ),
        enrichir=lambda siren, **_: Enrichissement(
            siren=str(siren or ""), statut=StatutEntreprise.ACTIVE, motif="fixture"
        ),
    )
    stats = resultat.statistiques

    assert stats["annonces_exploitables"] == 5, "les apports restent exploitables"
    assert stats["candidats_avant_enrichissement"] == 3, "ils ne sont pas candidats"
    assert stats["ecartes"]["apport"] == 2


# --- Le vocabulaire est-il le MEME des deux cotes ? ---------------------------


@pytest.mark.parametrize(
    "qualification",
    [
        Qualification.ACHAT,
        Qualification.APPORT,
        Qualification.DEVISE_OBSOLETE,
        Qualification.ACTE_TROP_ANCIEN,
        Qualification.ABSENT,
    ],
)
@pytest.mark.parametrize("montant_min", [0.0, 200_000.0, 10_000_000.0])
def test_les_deux_chemins_nomment_un_refus_a_l_identique(
    qualification: Qualification, montant_min: float
) -> None:
    """**Le test anti-divergence.**

    La collecte part d'une `Annonce` fraiche, la lecture d'un `LiquidityEvent`
    relu en base. Deux types differents portant les memes faits — donc deux
    occasions de nommer le meme refus de deux facons.

    Un motif ecrit « apport en nature » d'un cote et « apport » de l'autre
    casserait tout comptage agregeant les deux sources, et aucun test de l'un
    ou l'autre chemin pris separement ne rougirait. Seule leur COMPARAISON le
    voit.

    Le produit cartesien couvre les cinq qualifications et trois seuils, dont
    un qui mord sur tout et un qui ne mord sur rien : sans le seuil eleve, le
    motif « sous le montant minimum » ne serait jamais compare.
    """
    annonce = fabriquer_annonce("X", 300_000, qualification=qualification)
    event = LiquidityEvent.depuis_annonce(annonce)

    assert motif_ecart(annonce, montant_min) == motif_ecart_evenement(event, montant_min)


# --- La lecture : le score n'est pas fige -------------------------------------


def stocke(
    identifiant: str,
    montant: float,
    jours_acte: int,
    statut: StatutEntreprise = StatutEntreprise.ACTIVE,
    qualification: Qualification = Qualification.ACHAT,
    collecte: date = date(2026, 8, 16),
    reference: date = date(2026, 8, 18),
) -> EvenementStocke:
    annonce = fabriquer_annonce(identifiant, montant, qualification=qualification)
    event = LiquidityEvent.depuis_annonce(annonce).model_copy(
        update={
            "date_acte": reference - timedelta(days=jours_acte),
            "date_parution": reference - timedelta(days=jours_acte),
            "statut_cedant": statut,
            "motif_enrichissement": "fixture",
        }
    )
    return EvenementStocke(event=event, date_collecte=collecte)


def test_deux_dates_de_lecture_donnent_deux_scores() -> None:
    """**Le test du palier.**

    Sans lui, « le score est recalcule a la lecture » est une intention : rien
    ne distingue un recalcul d'une valeur figee tant qu'on ne lit qu'une fois.

    La fraicheur decroit des le premier jour, demi-vie 180 jours, sans plateau
    (Phase 2). Deux lectures espacees de six mois sur LA MEME LIGNE doivent
    donc rendre deux scores, et le plus tardif doit etre le plus faible : le
    produit de cession a eu six mois de plus pour trouver une destination.

    C'est aussi ce qui justifie de n'avoir aucune colonne de score en base : un
    score stocke le 18 aout est faux le 19.
    """
    ligne = [stocke("CESSION", 400_000, jours_acte=10)]

    tot = lire(ligne, aujourdhui=date(2026, 8, 18))
    tard = lire(ligne, aujourdhui=date(2027, 2, 18))

    assert tot.leads[0]["score"] > tard.leads[0]["score"], (
        "un score identique a six mois d'ecart signifie qu'il est fige"
    )
    # Et le fait, lui, n'a pas bouge : c'est bien le score qui est recalcule.
    assert tot.leads[0]["montant_eur"] == tard.leads[0]["montant_eur"]
    assert tot.leads[0]["date_acte"] == tard.leads[0]["date_acte"]


def test_la_fraicheur_est_le_critere_qui_bouge() -> None:
    """Precision du test precedent : le score baisse PAR LA FRAICHEUR, pas par
    un effet de bord. Le breakdown doit le dire, contrainte 5."""
    ligne = [stocke("CESSION", 400_000, jours_acte=10)]

    def points(resultat: object, critere: str) -> float:
        breakdown = resultat.leads[0]["breakdown"]
        return next(c["points"] for c in breakdown if c["critere"] == critere)

    tot = lire(ligne, aujourdhui=date(2026, 8, 18))
    tard = lire(ligne, aujourdhui=date(2027, 2, 18))

    assert points(tard, "fraicheur") < points(tot, "fraicheur")
    assert points(tard, "montant") == points(tot, "montant")


def test_la_provenance_relue_porte_la_date_de_collecte_pas_celle_du_jour() -> None:
    """Une provenance qui annoncerait la date de lecture pretendrait qu'on vient
    de consulter le BODACC. La contrainte 3 demande une date de collecte."""
    resultat = lire(
        [stocke("CESSION", 400_000, jours_acte=10, collecte=date(2026, 8, 16))],
        aujourdhui=date(2027, 2, 18),
    )
    assert resultat.leads[0]["provenance"]["date_collecte"] == "2026-08-16"


# --- La lecture : les refus gardent leur vocabulaire --------------------------


def test_le_seuil_de_montant_produit_le_meme_motif_qu_a_la_collecte() -> None:
    """Le motif rendu par la lecture doit etre mot pour mot celui de la
    collecte, sinon un decompte agregeant les deux sources compte deux fois
    sous deux noms."""
    resultat = lire(
        [stocke("GROSSE", 400_000, 10), stocke("PETITE", 50_000, 10)],
        montant_min=200_000,
    )
    assert resultat.statistiques["ecartes"] == {"sous le montant minimum": 1}
    assert {lead["cedant"] for lead in resultat.leads} == {"GROSSE"}


def test_une_societe_cessee_est_ecartee_a_la_lecture_avec_son_motif() -> None:
    """La porte du statut vaut a la lecture comme a la collecte : une societe
    cessee n'est pas « un peu moins bonne », la personne morale n'existe plus.
    Et elle sort AVEC son motif — un lead supprime serait indetectable, un lead
    ecarte est auditable."""
    resultat = lire(
        [
            stocke("VIVANTE", 400_000, 10),
            stocke("CESSEE", 900_000, 10, statut=StatutEntreprise.CESSEE),
        ]
    )
    assert {lead["cedant"] for lead in resultat.leads} == {"VIVANTE"}
    assert resultat.statistiques["ecartes"]["societe cedante cessee"] == 1


def test_les_leads_relus_sortent_tries_par_score() -> None:
    resultat = lire([stocke(f"C{i}", 200_000 + i * 100_000, 10) for i in range(5)])
    scores = [lead["score"] for lead in resultat.leads]
    assert scores == sorted(scores, reverse=True)


def test_la_troncature_a_la_lecture_n_est_pas_un_refus() -> None:
    """Meme regle qu'en direct : `classables` se compte AVANT la coupe, sinon
    une troncature se lit comme un jugement de la grille."""
    resultat = lire([stocke(f"C{i}", 300_000 + i * 1_000, 10) for i in range(6)], limite=2)
    stats = resultat.statistiques

    assert stats["candidats"] == 6
    assert stats["classables"] == 6
    assert stats["leads_rendus"] == 2
    assert stats["ecartes"] == {}, "aucun refus de la grille ici"


# --- Le resume vient de `resumer`, des deux cotes ------------------------------


def test_le_resume_de_lecture_porte_ses_referents() -> None:
    """`resumer` est la seule redaction du projet. Cote lecture, la condition
    d'obtention n'est pas la meme qu'en direct — la grille voit tous les
    candidats, pas seulement les enrichis — donc le referent change, mais la
    phrase se fabrique au meme endroit.
    """
    resultat = lire(
        [stocke(f"C{i}", 300_000 + i * 1_000, 10) for i in range(6)]
        + [stocke("PETITE", 50_000, 10)],
        montant_min=200_000,
        limite=2,
    )
    resume = resumer(resultat.statistiques)

    assert "7 evenements en base" in resume
    assert "6 classables sur 6 candidats" in resume
    assert "1 sous le montant minimum" in resume
    assert "2 rendus sur 6 classables sur 6 candidats (limite atteinte)" in resume

    # Regle 1 des lecons du projet : un chiffre ne s'ecrit jamais sans son
    # referent. Verifiee sur CHAQUE occurrence, comme cote MCP.
    for suite in resume.split("classables")[1:]:
        assert suite.startswith(" sur "), f"« classables » sans son referent : {resume!r}"


def test_le_resume_de_lecture_dit_qu_il_ignore_l_etendue_de_la_collecte() -> None:
    """Une base ne sait pas, par elle-meme, ce qu'elle n'a pas recu. Sans cette
    reserve, un stock se lirait comme un total — exactement ce que
    `annonces_examinees` faisait en annoncant 458 pour 662."""
    resume = resumer(lire([stocke("C", 400_000, 10)]).statistiques)
    assert "l'etendue de la collecte n'est pas connue" in resume


def test_quand_les_compteurs_de_collecte_existent_la_reserve_disparait() -> None:
    """Une mise en garde affichee en permanence cesse d'etre lue : elle ne
    s'affiche que quand elle mord. Le job du palier 3 fournira ces compteurs."""
    resultat = lire(
        [stocke("C", 400_000, 10)],
        collecte={
            "annonces_publiees": 662,
            "annonces_rapatriees": 662,
            "annonces_exploitables": 1,
            "sans_cedant_ou_illisibles": 0,
            "plafond_atteint": False,
            "classables_parmi_les_enrichis": 1,
            "enrichis": 1,
        },
    )
    resume = resumer(resultat.statistiques)
    assert "662 annonces publiees" in resume
    assert "l'etendue de la collecte" not in resume
