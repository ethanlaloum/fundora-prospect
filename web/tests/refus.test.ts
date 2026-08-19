/**
 * Le contrat de refus, verifie sur une reponse **reellement produite par
 * l'API** et non sur une reponse fabriquee ici.
 *
 * ## Pourquoi ce fichier existe a part
 *
 * `client.test.ts` fabrique ses reponses. Il assertait qu'un `{detail: "…"}`
 * arrive intact jusqu'a l'ecran — c'est vrai, et ca ne prouvait rien : l'API
 * rendait `detail` sous forme de LISTE sur son second chemin d'erreur, celui
 * de la validation des parametres. Le front tombait alors sur son repli et
 * affichait « /leads : reponse 422 ».
 *
 * **Aucune mutation du code de production ne pouvait le reveler**, parce que le
 * test fabriquait son entree : le defaut n'etait pas dans le code teste, il
 * etait dans l'ecart entre l'entree du test et l'entree reelle.
 *
 * D'ou ce script : il ne fabrique rien. `tests/test_front_execute.py` interroge
 * la vraie API, ecrit sa reponse telle quelle dans un fichier, et la lui passe.
 * C'est le « au moins un test qui branche les deux modules l'un sur l'autre »
 * que ce projet s'impose pour chaque contrat.
 *
 * Usage :  node --experimental-strip-types refus.test.ts <corps.json>
 */

import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";

import { FILTRES_VIDES, lireLeads } from "../src/api/client.ts";

const chemin = process.argv[2];
assert.ok(chemin, "chemin du corps de reponse attendu en argument");

// Le fichier porte la reponse REELLE de l'API, statut compris : le laisser
// deviner ici rouvrirait la fabrication qu'on veut justement eviter.
const capture: { statut: number; corps: unknown; champs: string[] } = JSON.parse(
  readFileSync(chemin, "utf8"),
);

globalThis.fetch = () =>
  Promise.resolve(
    new Response(JSON.stringify(capture.corps), {
      status: capture.statut,
      headers: { "content-type": "application/json" },
    }),
  );

await assert.rejects(
  () => lireLeads(FILTRES_VIDES),
  (souci: Error) => {
    // Le repli — « /leads : reponse 422 » — est ce que le front affiche quand
    // il ne comprend pas le refus. Le voir ici signifie que le contrat a
    // change sans que le front le sache.
    assert.ok(
      !souci.message.includes(String(capture.statut)),
      `le front est retombe sur son repli : ${souci.message}`,
    );
    for (const champ of capture.champs) {
      assert.ok(
        souci.message.includes(champ),
        `le champ fautif ${champ} n'arrive pas a l'ecran : ${souci.message}`,
      );
    }
    return true;
  },
);

console.log("refus : le message de l'API arrive intact a l'ecran");
