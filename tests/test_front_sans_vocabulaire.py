"""Le front connait des CLEFS, jamais des VALEURS.

## La frontiere, et pourquoi il en faut une

« Aucune donnee en dur dans le front » est inapplicable tel quel : afficher quoi
que ce soit exige de nommer quelque chose. La ligne tenue par ce projet :

- **Autorise** — `lead.score`, `statistiques.annonces_publiees`, le chemin
  `/leads`, `type_cedant === "pp"` pour choisir une classe CSS. Ce sont des
  liaisons *structurelles*, du meme ordre que connaitre l'URL d'une route.
- **Interdit** — « apport », « sous le montant minimum », « personne
  physique ». Ce sont des *valeurs* : elles viennent de l'API ou n'existent pas.

## Le vocabulaire interdit est DERIVE du coeur, pas recopie

Une liste ecrite a la main dans ce test serait elle-meme une copie du
vocabulaire — celle qui derive au premier motif renomme, et le test cesserait
alors de garder ce qu'il croit garder sans que rien ne rougisse.

`vocabulaire_du_coeur` fait donc **tourner le coeur** et ramasse les motifs
qu'il produit reellement : chaque qualification via `motif_ecart_faits`, les
refus de statut via `classer`, les libelles de segment via `TypeCedant`. Un
motif ajoute demain est couvert le jour meme.

## Balayage : tout `web/src`, pas seulement les composants

Un libelle cache dans un fichier de constantes, de styles ou de types generes
passerait un balayage limite aux composants. Le fichier genere par
`tools/exporter_types.py` est d'ailleurs le candidat le plus probable — c'est
lui qui pourrait deduire un champ par motif si les dictionnaires a clefs libres
n'etaient pas declares.

## La friction, constatee des la premiere execution

Le verrou a signale `main.tsx`, qui disait « element #racine **absent** de
index.html ». Un message d'erreur ordinaire — mais « absent » est aussi un motif
du coeur (`Qualification.ABSENT`), et le balayage ne sait pas distinguer les
deux emplois d'un mot francais courant.

**Choix : reformuler le front, pas affaiblir le verrou.** Ecrire
« introuvable » coute une seconde ; restreindre le balayage aux chaines
affichables couterait la garantie, et n'aurait meme pas aide ici — le message
etait dans une chaine.

C'est un compromis, pas une evidence, et il a une limite connue : **si ce cas se
represente souvent, le verrou finira desactive** — « un audit qui crie au loup
est desactive dans la semaine ». Le signal a surveiller est le nombre de
reformulations subies pour lui plaire. S'il grandit, la bonne reponse ne sera
pas de tolerer des exceptions une a une mais de retirer du vocabulaire les
motifs d'un seul mot courant, en assumant qu'ils ne sont plus gardes.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from fundora_prospect.models import LiquidityEvent, StatutEntreprise, TypeCedant
from fundora_prospect.pipeline import Ecarte, classer, motif_ecart_faits
from fundora_prospect.prix import Qualification
from fundora_prospect.scoring import GrillePonderation

RACINE = Path(__file__).resolve().parent.parent
WEB = RACINE / "web" / "src"

# Les dossiers produits par l'outillage : ils ne sont pas du code ecrit ici.
IGNORES = {"node_modules", "dist", ".vite"}


def _event(identifiant: str, **options: object) -> LiquidityEvent:
    return LiquidityEvent(
        id=identifiant,
        date_parution=date(2026, 8, 1),
        date_acte=date(2026, 7, 1),
        departement="06",
        url_publication=options.pop("url", "https://www.bodacc.fr/x/1"),  # type: ignore[arg-type]
        montant_eur=400_000.0,
        devise="EUR",
        qualification="achat",
        retenu=True,
        cedant_denomination="SOCIETE",
        cedant_type=TypeCedant.PERSONNE_MORALE,
        cedant_siren="852872563",
        **options,  # type: ignore[arg-type]
    )


def vocabulaire_du_coeur() -> set[str]:
    """Tous les textes que le coeur peut produire et que le front ne doit pas
    contenir. **Obtenus en le faisant tourner**, jamais recopies."""
    motifs: set[str] = {t.libelle for t in TypeCedant}

    # Un motif par qualification, plus les deux qui n'en dependent pas.
    for qualification in Qualification:
        motifs.add(str(motif_ecart_faits(
            retenu=False, aberrant=False, qualification=str(qualification), montant=1.0
        )))
    motifs.add(str(motif_ecart_faits(
        retenu=True, aberrant=True, qualification="achat", montant=1.0
    )))
    motifs.add(str(motif_ecart_faits(
        retenu=True, aberrant=False, qualification="achat", montant=1.0, montant_min=2.0
    )))

    # Les refus decides par `classer` : on les ramasse en le faisant refuser.
    recueil: list[Ecarte] = []
    classer(
        [
            _event("CESSEE", statut_cedant=StatutEntreprise.CESSEE),
            _event("NON-DIFF", statut_cedant=StatutEntreprise.NON_DIFFUSIBLE),
            _event("SANS-URL", url=""),
        ],
        grille=GrillePonderation.defaut(),
        aujourdhui=date(2026, 8, 18),
        limite=10,
        ecartes=recueil,
        date_collecte_de=lambda _: date(2026, 8, 18),
    )
    motifs |= {e.motif for e in recueil}
    return {m for m in motifs if m and m != "None"}


def fichiers_web(base: Path | None = None) -> list[Path]:
    """Le repertoire est un PARAMETRE, pas une globale substituee.

    La premiere version le lisait dans un global que les tests de dents
    remplacaient par `monkeypatch`. Ca ne marchait pas — pytest importe ce
    module sous un nom, `monkeypatch` en visait un autre, et les tests de dents
    echouaient en silence sur un repertoire vide. Un parametre ne peut pas rater
    sa cible : meme raison que `rechercher` et `enrichir` dans le coeur.
    """
    base = base or WEB
    if not base.exists():
        return []
    return sorted(
        p for p in base.rglob("*") if p.is_file() and not (set(p.parts) & IGNORES)
    )


def occurrences(texte: str, vocabulaire: set[str]) -> set[str]:
    """Les termes du coeur presents dans un texte, aux frontieres de mots.

    Les frontieres comptent : « apport » sans elles serait trouve dans
    « rapport », et un audit qui crie au loup est desactive dans la semaine.
    Avec elles, « apport en nature » est bien signale — il CONTIENT le mot.
    """
    return {
        terme
        for terme in vocabulaire
        if re.search(rf"\b{re.escape(terme)}\b", texte, flags=re.IGNORECASE)
    }


# --- Le depot est propre ------------------------------------------------------


def test_le_vocabulaire_du_coeur_n_apparait_nulle_part_dans_web(tmp_path: Path) -> None:
    """Le verrou. Balaye TOUT `web/src`, extensions comprises."""
    vocabulaire = vocabulaire_du_coeur()
    fautifs = {
        p.relative_to(RACINE).as_posix(): trouves
        for p in fichiers_web()
        if (trouves := occurrences(p.read_text(encoding="utf-8", errors="ignore"), vocabulaire))
    }
    assert not fautifs, (
        "vocabulaire du coeur recopie dans le front — il doit venir de l'API :\n"
        + "\n".join(f"  {f} : {sorted(t)}" for f, t in sorted(fautifs.items()))
    )


def test_le_balayage_voit_bien_des_fichiers() -> None:
    """Garde-fou contre un test vert parce qu'il ne regarde rien. Un mauvais
    chemin rendrait le verrou muet — vert pour la mauvaise raison."""
    assert fichiers_web(), "aucun fichier balaye dans web/src"


def test_le_vocabulaire_derive_est_RICHE_et_specifique() -> None:
    """Un vocabulaire vide ou minuscule passerait le verrou sans rien garder.

    On verifie qu'il contient des motifs de plusieurs familles — une
    qualification, un refus de statut, un libelle de segment — parce que c'est
    la couverture qui fait la valeur du test, pas sa presence.
    """
    vocabulaire = vocabulaire_du_coeur()
    assert len(vocabulaire) >= 8, f"seulement {len(vocabulaire)} termes derives"
    assert "apport" in vocabulaire, "les qualifications doivent etre couvertes"
    assert "sous le montant minimum" in vocabulaire, "le seuil commercial aussi"
    assert any("cess" in m for m in vocabulaire), "les refus de statut aussi"
    assert "personne physique" in vocabulaire, "les libelles de segment aussi"


# --- Le verrou a des dents ----------------------------------------------------


@pytest.mark.parametrize(
    ("contenu", "pourquoi"),
    [
        ('const x = "apport en nature";', "un motif noye dans une phrase plus longue"),
        ("// un commentaire qui parle d'apport\n", "un motif dans un commentaire"),
        ('.badge::after { content: "personne physique"; }', "un libelle dans du CSS"),
        ('export const SEUIL = "sous le montant minimum";', "un motif dans les constantes"),
    ],
)
def test_le_verrou_attrape_un_libelle_cache(
    tmp_path: Path, contenu: str, pourquoi: str
) -> None:
    """**Les dents.** Quatre cachettes, dont trois hors des composants : un
    fichier de styles, un fichier de constantes, un commentaire."""
    faux = tmp_path / "src" / "quelque_part"
    faux.mkdir(parents=True)
    (faux / "fichier.ts").write_text(contenu, encoding="utf-8")

    trouves = {
        p: t
        for p in fichiers_web(tmp_path / "src")
        if (t := occurrences(p.read_text(encoding="utf-8"), vocabulaire_du_coeur()))
    }
    assert trouves, pourquoi


def test_le_verrou_ne_crie_pas_au_loup_sur_un_mot_qui_CONTIENT_un_motif() -> None:
    """« rapport » contient « apport ». Sans frontieres de mots, le verrou
    signalerait du francais ordinaire — et serait desactive dans la semaine."""
    vocabulaire = vocabulaire_du_coeur()
    assert not occurrences("const rapport = construireRapport();", vocabulaire)
    assert occurrences("const x = 'apport';", vocabulaire) == {"apport"}
