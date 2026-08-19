/**
 * Les assertions de la frontiere avec l'API.
 *
 * `client.ts` prend deux decisions, et ce sont les deux seules du front :
 *
 * 1. **un champ vide n'est pas envoye** — c'est ce qui permet au front de ne
 *    recopier aucun defaut du coeur. Si la garde tombait, le front enverrait
 *    `mois=` et l'API refuserait ; ou pire, il devrait ecrire un defaut ici ;
 * 2. **le refus de l'API est remonte tel quel** — le front ne formule pas un
 *    refus qu'il n'a pas decide.
 *
 * Les deux se verifient sans navigateur : `fetch` est une fonction globale,
 * donc remplacable. Aucune dependance, aucune installation — meme raison que
 * pour `format.test.ts`.
 */

import { strict as assert } from "node:assert";

import {
  FILTRES_VIDES,
  lireEcartes,
  lireEvenement,
  lireFiltres,
  lireLeads,
  lireSorties,
} from "../src/api/client.ts";

const vues: string[] = [];

function repondre(charge: unknown, status = 200): void {
  globalThis.fetch = (entree: unknown) => {
    vues.push(String(entree));
    return Promise.resolve(
      new Response(JSON.stringify(charge), {
        status,
        headers: { "content-type": "application/json" },
      }),
    );
  };
}

// --- Un champ vide n'est pas un filtre ---------------------------------------

repondre({ leads: [] });
await lireLeads(FILTRES_VIDES);
assert.equal(vues.at(-1), "/api/leads", `aucun parametre attendu : ${vues.at(-1)}`);

repondre({ leads: [] });
await lireLeads({ ...FILTRES_VIDES, departement: "06" });
assert.equal(vues.at(-1), "/api/leads?departement=06");

// Les champs renseignes partent tous ; les vides restent absents. Le corpus est
// choisi pour que les deux cas coexistent dans la MEME requete : une requete
// entierement pleine ou entierement vide ne departagerait pas.
repondre({ leads: [] });
await lireLeads({ ...FILTRES_VIDES, departement: "06", limite: "5" });
assert.equal(vues.at(-1), "/api/leads?departement=06&limite=5");

// Un zero explicite est une saisie, pas une absence.
repondre({ leads: [] });
await lireLeads({ ...FILTRES_VIDES, montant_min: "0" });
assert.equal(vues.at(-1), "/api/leads?montant_min=0");

// --- Les refus : le motif fait l'aller-retour, intact ------------------------
//
// Le motif est une VALEUR du coeur. Le front la recoit dans `statistiques.ecartes`
// et la renvoie telle quelle : il filtre sur un vocabulaire qu'il ne connait pas.
// La chaine d'essai porte une espace et une esperluette — deux caracteres qui
// cassent une concatenation naive d'URL et qu'un encodage correct traverse.

const MOTIF = "motif avec espaces & signes";

repondre({ ecartes: [] });
await lireEcartes(FILTRES_VIDES, MOTIF);
assert.equal(
  vues.at(-1),
  "/api/ecartes?motif=motif+avec+espaces+%26+signes",
  `le motif doit partir encode, et vers /ecartes : ${vues.at(-1)}`,
);

// Les filtres de l'ecran accompagnent le motif : sans eux, la liste des refus
// decrirait une autre population que le decompte sur lequel on a clique.
repondre({ ecartes: [] });
await lireEcartes({ ...FILTRES_VIDES, departement: "06", mois: "6" }, "un-autre-motif");
assert.equal(vues.at(-1), "/api/ecartes?departement=06&mois=6&motif=un-autre-motif");

// --- La fiche d'un evenement : l'identifiant part dans le CHEMIN --------------

repondre({ lead: null, ecarte: null });
await lireEvenement("A20260153319");
assert.equal(vues.at(-1), "/api/evenements/A20260153319");

// Un identifiant porteur d'une barre oblique ou d'une espace changerait la
// route interrogee s'il partait brut — et la reponse serait un 404 plausible
// plutot qu'une erreur qui se voit.
repondre({ lead: null, ecarte: null });
await lireEvenement("A2026 015/3319");
assert.equal(vues.at(-1), "/api/evenements/A2026%20015%2F3319");

// --- L'aide de saisie : une route a elle, sans parametre ---------------------

repondre({ filtres: [] });
await lireFiltres();
assert.equal(vues.at(-1), "/api/filtres", "l'aide de saisie ne depend d'aucune saisie");

// --- Les sorties du flux : une date, ou rien ---------------------------------

repondre({ sorties: [] });
await lireSorties("");
assert.equal(vues.at(-1), "/api/sorties", "sans date, la route rend tout le journal");

repondre({ sorties: [] });
await lireSorties("2026-04-01");
assert.equal(vues.at(-1), "/api/sorties?depuis=2026-04-01");

// --- Le refus de l'API est remonte tel quel -----------------------------------

repondre({ detail: "departement illisible : 'xx'" }, 422);
await assert.rejects(
  () => lireLeads(FILTRES_VIDES),
  (souci: Error) => {
    assert.equal(souci.message, "departement illisible : 'xx'");
    return true;
  },
  "le message du serveur doit arriver intact jusqu'a l'ecran",
);

// Sans `detail`, le repli ne nomme que ce que le front connait de son cote.
repondre("pas du json objet", 500);
await assert.rejects(
  () => lireLeads(FILTRES_VIDES),
  (souci: Error) => {
    assert.ok(souci.message.includes("/leads"), souci.message);
    assert.ok(souci.message.includes("500"), souci.message);
    return true;
  },
);

// --- Une reponse valide arrive telle quelle -----------------------------------

repondre({ resume: "phrase du coeur", leads: [] });
const recue = await lireLeads(FILTRES_VIDES);
assert.equal(recue.resume, "phrase du coeur");

console.log("client.ts : toutes les assertions passent");
