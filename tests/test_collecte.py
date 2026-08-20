"""Le job de collecte et ses deux journaux — paliers 3, 4 et 5.

Palier 3, trois choses a prouver, et la premiere n'etait jusqu'ici qu'une
phrase :

1. **Le TTL.** « 30 jours pour les actives, jamais de re-enrichissement des
   cessees » etait ecrit dans CLAUDE.md avec sa propre reserve : *c'est une
   affirmation tant qu'un test ne la prouve pas*. Deux assertions distinctes,
   parce que ce sont deux regles distinctes — l'une est un delai, l'autre est
   une regle metier sans delai.
2. **La reprise.** Un balayage coupe laisse une ligne `collecte` sans
   `terminee_a`. Ses compteurs sous-estiment, et la lecture doit le dire :
   sinon c'est le plafond de rapatriement compte comme la totalite, deplace
   d'un cran.
3. **La deduplication par SIREN**, qui est le gain d'appels du design. Un
   chiffre qu'on annonce doit etre un chiffre qu'on mesure.

Paliers 4 et 5, une seule propriete sous deux formes : **les journaux
n'ecrivent que sur un CHANGEMENT REEL.** C'est ce qui les rend lisibles, et
c'est ce qui est le plus facile a casser sans qu'un test s'en apercoive — une
table non vide a l'air d'une table qui fonctionne.

Sept mutations y ont survecu au premier passage. Deux causes, toutes deux deja
nommees dans CLAUDE.md et rencontrees quand meme :

- **des corpus qui ne separaient pas** deux grandeurs proches (toutes les
  transitions a la meme date, tous les evenements neufs) ;
- **des valeurs jamais assertees** — `motif`, `evenements_nouveaux` — dont il
  suffisait qu'elles existent.

D'ou la forme des tests ci-dessous : trois balayages a trois dates plutot que
deux, un second passage qui reecrit une ligne connue, et un test structurel
pour `COLONNES_DE_FAIT` — parce qu'un test parametre sur trois colonnes en
laisse dix sans garde tout en s'appelant « chaque colonne ».
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from fundora_prospect import collecte, entrepot, provenance
from fundora_prospect.bodacc import Annonce, Cedant, ResultatRecherche
from fundora_prospect.enrichment import Enrichissement
from fundora_prospect.models import Evaluation, Lead, LiquidityEvent, StatutEntreprise
from fundora_prospect.pipeline import lire, resumer
from fundora_prospect.prix import Confiance, PrixCession, Qualification

AUJOURDHUI = date(2026, 8, 18)


def annonce(
    identifiant: str,
    siren: str | None = "852872563",
    montant: float = 400_000.0,
    qualification: Qualification = Qualification.ACHAT,
    departement: str = "06",
    url: str | None = None,
) -> Annonce:
    jour = AUJOURDHUI - timedelta(days=20)
    return Annonce(
        id=identifiant,
        date_parution=jour,
        date_acte=jour,
        departement=departement,
        url_publication=f"https://www.bodacc.fr/x/{identifiant}" if url is None else url,
        categorie_vente=None,
        activite=None,
        cedant=Cedant(denomination=f"CEDANT {identifiant}", type_personne="pm", siren=siren),
        prix=PrixCession(
            montant=montant,
            devise="EUR",
            qualification=qualification,
            methode="test",
            texte_source="",
            confiance=Confiance.ACTE_DATE,
            ecart_acte_jours=0,
        ),
    )


@pytest.fixture
def base(tmp_path: Path) -> sqlite3.Connection:
    connexion = entrepot.ouvrir(tmp_path / "essai.db")
    yield connexion
    connexion.close()


class Compteur:
    """Un `enrichir` qui retient qui il a appele. Le nombre d'appels EST la
    mesure du design : le compter est le seul moyen de savoir si la
    deduplication opere."""

    def __init__(
        self,
        statut: StatutEntreprise = StatutEntreprise.ACTIVE,
        motif: str = "fixture",
    ) -> None:
        self.appels: list[str] = []
        self.statut = statut
        # Le motif est reglable pour qu'un test puisse le distinguer du statut :
        # les deux sont des chaines non vides, et les confondre en base
        # resterait plausible a la lecture.
        self.motif = motif

    def __call__(self, siren: str, **_: object) -> Enrichissement:
        self.appels.append(str(siren))
        return Enrichissement(
            siren=str(siren), statut=self.statut, code_ape="56.10A",
            section_ape="I", motif=self.motif,
        )


def fabriquer_lead_v2(identifiant: str = "A1") -> Lead:
    """Un `Lead` monte directement, sans passer par le job — pour les tests de
    migration, qui doivent ecrire dans une base avant de la faire evoluer."""
    event = LiquidityEvent.depuis_annonce(annonce(identifiant))
    return provenance.assembler(
        event,
        Evaluation(event_id=event.id, classable=False, motif_refus="non classe"),
        date_collecte=AUJOURDHUI,
    )


def recherche_de(annonces: list[Annonce], publiees: int | None = None) -> ResultatRecherche:
    total = len(annonces) if publiees is None else publiees
    return ResultatRecherche(annonces=annonces, publiees=total, rapatriees=total)


# --- 1. Le TTL ----------------------------------------------------------------


def enregistrer_cedant(
    base: sqlite3.Connection, siren: str, statut: StatutEntreprise, enrichi_a: date
) -> None:
    base.execute(
        "INSERT INTO cedant (siren, statut, motif, enrichi_a) VALUES (?, ?, ?, ?)",
        (siren, str(statut), "fixture", enrichi_a.isoformat()),
    )
    base.commit()


@pytest.mark.parametrize("age", [30, 31, 90, 400])
def test_une_active_perimee_est_reenrichie(base: sqlite3.Connection, age: int) -> None:
    """Un statut se perime : une societe active il y a plus de 30 jours peut
    avoir cesse depuis. C'est le seul champ de l'enrichissement qui bouge."""
    enregistrer_cedant(
        base, "852872563", StatutEntreprise.ACTIVE, AUJOURDHUI - timedelta(days=age)
    )
    assert entrepot.sirens_a_enrichir(
        base, ["852872563"], aujourdhui=AUJOURDHUI
    ) == ["852872563"]


@pytest.mark.parametrize("age", [0, 1, 29])
def test_une_active_fraiche_n_est_pas_resondee(base: sqlite3.Connection, age: int) -> None:
    """L'autre moitie du seuil. Sans ce cas, un TTL de zero jour passerait le
    test precedent — les deux bornes doivent etre exercees pour que le seuil
    soit garde, pas seulement franchi."""
    enregistrer_cedant(
        base, "852872563", StatutEntreprise.ACTIVE, AUJOURDHUI - timedelta(days=age)
    )
    assert entrepot.sirens_a_enrichir(base, ["852872563"], aujourdhui=AUJOURDHUI) == []


@pytest.mark.parametrize("age", [0, 1, 29, 30, 31, 400, 5_000])
def test_une_cessee_n_est_jamais_reenrichie(base: sqlite3.Connection, age: int) -> None:
    """**La regle metier, verrouillee.**

    Une personne morale radiee ne redevient pas active. Resonder son SIREN est
    un appel API garanti sans information — pas une precaution.

    Le parametrage couvre delibérement des ages DE PART ET D'AUTRE du seuil de
    30 jours, jusqu'a treize ans. Un test qui ne montrerait qu'une cessee
    fraiche serait vert meme si la regle etait « cessee = pas encore perimee » :
    on ne saurait pas si c'est le statut ou le delai qui l'a protegee. C'est la
    famille du corpus degenere, appliquee a un parametre.
    """
    enregistrer_cedant(
        base, "852872563", StatutEntreprise.CESSEE, AUJOURDHUI - timedelta(days=age)
    )
    assert entrepot.sirens_a_enrichir(base, ["852872563"], aujourdhui=AUJOURDHUI) == []


def test_un_siren_jamais_vu_est_enrichi(base: sqlite3.Connection) -> None:
    assert entrepot.sirens_a_enrichir(
        base, ["404833048"], aujourdhui=AUJOURDHUI
    ) == ["404833048"]


def test_le_ttl_distingue_les_statuts_dans_un_meme_lot(base: sqlite3.Connection) -> None:
    """Le cas qui compte vraiment : les trois populations dans le meme appel.
    Un test par statut isole ne prouve pas que la regle discrimine."""
    vieux = AUJOURDHUI - timedelta(days=200)
    enregistrer_cedant(base, "111111111", StatutEntreprise.ACTIVE, vieux)
    enregistrer_cedant(base, "222222222", StatutEntreprise.CESSEE, vieux)
    enregistrer_cedant(base, "333333333", StatutEntreprise.ACTIVE, AUJOURDHUI)
    enregistrer_cedant(base, "444444444", StatutEntreprise.INCONNU, vieux)

    a_faire = entrepot.sirens_a_enrichir(
        base,
        ["111111111", "222222222", "333333333", "444444444", "555555555"],
        aujourdhui=AUJOURDHUI,
    )
    assert a_faire == ["111111111", "444444444", "555555555"]


def test_le_job_ne_resonde_pas_une_cessee(base: sqlite3.Connection) -> None:
    """La regle doit tenir DANS le job, pas seulement dans la fonction qui la
    porte. Un balayage qui contournerait `sirens_a_enrichir` la perdrait."""
    enregistrer_cedant(
        base, "852872563", StatutEntreprise.CESSEE, AUJOURDHUI - timedelta(days=900)
    )
    compteur = Compteur()
    collecte.balayer(
        base,
        departements=["06"],
        aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de([annonce("A1")]),
        enrichir=compteur,
    )
    assert compteur.appels == [], "une cessee ne doit declencher aucun appel"


# --- 2. La deduplication par SIREN --------------------------------------------


def test_un_siren_cite_dix_fois_ne_coute_qu_un_appel(base: sqlite3.Connection) -> None:
    """Le gain du design. Le statut est une propriete de la SOCIETE : dix
    annonces du meme cedant rendraient dix fois la meme reponse."""
    corpus = [annonce(f"A{i}", siren="852872563") for i in range(10)]
    compteur = Compteur()
    resultat = collecte.balayer(
        base,
        departements=["06"],
        aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus),
        enrichir=compteur,
    )

    assert len(compteur.appels) == 1
    assert resultat.enrichissements == 1
    assert resultat.enrichissements_evites == 9
    assert resultat.economie == pytest.approx(0.9)
    assert resultat.evenements_ecrits == 10, "les dix evenements sont ecrits"

    # `cedants_distincts` compte des SOCIETES, pas des citations. Sans cette
    # assertion, retirer le dedoublonnage du job passait inapercu : les appels
    # API restaient corrects — `sirens_a_enrichir` dedoublonne aussi — mais le
    # compteur annoncait 10 societes la ou il n'y en a qu'une. Un compteur
    # nomme d'apres une population doit etre calcule sur cette population.
    assert resultat.cedants_distincts == 1


def test_un_second_balayage_ne_reenrichit_rien(base: sqlite3.Connection) -> None:
    """Idempotence : relancer le job le meme jour ne redemande rien a l'API."""
    corpus = [annonce("A1"), annonce("A2", siren="404833048")]
    premier = Compteur()
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=premier,
    )
    second = Compteur()
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=second,
    )

    assert len(premier.appels) == 2
    assert second.appels == []
    assert base.execute("SELECT count(*) FROM evenement").fetchone()[0] == 2


def test_un_statut_deja_connu_n_est_pas_efface(base: sqlite3.Connection) -> None:
    """Un SIREN qu'on ne resonde pas doit garder son statut : la ligne `cedant`
    est reecrite depuis le `Lead`, donc sans reinjecter ce qu'on sait, un
    second balayage repasserait tout le monde a INCONNU."""
    corpus = [annonce("A1")]
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=Compteur(),
    )
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=Compteur(),
    )
    assert base.execute("SELECT statut FROM cedant").fetchone()["statut"] == "active"


# --- 3. Ce que le job ecrit, et ce que la lecture en fait ---------------------


def test_le_job_ecrit_aussi_les_annonces_ecartees(base: sqlite3.Connection) -> None:
    """Sans les ecartees en base, leur decompte par motif cesserait d'etre
    recalculable a la lecture — et il faudrait une table pour le figer, qui
    deriverait au premier renommage."""
    corpus = [annonce("VENTE"), annonce("APPORT", qualification=Qualification.APPORT)]
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=Compteur(),
    )
    assert base.execute("SELECT count(*) FROM evenement").fetchone()[0] == 2

    resultat = lire(entrepot.evenements(base), aujourdhui=AUJOURDHUI)
    assert resultat.statistiques["ecartes"] == {"apport": 1}


def test_la_reserve_d_etendue_disparait_quand_le_job_a_tourne(
    base: sqlite3.Connection,
) -> None:
    """Les deux sens, avec la VRAIE source des compteurs.

    Le palier 2 le testait avec un dict ecrit a la main. Ici les compteurs
    viennent de la table que le job a remplie — c'est la seule facon de savoir
    si les deux morceaux s'emboitent reellement.
    """
    corpus = [annonce("A1")]
    avant = lire(entrepot.evenements(base), aujourdhui=AUJOURDHUI)
    assert "l'etendue de la collecte n'est pas connue" in resumer(avant.statistiques)

    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus, publiees=42), enrichir=Compteur(),
    )
    apres = lire(
        entrepot.evenements(base),
        aujourdhui=AUJOURDHUI,
        collecte=entrepot.compteurs_de_collecte(base),
    )
    resume = resumer(apres.statistiques)

    assert "42 annonces publiees" in resume
    assert "l'etendue de la collecte n'est pas connue" not in resume
    # Le referent de « classables » reste celui de la lecture : la grille a vu
    # tous les candidats, pas seulement un budget d'enrichis.
    assert "classables sur 1 candidats" in resume


def test_une_collecte_interrompue_ne_se_presente_pas_comme_complete(
    base: sqlite3.Connection,
) -> None:
    """**Le test de reprise.**

    Un balayage coupe au milieu laisse une ligne avec `terminee_a` a NULL. Ses
    compteurs sous-estiment ce que la source contenait. Les servir sans reserve
    serait exactement le defaut du plafond de rapatriement compte comme la
    totalite — un sous-ensemble presente comme un total.
    """
    entrepot.demarrer_collecte(
        base, lot="interrompu", departement="06",
        fenetre_debut=date(2025, 9, 1), fenetre_fin=AUJOURDHUI, lancee_a=AUJOURDHUI,
    )
    compteurs = entrepot.compteurs_de_collecte(base)

    assert compteurs is not None
    assert compteurs["collecte_partielle"] is True

    resume = resumer(
        lire(entrepot.evenements(base), aujourdhui=AUJOURDHUI, collecte=compteurs).statistiques
    )
    assert "n'est pas allee au bout" in resume


def test_une_collecte_terminee_ne_porte_pas_la_reserve(base: sqlite3.Connection) -> None:
    """L'autre sens : une reserve affichee en permanence cesse d'etre lue."""
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de([annonce("A1")]), enrichir=Compteur(),
    )
    compteurs = entrepot.compteurs_de_collecte(base)
    assert compteurs is not None
    assert compteurs["collecte_partielle"] is False

    resume = resumer(
        lire(entrepot.evenements(base), aujourdhui=AUJOURDHUI, collecte=compteurs).statistiques
    )
    assert "n'est pas allee au bout" not in resume


def test_une_reprise_apres_interruption_ferme_la_reserve(base: sqlite3.Connection) -> None:
    """Relancer le job apres une coupure doit rendre les compteurs complets.

    La ligne interrompue reste en base — c'est une trace, on ne la reecrit
    pas — mais `compteurs_de_collecte` ne retient que la DERNIERE par
    departement. Sans cette regle, une vieille coupure marquerait toutes les
    lectures suivantes comme partielles.
    """
    entrepot.demarrer_collecte(
        base, lot="interrompu", departement="06",
        fenetre_debut=date(2025, 9, 1), fenetre_fin=AUJOURDHUI, lancee_a=AUJOURDHUI,
    )
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de([annonce("A1")]), enrichir=Compteur(),
    )
    compteurs = entrepot.compteurs_de_collecte(base)

    assert compteurs is not None
    assert compteurs["collecte_partielle"] is False
    assert base.execute("SELECT count(*) FROM collecte").fetchone()[0] == 2, (
        "la ligne interrompue reste : c'est une trace"
    )


def test_les_compteurs_ne_s_additionnent_pas_entre_deux_passages(
    base: sqlite3.Connection,
) -> None:
    """Le job tourne periodiquement. Additionner les passages compterait
    plusieurs fois les memes annonces publiees, et le total gonflerait a chaque
    execution sans que rien n'ait change dans la source."""
    for jour in (AUJOURDHUI - timedelta(days=1), AUJOURDHUI):
        collecte.balayer(
            base, departements=["06"], aujourdhui=jour,
            rechercher=lambda **_: recherche_de([annonce("A1")], publiees=42),
            enrichir=Compteur(),
        )
    compteurs = entrepot.compteurs_de_collecte(base)
    assert compteurs is not None
    assert compteurs["annonces_publiees"] == 42, "la derniere, pas la somme"


def test_le_balayage_couvre_chaque_departement_demande(base: sqlite3.Connection) -> None:
    """Le perimetre est un parametre des maintenant : PACA en defaut, mais
    l'elargissement ne doit pas demander de refactoring."""
    vus: list[str] = []

    def rechercher(**kwargs: object) -> ResultatRecherche:
        departement = list(kwargs["departements"])[0]  # type: ignore[index]
        vus.append(departement)
        return recherche_de([annonce(f"A-{departement}", departement=departement)])

    resultat = collecte.balayer(
        base, departements=["06", "13", "83"], aujourdhui=AUJOURDHUI,
        rechercher=rechercher, enrichir=Compteur(),
    )
    assert vus == ["06", "13", "83"]
    assert resultat.evenements_ecrits == 3
    assert base.execute("SELECT count(*) FROM collecte").fetchone()[0] == 3


def test_une_annonce_intracable_est_un_incident_pas_une_ligne(
    base: sqlite3.Connection,
) -> None:
    """La contrainte 3 vaut aussi a l'ecriture par le job : une annonce sans
    URL ne devient pas une ligne, et ne disparait pas en silence non plus."""
    corpus = [annonce("TRACABLE"), annonce("SANS-URL", url="")]
    resultat = collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=Compteur(),
    )
    assert resultat.evenements_ecrits == 1
    assert len(resultat.incidents) == 1
    assert "SANS-URL" in resultat.incidents[0]


def test_le_job_n_applique_aucun_seuil_de_montant(base: sqlite3.Connection) -> None:
    """Le seuil est un filtre de LECTURE. L'appliquer a la collecte obligerait
    a recollecter pour le relever."""
    corpus = [annonce("GROSSE", montant=900_000), annonce("PETITE", montant=5_000)]
    collecte.balayer(
        base, departements=["06"], aujourdhui=AUJOURDHUI,
        rechercher=lambda **_: recherche_de(corpus), enrichir=Compteur(),
    )
    assert base.execute("SELECT count(*) FROM evenement").fetchone()[0] == 2


# --- Migration ----------------------------------------------------------------


def test_ouvrir_une_base_v1_ajoute_la_table_collecte(tmp_path: Path) -> None:
    """Le schema est additif et ecrit en `IF NOT EXISTS` : ouvrir une base d'un
    palier precedent la complete sans rien detruire."""
    chemin = tmp_path / "v1.db"
    ancienne = sqlite3.connect(chemin)
    ancienne.executescript(
        "CREATE TABLE cedant (siren TEXT PRIMARY KEY, statut TEXT NOT NULL, "
        "code_ape TEXT, section_ape TEXT, motif TEXT NOT NULL, enrichi_a TEXT NOT NULL);"
        "PRAGMA user_version = 1;"
    )
    ancienne.close()

    connexion = entrepot.ouvrir(chemin)
    assert connexion.execute("PRAGMA user_version").fetchone()[0] == entrepot.VERSION_SCHEMA
    connexion.execute("SELECT count(*) FROM collecte")
    connexion.close()


# --- Palier 4 : le journal des transitions de statut --------------------------


def balayage(
    base: sqlite3.Connection,
    corpus: list[Annonce],
    statut: StatutEntreprise = StatutEntreprise.ACTIVE,
    jour: date = AUJOURDHUI,
    motif: str = "fixture",
) -> collecte.ResultatCollecte:
    return collecte.balayer(
        base, departements=["06"], aujourdhui=jour,
        rechercher=lambda **_: recherche_de(corpus), enrichir=Compteur(statut, motif),
    )


def test_une_premiere_observation_n_est_pas_une_transition(
    base: sqlite3.Connection,
) -> None:
    """Le journal porte des CHANGEMENTS. Une premiere observation n'en est pas
    un — `cedant.enrichi_a` la date deja. L'y ecrire ferait 3 263 lignes au
    premier balayage PACA, toutes sans information."""
    balayage(base, [annonce("A1")])
    assert entrepot.transitions(base) == []


def test_un_sondage_qui_confirme_n_ecrit_rien(base: sqlite3.Connection) -> None:
    """Le journal grossirait a chaque balayage en ne disant rien."""
    corpus = [annonce("A1")]
    balayage(base, corpus)
    # 40 jours plus tard : le TTL a expire, la societe est resondee ACTIVE.
    balayage(base, corpus, jour=AUJOURDHUI + timedelta(days=40))
    assert entrepot.transitions(base) == []


def test_une_bascule_active_vers_cessee_est_datee(base: sqlite3.Connection) -> None:
    """**Le signal metier du journal.** `active -> cessee` date le moment ou le
    produit de cession est descendu aux associes : c'est la date de sortie du
    prospect, pas une simple ligne d'audit."""
    corpus = [annonce("A1")]
    balayage(base, corpus)
    plus_tard = AUJOURDHUI + timedelta(days=40)
    resultat = balayage(base, corpus, statut=StatutEntreprise.CESSEE, jour=plus_tard)

    changements = entrepot.transitions(base)
    assert len(changements) == 1
    transition = changements[0]
    assert transition.siren == "852872563"
    assert transition.statut_avant is StatutEntreprise.ACTIVE
    assert transition.statut_apres is StatutEntreprise.CESSEE
    assert transition.observe_a == plus_tard
    assert transition.sortie_du_flux is True

    # Le job rapporte ce que la BASE contient, pas ce qu'il croit avoir ecrit.
    assert resultat.transitions == changements
    assert len(resultat.sorties_du_flux) == 1


def test_une_bascule_qui_n_est_pas_une_sortie_ne_compte_pas_comme_telle(
    base: sqlite3.Connection,
) -> None:
    """`sortie_du_flux` doit distinguer, pas compter toutes les transitions.
    Sans ce cas, une propriete qui rendrait toujours `True` passerait le test
    precedent."""
    corpus = [annonce("A1")]
    balayage(base, corpus, statut=StatutEntreprise.INCONNU)
    resultat = balayage(
        base, corpus, statut=StatutEntreprise.ACTIVE, jour=AUJOURDHUI + timedelta(days=40)
    )
    assert len(resultat.transitions) == 1
    assert resultat.sorties_du_flux == [], "inconnu -> active n'est pas une sortie"


def test_le_journal_se_filtre_par_siren(base: sqlite3.Connection) -> None:
    """« Pourquoi CE lead a-t-il disparu ? » — la question qu'un decompte
    d'ecartes ne peut pas trancher, parce qu'il dit combien et jamais depuis
    quand."""
    corpus = [annonce("A1"), annonce("A2", siren="404833048")]
    balayage(base, corpus)
    balayage(
        base, corpus, statut=StatutEntreprise.CESSEE, jour=AUJOURDHUI + timedelta(days=40)
    )
    assert len(entrepot.transitions(base)) == 2
    assert len(entrepot.transitions(base, siren="404833048")) == 1


def test_le_journal_porte_le_MOTIF_de_l_enrichissement_pas_le_statut(
    base: sqlite3.Connection,
) -> None:
    """La colonne `motif` dit ce que la SOURCE a repondu, pas ce qu'on en a
    conclu.

    Sans cette assertion, ecrire le statut dans `motif` passe inapercu :
    `statut_apres` le porte deja, les deux sont des chaines non vides, et la
    ligne resterait plausible en disant deux fois la meme chose — au prix de la
    seule information qui permette de remonter a la reponse de l'API. Mutation
    verifiee : elle survivait a la suite entiere.
    """
    corpus = [annonce("A1")]
    balayage(base, corpus)
    resultat = balayage(
        base,
        corpus,
        statut=StatutEntreprise.CESSEE,
        jour=AUJOURDHUI + timedelta(days=40),
        motif="unite legale : etat administratif C",
    )
    assert resultat.transitions[0].motif == "unite legale : etat administratif C"


def test_le_job_ne_rapporte_que_les_transitions_de_SON_passage(
    base: sqlite3.Connection,
) -> None:
    """`ResultatCollecte.transitions` decrit CE balayage, pas l'historique.

    Le corpus separe deliberement les deux grandeurs : deux transitions en
    base, une seule datee du jour. Avec une seule, le compte-rendu d'un job
    grossirait a chaque passage en re-annoncant des bascules vieilles de
    plusieurs mois — et rien ne le distinguerait d'un rapport juste.
    """
    corpus = [annonce("A1")]
    balayage(base, corpus)
    balayage(base, corpus, statut=StatutEntreprise.INCONNU, jour=AUJOURDHUI + timedelta(days=40))
    dernier = AUJOURDHUI + timedelta(days=80)
    resultat = balayage(base, corpus, statut=StatutEntreprise.CESSEE, jour=dernier)

    assert len(entrepot.transitions(base)) == 2, "l'historique en porte deux"
    assert [t.observe_a for t in resultat.transitions] == [dernier], "le job n'en a fait qu'une"


def test_le_schema_refuse_une_transition_immobile(base: sqlite3.Connection) -> None:
    """Une ligne `active -> active` n'est pas une transition. Le CHECK l'interdit
    au niveau du schema, donc au code pas encore ecrit."""
    base.execute(
        "INSERT INTO cedant (siren, statut, motif, enrichi_a) "
        "VALUES ('852872563', 'active', 'x', '2026-08-16')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        base.execute(
            "INSERT INTO cedant_journal (siren, observe_a, statut_avant, statut_apres, motif) "
            "VALUES ('852872563', '2026-08-18', 'active', 'active', 'x')"
        )


# --- Palier 5 : les revisions de fait -----------------------------------------


def test_une_recollecte_identique_n_ecrit_aucune_revision(
    base: sqlite3.Connection,
) -> None:
    """Le cas nominal, et de loin le plus frequent. Une revision par ligne a
    chaque balayage rendrait la table illisible et le signal inexploitable."""
    corpus = [annonce("A1")]
    balayage(base, corpus)
    resultat = balayage(base, corpus, jour=AUJOURDHUI + timedelta(days=40))

    assert entrepot.revisions(base) == []
    assert resultat.revisions == []


def test_la_date_de_collecte_n_avance_pas_sur_un_fait_inchange(
    base: sqlite3.Connection,
) -> None:
    """`date_collecte` date le FAIT STOCKE, `derniere_verification` date le
    dernier passage. Deux dates, deux significations : les faire avancer
    ensemble ferait de la seconde un doublon de la premiere."""
    corpus = [annonce("A1")]
    balayage(base, corpus)
    plus_tard = AUJOURDHUI + timedelta(days=40)
    balayage(base, corpus, jour=plus_tard)

    ligne = base.execute("SELECT * FROM evenement").fetchone()
    assert ligne["date_collecte"] == AUJOURDHUI.isoformat(), "le fait n'a pas change"
    assert ligne["derniere_verification"] == plus_tard.isoformat()


def test_un_fait_qui_change_laisse_sa_version_precedente(
    base: sqlite3.Connection,
) -> None:
    """**Le test du palier 5.**

    Un rectificatif du BODACC et une regression de notre parser produisent le
    meme symptome : un fait qui n'est plus celui d'hier. Ecraser rend les deux
    indistinguables. La version remplacee est la seule trace qui permette de
    trancher.
    """
    balayage(base, [annonce("A1", montant=400_000.0)])
    plus_tard = AUJOURDHUI + timedelta(days=40)
    resultat = balayage(base, [annonce("A1", montant=450_000.0)], jour=plus_tard)

    versions = entrepot.revisions(base)
    assert len(versions) == 1
    assert versions[0].evenement_id == "A1"
    assert versions[0].remplacee_a == plus_tard
    assert versions[0].contenu["montant_eur"] == 400_000.0
    assert resultat.revisions == versions

    # Et la ligne courante porte bien la NOUVELLE valeur, datee de sa collecte.
    ligne = base.execute("SELECT * FROM evenement").fetchone()
    assert ligne["montant_eur"] == 450_000.0
    assert ligne["date_collecte"] == plus_tard.isoformat()


def test_la_revision_dit_QUELS_champs_ont_change(base: sqlite3.Connection) -> None:
    """C'est la comparaison qui permet de trancher : un montant qui change seul
    ressemble a un rectificatif, un montant qui devient nul sur des dizaines de
    lignes le meme jour ressemble a un parser casse."""
    balayage(base, [annonce("A1", montant=400_000.0)])
    balayage(
        base, [annonce("A1", montant=450_000.0)], jour=AUJOURDHUI + timedelta(days=40)
    )

    actuel = dict(base.execute("SELECT * FROM evenement").fetchone())
    modifies = entrepot.revisions(base)[0].champs_modifies(actuel)

    assert set(modifies) == {"montant_eur"}, "seul le montant a bouge"
    assert modifies["montant_eur"] == (400_000.0, 450_000.0)


@pytest.mark.parametrize(
    ("champ", "avant", "apres"),
    [
        ("montant", 400_000.0, 450_000.0),
        ("qualification", Qualification.ACHAT, Qualification.APPORT),
        ("siren", "852872563", "404833048"),
    ],
)
def test_chaque_colonne_de_fait_declenche_une_revision(
    base: sqlite3.Connection, champ: str, avant: object, apres: object
) -> None:
    """L'empreinte doit couvrir TOUTES les colonnes de fait. Un champ oublie
    dans le calcul rendrait ses changements invisibles — et invisibles
    silencieusement, ce qui est le pire des deux mondes."""
    balayage(base, [annonce("A1", **{champ: avant})])  # type: ignore[arg-type]
    balayage(base, [annonce("A1", **{champ: apres})], jour=AUJOURDHUI + timedelta(days=40))  # type: ignore[arg-type]
    assert len(entrepot.revisions(base)) == 1, f"un changement de {champ} doit tracer"


@pytest.mark.parametrize(
    ("presente", "pourquoi"),
    [
        ("", "une chaine vide — le cas evident, et celui qui ne garde RIEN"),
        ("None", "le mot « None » en clair — le seul cas que `_ABSENT` protege"),
    ],
)
def test_une_valeur_absente_ne_se_confond_avec_aucune_valeur_presente(
    presente: str, pourquoi: str
) -> None:
    """`None` a sa marque propre dans l'empreinte, et c'est le second cas qui
    le prouve.

    Le premier — absent contre chaine vide — se distingue **tout seul**, sans
    marqueur : `str(None)` rend « None », qui n'est pas «  ». Il est garde ici
    pour memoire, mais la mutation `_ABSENT = "None"` lui survit.

    Le second est le vrai risque : `str(None)` rend litteralement « None », et
    un `cedant_denomination` peut valoir « None ». Sans octet NUL, une
    denomination disparue et une denomination valant « None » rendraient la
    meme empreinte — et la disparition serait invisible.
    """
    faits = {c: "x" for c in entrepot.COLONNES_DE_FAIT}
    absente = entrepot.empreinte_du_fait({**faits, "cedant_denomination": None})
    assert absente != entrepot.empreinte_du_fait(
        {**faits, "cedant_denomination": presente}
    ), pourquoi


def test_deux_valeurs_voisines_ne_se_fondent_pas_l_une_dans_l_autre() -> None:
    """Le separateur borne chaque valeur.

    Sans lui, l'empreinte n'est qu'une concatenation, et la frontiere entre
    deux champs voisins disparait : `departement="06"` suivi de
    `montant_eur="1"` donne la meme chaine que `departement="0"` suivi de
    `montant_eur="61"`. Deux faits differents, une seule empreinte — donc une
    revision jamais tracee.
    """
    faits = {c: "x" for c in entrepot.COLONNES_DE_FAIT}
    # `departement` et `montant_eur` sont VOISINS dans `COLONNES_DE_FAIT` :
    # c'est la seule configuration ou la frontiere peut se dissoudre.
    gauche = entrepot.empreinte_du_fait({**faits, "departement": "06", "montant_eur": "1"})
    droite = entrepot.empreinte_du_fait({**faits, "departement": "0", "montant_eur": "61"})
    assert gauche != droite


def test_une_permutation_de_deux_champs_change_l_empreinte() -> None:
    """C'est la POSITION qui identifie chaque valeur, pas un nom de colonne.

    Les colonnes sont parcourues dans un ordre fixe : deux champs qui
    echangeraient leur valeur produisent donc deja deux concatenations
    differentes. Ce test garde cette propriete — il rougirait si l'empreinte
    se mettait a hacher un ensemble non ordonne, ou que l'ordre des colonnes
    devienne dependant du dictionnaire d'entree.
    """
    faits = {c: "x" for c in entrepot.COLONNES_DE_FAIT}
    droit = entrepot.empreinte_du_fait({**faits, "devise": "EUR", "departement": "06"})
    permute = entrepot.empreinte_du_fait({**faits, "devise": "06", "departement": "EUR"})
    assert droit != permute


def test_les_dates_de_suivi_ne_sont_pas_dans_l_empreinte() -> None:
    """`date_collecte` et consorts bougent a chaque passage : les inclure ferait
    conclure a un changement du fait a chaque recollecte, donc a une revision
    par ligne et par balayage."""
    for suivi in ("date_collecte", "premiere_collecte", "derniere_verification"):
        assert suivi not in entrepot.COLONNES_DE_FAIT


def test_le_job_ne_rapporte_que_les_revisions_de_SON_passage(
    base: sqlite3.Connection,
) -> None:
    """Meme regle que pour les transitions, et meme corpus qui separe : deux
    revisions en base, une seule datee du jour."""
    balayage(base, [annonce("A1", montant=400_000.0)])
    balayage(base, [annonce("A1", montant=450_000.0)], jour=AUJOURDHUI + timedelta(days=40))
    dernier = AUJOURDHUI + timedelta(days=80)
    resultat = balayage(base, [annonce("A1", montant=500_000.0)], jour=dernier)

    assert len(entrepot.revisions(base)) == 2, "l'historique en porte deux"
    assert [r.remplacee_a for r in resultat.revisions] == [dernier], "le job n'en a fait qu'une"


def test_les_evenements_NOUVEAUX_se_distinguent_des_evenements_ecrits(
    base: sqlite3.Connection,
) -> None:
    """Deux grandeurs, deux noms — et un corpus ou elles different.

    Sur un corpus entierement neuf, `evenements_ecrits` et
    `evenements_nouveaux` valent le meme nombre : le test serait vert quelle
    que soit celle des deux que le code calcule. C'est exactement le corpus
    degenere qui a deja coute deux tests aveugles a ce projet. Le second
    balayage reecrit donc A1 — deja connu — et n'apporte que A2.
    """
    balayage(base, [annonce("A1")])
    resultat = balayage(
        base, [annonce("A1"), annonce("A2")], jour=AUJOURDHUI + timedelta(days=40)
    )
    assert resultat.evenements_ecrits == 2, "les deux lignes sont reecrites"
    assert resultat.evenements_nouveaux == 1, "une seule n'existait pas avant"


def test_toute_colonne_de_fait_du_schema_entre_dans_l_empreinte(
    base: sqlite3.Connection,
) -> None:
    """**Le garde structurel.** `COLONNES_DE_FAIT` recopie le schema, donc elle
    en derive.

    Les cas nominaux ne couvrent qu'une poignee de colonnes : en retirer une
    autre — `url_publication`, par exemple — rendait ses changements
    silencieusement invisibles sans faire rougir quoi que ce soit. Mutation
    verifiee.

    La liste des colonnes de SUIVI est ecrite ici en clair : ajouter une
    colonne au schema sans la classer dans l'un des deux camps fait echouer ce
    test, ce qui est le but — le classement doit etre une decision, pas un
    oubli.
    """
    suivi = {"id", "date_collecte", "premiere_collecte", "derniere_verification", "empreinte"}
    du_schema = {ligne["name"] for ligne in base.execute("PRAGMA table_info(evenement)")}
    assert du_schema - suivi == set(entrepot.COLONNES_DE_FAIT)


def test_la_migration_calcule_les_empreintes_existantes(tmp_path: Path) -> None:
    """**La premiere migration qui ne peut pas etre implicite.**

    Laisser `empreinte = ''` sur les lignes d'une base anterieure ferait
    conclure a un changement des la premiere recollecte, et ecrirait une
    revision fantome sur CHAQUE ligne — un faux positif de masse, dans la table
    meme qui doit servir a distinguer un rectificatif d'une regression.
    """
    chemin = tmp_path / "v2.db"
    ancienne = entrepot.ouvrir(chemin)
    entrepot.enregistrer(ancienne, fabriquer_lead_v2())
    # On simule une base d'avant le palier 5 : empreinte vidée, version reculee.
    ancienne.execute("UPDATE evenement SET empreinte = ''")
    ancienne.execute("PRAGMA user_version = 2")
    ancienne.commit()
    ancienne.close()

    migree = entrepot.ouvrir(chemin)
    empreinte = migree.execute("SELECT empreinte FROM evenement").fetchone()["empreinte"]
    assert empreinte != "", "la migration doit CALCULER, pas laisser vide"
    assert migree.execute("PRAGMA user_version").fetchone()[0] == entrepot.VERSION_SCHEMA

    # Et la recollecte a l'identique ne doit produire AUCUNE revision fantome.
    entrepot.enregistrer(migree, fabriquer_lead_v2())
    assert entrepot.revisions(migree) == []
    migree.close()
