/**
 * La logique du comparatif — pure, donc testable sans navigateur.
 *
 * Trois proprietes de cet ecran ne devaient pas dependre d'une mise en page :
 * un remaniement de JSX ne doit pas pouvoir les casser en silence. Elles sont
 * donc portees par des fonctions, pas par la structure des composants, et
 * `web/tests/comparatif.test.ts` les exerce.
 *
 * ## 1. La cause reste collee a son ecart
 *
 * `arguments_respectes` explique pourquoi `effet_du_modele` serait faux. Les
 * separer laisserait lire un ecart sans sa cause — et un ecart sans cause se
 * lit comme une explication.
 *
 * `lignesDEcart` rend **toutes** les clefs de l'objet, sans en nommer aucune.
 * La cause n'est donc pas affichee parce que quelqu'un s'en est souvenu : elle
 * l'est parce qu'elle est dans l'objet. La retirer de l'ecran demanderait de
 * retirer l'affichage generique, ce qu'un test attrape.
 *
 * ## 2. La degradation est un etat rendu, pas une absence
 *
 * `presenterAnalyse` rend deux formes explicites — le texte, ou la reserve —
 * et **jamais rien**. Un composant qui n'afficherait rien quand l'analyse
 * manque laisserait croire qu'il n'y avait rien a dire. C'est le cas qui
 * arrivera en demonstration le jour ou la clef expire.
 *
 * ## 3. Le rattachement se fait par CLEF
 *
 * `encarts[lead.id]` est un acces, pas un appariement. Une boucle qui
 * chercherait le bon lead pour chaque analyse serait du recalcul, et le front
 * n'a pas le droit d'en faire.
 */

import type { ReponseComparatif } from "./api/schema";

type Ecart = ReponseComparatif["effet_du_modele"] | ReponseComparatif["fraicheur_de_la_base"];

/**
 * Les lignes d'un ecart, dans l'ordre de l'API, **sans en nommer aucune**.
 *
 * C'est ce qui garantit qu'`arguments_respectes` ne peut pas etre separe
 * d'`effet_du_modele` : le front ne sait pas qu'il existe, il rend ce que
 * l'objet contient. Un champ ajoute demain a l'ecart apparait a l'ecran ; un
 * champ retire disparait — et aucun des deux ne demande de toucher au JSX.
 */
export function lignesDEcart(ecart: Ecart): [string, unknown][] {
  return Object.entries(ecart);
}

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
export function presenterAnalyse(analyse: ReponseComparatif["analyse"]): Analyse {
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
