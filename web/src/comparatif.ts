/**
 * La logique de l'analyse — pure, donc testable sans navigateur.
 *
 * Deux proprietes de l'ecran ne devaient pas dependre d'une mise en page : un
 * remaniement de JSX ne doit pas pouvoir les casser en silence. Elles sont donc
 * portees par des fonctions, et `web/tests/comparatif.test.ts` les exerce.
 *
 * ## 1. La degradation est un etat rendu, pas une absence
 *
 * `presenterAnalyse` rend deux formes explicites — le texte, ou la reserve —
 * et **jamais rien**. Un composant qui n'afficherait rien quand l'analyse
 * manque laisserait croire qu'il n'y avait rien a dire. C'est le cas qui
 * arrivera en demonstration le jour ou la clef expire.
 *
 * ## 2. Le rattachement se fait par CLEF
 *
 * `encarts[lead.id]` est un acces, pas un appariement. Une boucle qui
 * chercherait le bon lead pour chaque analyse serait du recalcul, et le front
 * n'a pas le droit d'en faire.
 */

import type { ReponseRecherche } from "./api/schema";

export interface Analyse {
  disponible: boolean;
  texte: string;
  /** `{id: analyse}`. Vide quand l'analyse manque — donc aucun encart. */
  encarts: Record<string, string>;
}

/**
 * Ce que l'ecran doit montrer de l'analyse, dans les deux etats.
 *
 * Quand elle manque, on rend la RESERVE — le motif que l'API donne — et pas
 * une chaine vide : la degradation doit se voir a l'ecran, pas seulement dans
 * la reponse.
 */
export function presenterAnalyse(analyse: ReponseRecherche["analyse"]): Analyse {
  if (analyse.disponible) {
    return { disponible: true, texte: analyse.synthese, encarts: analyse.par_lead };
  }
  return {
    disponible: false,
    // Le repli ne formule rien : si l'API ne dit pas pourquoi, l'ecran dit
    // qu'elle ne l'a pas dit. Inventer un motif ici serait ecrire une valeur
    // dans le front.
    texte: analyse.reserve ?? "",
    encarts: {},
  };
}
