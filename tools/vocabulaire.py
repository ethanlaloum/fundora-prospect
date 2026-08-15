"""Vocabulaire synthetique des fixtures — la definition de la LISTE BLANCHE.

Contrainte 4 : les fixtures ne peuvent contenir que ce qui est declare ici.
Ce module est la source unique de verite, partagee par le recorder qui
substitue et par le test qui valide. Deux listes separees divergeraient.

Principe : on ne masque pas des morceaux de phrase reelle, on la RECONSTRUIT.
Un masquage laisse la structure et le contexte de la donnee d'origine ; une
reconstruction ne laisse rien. Seules les valeurs non personnelles (dates,
montants, numeros d'annonce) sont reportees dans les gabarits, via des
emplacements typés.
"""

from __future__ import annotations

import re
import unicodedata

# --- Valeurs de remplacement des champs structures ---------------------------

NOMS = ("NOMTEST", "PATRONYMETEST", "FAMILLETEST")
PRENOMS = ("Prenomtest", "Secondtest", "Tiercetest")
NOMS_USAGE = ("USAGETEST",)
TYPES_VOIE = ("Rue", "Avenue", "Boulevard")
NOMS_VOIE = ("de la Fixture", "des Tests", "du Gabarit")
NUMEROS_VOIE = ("1", "2", "3")
COMPLEMENTS = ("Batiment Test", "Zone Test")
VILLES = ("Villetest", "Bourgtest", "Communetest")
CODES_POSTAUX = ("00000", "00001", "00002")
PAYS = ("Paystest",)
NATIONALITES = ("Nationalitetest",)
# Une enseigne peut etre un nom de personne (« Chez Michel ») : substituee.
ENSEIGNES = ("ENSEIGNETEST",)
# `activite` est de la prose libre : 264 valeurs distinctes sur 271, jusqu'a
# 908 caracteres. Aucun lexique ne peut la valider sans devenir une liste
# ouverte, donc une liste noire deguisee. Elle est substituee, et le critere
# secteur du scoring sera keye sur le code APE recupere en Phase 3.
ACTIVITES = ("Activitetest",)

# Regroupement par champ terminal : le recorder pioche dedans, le test verifie
# l'appartenance.
VALEURS_AUTORISEES: dict[str, tuple[str, ...]] = {
    "nom": NOMS,
    "prenom": PRENOMS,
    "nomUsage": NOMS_USAGE,
    "typeVoie": TYPES_VOIE,
    "nomVoie": NOMS_VOIE,
    "numeroVoie": NUMEROS_VOIE,
    "complGeographique": COMPLEMENTS,
    "ville": VILLES,
    "codePostal": CODES_POSTAUX,
    "pays": PAYS,
    "nationalite": NATIONALITES,
    "enseigne": ENSEIGNES,
    "activite": ACTIVITES,
}

# --- Gabarits des champs a texte libre ---------------------------------------
# Chaque gabarit est un motif ANCRE. Les seuls emplacements variables sont des
# donnees non personnelles : dates, numeros, montants.

_DATE = r"\d{2}/\d{2}/\d{4}"

GABARITS: dict[str, re.Pattern[str]] = {
    # Porte la date d'acte, indispensable au garde de fraicheur du parser.
    # Les dates sont conservees, tout le reste est reconstruit.
    "acte.descriptif": re.compile(rf"^Acte en date du {_DATE}(?: enregistre le {_DATE})?\.$"),
    # Champ le plus dangereux du dataset : nom ET adresse complete en clair.
    "acte.vente.opposition": re.compile(
        r"^Election de domicile : ETUDE TEST, 1 Rue de la Fixture, 00000 Villetest\.$"
    ),
    # Melange raison sociale et nom de personne sans separateur fiable :
    # remplace en entier.
    "commercant": re.compile(r"^COMMERCANT TEST$"),
    # Liste de dirigeants, personnes physiques nommees.
    "listepersonnes.personne.administration": re.compile(r"^President : NOMTEST Prenomtest$"),
}

# Valeurs de substitution correspondantes, utilisees par le recorder.
_OPPOSITION = "Election de domicile : ETUDE TEST, 1 Rue de la Fixture, 00000 Villetest."

SUBSTITUTIONS: dict[str, str] = {
    "acte.vente.opposition": _OPPOSITION,
    "commercant": "COMMERCANT TEST",
    "listepersonnes.personne.administration": "President : NOMTEST Prenomtest",
}

# --- Lexique autorise pour `origineFonds` ------------------------------------
# Ce champ porte le prix : c'est la matiere premiere du parser, on ne peut pas
# le remplacer par un gabarit sans vider les tests de leur substance. Il est
# donc CONSERVE mais valide mot a mot : chaque mot doit appartenir au lexique.
# Un nom propre serait un mot inconnu et ferait echouer la validation.
# Le lexique est ecrit SANS accent ; la comparaison les retire aussi. BODACC
# melange les deux graphies (« stipulé » / « stipule ») selon les greffes.
# Le bloc de texte se relit et s'edite mieux qu'une liste de litteraux ; ce
# lexique est destine a grandir au fil des formulations de greffe rencontrees.
# SIM905 est desactive pour ce fichier dans pyproject.toml.
LEXIQUE_ORIGINE_FONDS = frozenset(
    """
    a achat achete acquis acquise activite apport apporte attribue attribution
    au auquel aux avec bail biens bien cede cedee cession commercial commerciale
    complementaire creation d de des donation du elements en est et etablissement
    evalue evaluee exploitation exploite exploitee fonds francais francs frf
    gerance heritage indivision l la le les licence location locationgerance
    montant negoce par partiel partie precedemment principal prix propriete
    rachat recu reprise secondaire siege societe stipule stipulee succession
    suite sur titre transmission un une universalite valeur vente
    euro euros eur
    """.split()
)

# Tokens non lexicaux toleres dans `origineFonds` : nombres, ponctuation.
MOTIF_TOKEN_NEUTRE = re.compile(r"^[\d\s.,;:()'’\-/€]*$")


def sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def mots_inconnus(texte: str) -> list[str]:
    """Mots de `origineFonds` absents du lexique — doit toujours etre vide.

    `origineFonds` porte le prix : c'est la matiere premiere du parser, la
    remplacer par un gabarit vide les tests de leur substance. Le champ est donc
    conserve reel mais valide mot a mot — un nom propre serait un mot inconnu.
    """
    inconnus = []
    for brut in re.split(r"[\s,;:()'’\-/]+", texte):
        token = sans_accents(brut.strip(".")).lower()
        if not token or MOTIF_TOKEN_NEUTRE.match(brut):
            continue
        if token.isdigit():
            continue
        if token not in LEXIQUE_ORIGINE_FONDS:
            inconnus.append(brut)
    return inconnus


# --- Chemins autorises a contenir du texte -----------------------------------
# Tout chemin de type chaine absent de cet ensemble fait echouer le test : une
# evolution du schema BODACC introduisant un nouveau champ texte est signalee
# au lieu de passer inapercue.
CHEMINS_TEXTE_AUTORISES = frozenset(
    {
        # identifiants et metadonnees, sans donnee personnelle
        "id",
        "publicationavis",
        "parution",
        "dateparution",
        "typeavis",
        "typeavis_lib",
        "familleavis",
        "familleavis_lib",
        "numerodepartement",
        "departement_nom_officiel",
        "region_nom_officiel",
        "tribunal",
        "ville",
        "registre[]",
        "cp",
        "ispdf_unitaire",
        "url_complete",
        # contenu metier
        "commercant",
        "acte.descriptif",
        "acte.dateCommencementActivite",
        "acte.dateImmatriculation",
        "acte.vente.categorieVente",
        "acte.vente.dateEffet",
        # Nom de greffe : institution publique, pas une personne.
        "acte.vente.declarationCreance",
        "acte.vente.opposition",
        "acte.vente.publiciteLegale.date",
        "acte.vente.publiciteLegale.titre",
        "listeetablissements.etablissement.activite",
        "listeetablissements.etablissement.enseigne",
        "listeetablissements.etablissement.origineFonds",
        "listeetablissements.etablissement.adresse.pays",
        "listeetablissements.etablissement.qualiteEtablissement",
        "listeetablissements.etablissement.adresse.codePostal",
        "listeetablissements.etablissement.adresse.complGeographique",
        "listeetablissements.etablissement.adresse.nomVoie",
        "listeetablissements.etablissement.adresse.numeroVoie",
        "listeetablissements.etablissement.adresse.typeVoie",
        "listeetablissements.etablissement.adresse.ville",
        "parutionavisprecedent.dateParution",
        "parutionavisprecedent.nomPublication",
        "parutionavisprecedent.numeroAnnonce",
        "parutionavisprecedent.numeroParution",
    }
)

# Les branches `personne` apparaissent sous quatre listes et tantot en objet,
# tantot en tableau. On decrit les feuilles autorisees une fois.
FEUILLES_PERSONNE_AUTORISEES = frozenset(
    {
        "administration",
        "adresseSiegeSocial.codePostal",
        "adresseSiegeSocial.complGeographique",
        "adresseSiegeSocial.nomVoie",
        "adresseSiegeSocial.numeroVoie",
        "adresseSiegeSocial.pays",
        "adresseSiegeSocial.typeVoie",
        "adresseSiegeSocial.ville",
        "capital.devise",
        "capital.montantCapital",
        "denomination",
        "formeJuridique",
        "nationalite",
        "nom",
        "nomCommercial",
        "nomUsage",
        "nonInscrit",
        # Sous-objet `personneMorale` : raison sociale, conservee (contrainte 4).
        "personneMorale.denomination",
        "personneMorale.nonInscrit",
        "numeroImmatriculation.codeRCS",
        "numeroImmatriculation.nomGreffeImmat",
        "numeroImmatriculation.numeroIdentification",
        "prenom",
        "sigle",
        "typePersonne",
    }
)

PREFIXES_PERSONNE = (
    "listepersonnes.personne",
    "listeprecedentproprietaire.personne",
    "listeprecedentexploitant.personne",
)
