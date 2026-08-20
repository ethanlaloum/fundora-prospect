/**
 * Les deux proprietes de l'analyse qui ne doivent pas dependre d'une mise en
 * page.
 *
 * Aucun lanceur de tests dans le front, aucun DOM : c'est pourquoi elles ont
 * ete sorties du JSX. Un composant se verifie avec un
 * navigateur, une fonction pure avec `node` — et ce qui est important a assez
 * de valeur pour etre deplace.
 */

import { strict as assert } from "node:assert";

import { presenterAnalyse } from "../src/comparatif.ts";

// --- 1. La degradation est un etat rendu, pas une absence --------------------

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

// --- 2. Le rattachement se fait par CLEF -------------------------------------
//
// Pas d'appariement, pas de recherche : un acces. Le test le verifie sur les
// deux cas qui comptent — un lead analyse, et un lead que le modele a laisse
// tomber (celui qui doit rester affiche avec un emplacement vide).

const encarts = NOMINALE.encarts;
assert.equal(encarts["A-PM"], "Societe active, produit encore au bilan.");
assert.equal(encarts["A-PP"], undefined, "un lead sans analyse n'en invente pas");

console.log("comparatif.ts : toutes les assertions passent");
