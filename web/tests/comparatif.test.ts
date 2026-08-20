/**
 * Les trois proprietes de l'ecran de comparatif qui ne doivent pas dependre
 * d'une mise en page.
 *
 * Aucun lanceur de tests dans le front, aucun DOM : c'est pourquoi ces trois
 * proprietes ont ete sorties du JSX. Un composant se verifie avec un
 * navigateur, une fonction pure avec `node` — et ce qui est important a assez
 * de valeur pour etre deplace.
 */

import { strict as assert } from "node:assert";

import { lignesDEcart, presenterAnalyse } from "../src/comparatif.ts";

// --- 1. La cause reste collee a son ecart ------------------------------------

const EFFET = {
  identiques: false,
  meme_ordre: false,
  seulement_reference: ["A-PP"],
  seulement_comparee: [],
  arguments_respectes: false,
};

const lignes = lignesDEcart(EFFET);
const clefs = lignes.map(([clef]) => clef);

assert.ok(
  clefs.includes("arguments_respectes"),
  "la cause doit etre rendue avec l'ecart, jamais separement",
);
assert.equal(
  clefs.length,
  Object.keys(EFFET).length,
  "toutes les clefs de l'ecart sont rendues, aucune n'est choisie",
);

// Le point qui compte : le front ne NOMME aucune clef. Un champ ajoute demain
// apparait sans qu'on touche au JSX, un champ retire disparait — et c'est ce
// qui empeche qu'on « oublie » la cause en remaniant la mise en page.
const AJOUTE = { ...EFFET, cause_nouvelle: "quelque chose" };
assert.ok(lignesDEcart(AJOUTE).map(([c]) => c).includes("cause_nouvelle"));

// L'autre ecart passe par la meme fonction — sinon les deux divergeraient sur
// ce qu'ils montrent, et le second se lirait comme le premier.
const FRAICHEUR = {
  disponible: true,
  identiques: false,
  meme_ordre: false,
  seulement_reference: ["A-X"],
  seulement_comparee: [],
  reserve: "mesure l'age de la derniere collecte, pas l'effet du modele",
};
assert.ok(lignesDEcart(FRAICHEUR).map(([c]) => c).includes("reserve"));

// --- 2. La degradation est un etat rendu, pas une absence --------------------

const NOMINALE = presenterAnalyse({
  disponible: true,
  synthese: "Deux cessions recentes.",
  par_lead: { "A-PM": "Societe active, produit encore au bilan." },
  reserve: null,
});

assert.equal(NOMINALE.disponible, true);
assert.equal(NOMINALE.texte, "Deux cessions recentes.");
assert.deepEqual(Object.keys(NOMINALE.encarts), ["A-PM"]);

const DEGRADEE = presenterAnalyse({
  disponible: false,
  synthese: "",
  par_lead: {},
  reserve: "RuntimeError : api indisponible",
});

assert.equal(DEGRADEE.disponible, false);
assert.equal(
  DEGRADEE.texte,
  "RuntimeError : api indisponible",
  "la reserve doit etre montree — la degradation se voit a l'ecran",
);
assert.deepEqual(DEGRADEE.encarts, {}, "aucun encart quand l'analyse manque");

// Une reserve absente ne doit pas faire inventer un motif au front : si l'API
// ne dit pas pourquoi, l'ecran dit qu'elle ne l'a pas dit.
const MUETTE = presenterAnalyse({
  disponible: false,
  synthese: "",
  par_lead: {},
  reserve: null,
});
assert.equal(MUETTE.texte, "");

// --- 3. Le rattachement se fait par CLEF -------------------------------------
//
// Pas d'appariement, pas de recherche : un acces. Le test le verifie sur les
// deux cas qui comptent — un lead analyse, et un lead que le modele a laisse
// tomber (celui qui doit rester affiche avec un emplacement vide).

const encarts = NOMINALE.encarts;
assert.equal(encarts["A-PM"], "Societe active, produit encore au bilan.");
assert.equal(encarts["A-PP"], undefined, "un lead sans analyse n'en invente pas");

console.log("comparatif.ts : toutes les assertions passent");
