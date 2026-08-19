/**
 * Les assertions du seul module du front qui contienne de la LOGIQUE.
 *
 * ## Pourquoi ce fichier existe, et pourquoi il est seul
 *
 * Le front n'a pas de lanceur de tests : en installer un demanderait un aller
 * sur le reseau, et les verrous du depot sont statiques — ils lisent le code,
 * ils ne l'executent pas. Une mise en forme fausse (une date permutee, un
 * arrondi qui mange un chiffre) passerait donc **tous** les controles.
 *
 * Node 22+ sait executer du TypeScript en retirant les types. Le module de
 * mise en forme est pur, sans DOM et sans React : il s'execute donc tel quel,
 * sans dependance, sans installation. C'est exactement pour ca que la logique
 * d'affichage a ete tenue **hors** des composants — un composant se teste avec
 * un navigateur, une fonction pure se teste avec `node`.
 *
 * Ce qui reste non couvert est dit franchement : le rendu JSX lui-meme. Ce
 * n'est pas un oubli, c'est le cout assume de ne pas installer de navigateur
 * d'essai — et la raison de garder les composants sans decision.
 *
 * Lance par `tests/test_format_web.py`, qui verifie aussi que ce fichier sait
 * ROUGIR : un harnais qui rendrait toujours vert passerait inapercu.
 */

import { strict as assert } from "node:assert";

import { compte, libelle, valeur, VIDE } from "../src/format.ts";

// --- La clef, rendue lisible, et rien de plus -------------------------------

assert.equal(libelle("montant_min_eur"), "montant min eur");
assert.equal(libelle("score"), "score");

// --- Les dates ne bougent PAS d'un jour --------------------------------------
//
// Le piege que ce test garde : `new Date("2026-08-11")` est interprete en UTC,
// et un fuseau negatif afficherait le 10. Sur une fiche d'audit, une date
// d'acte fausse d'un jour est un faux fait — et un faux fait se lit, quand une
// absence se voit.

assert.equal(valeur("date_parution", "2026-08-11"), "11/08/2026");
assert.equal(valeur("date_acte", "2026-01-01"), "01/01/2026");

// Une chaine qui n'est pas une date sort intacte.
assert.equal(valeur("statut_cedant", "active"), "active");

// --- Le vide se voit ---------------------------------------------------------

assert.equal(valeur("date_acte", null), VIDE);
assert.equal(valeur("siren", undefined), VIDE);

// --- Les booleens ------------------------------------------------------------

assert.equal(valeur("plafond_atteint", true), "oui");
assert.equal(valeur("collecte_partielle", false), "non");

// --- Les nombres : l'unite vient du NOM du champ ------------------------------

const montant = valeur("montant_eur", 6350000);
assert.ok(montant.includes("€"), `pas d'euro dans ${montant}`);
assert.equal(
  montant.replace(/\D/g, ""),
  "6350000",
  `les chiffres du montant doivent survivre a la mise en forme : ${montant}`,
);

// Un champ numerique sans `_eur` n'est pas de l'argent.
const jours = valeur("jours_ecoules", 8);
assert.ok(!jours.includes("€"), `l'euro s'est invite dans ${jours}`);
assert.equal(jours, "8");

// Le score garde une decimale : deux leads a 98,6 et 98,7 ne doivent pas
// s'afficher identiques alors que le classement les separe.
assert.equal(valeur("score", 98.6348), "98,6");
assert.notEqual(valeur("score", 98.6348), valeur("score", 98.7348));

// Un compteur de population reste entier et lisible.
assert.equal(compte(1218).replace(/\D/g, ""), "1218");

console.log("format.ts : toutes les assertions passent");
