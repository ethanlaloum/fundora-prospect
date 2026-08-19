/**
 * La mise en forme, et rien d'autre.
 *
 * ## Tout libelle affiche est une CLEF, jamais une valeur
 *
 * La frontiere de la Phase 7 autorise le front a connaitre des clefs — le nom
 * d'un champ, le chemin d'une route — et lui interdit les valeurs : un motif de
 * refus, un libelle de segment, un seuil. Une table de traduction
 * `annonces_publiees -> "Annonces publiees au BODACC"` serait une valeur ecrite
 * ici, donc une copie du vocabulaire du coeur, donc une divergence a venir.
 *
 * D'ou `libelle`, qui n'invente rien : il rend la clef, ses tirets bas en
 * espaces. Une colonne du tableau porte donc le nom du champ de l'API qui
 * l'alimente. C'est un peu brut a lire, et c'est exactement ce qu'on veut sur
 * un outil d'audit : le lecteur voit quel champ il regarde.
 *
 * ## L'euro vient du NOM du champ
 *
 * `montant_eur` porte son unite dans sa clef. Formater en euros ce qui se
 * termine par `_eur` est donc une liaison structurelle, pas une hypothese sur
 * la donnee. Les evenements en francs, eux, sont rejetes par le parser bien
 * avant d'arriver ici — le front n'a aucune devise a decider.
 *
 * ## Les dates sont retournees, pas parsees
 *
 * `new Date("2026-08-19")` est interprete en UTC : dans un fuseau negatif,
 * l'affichage recule d'un jour. Une date d'acte fausse d'un jour sur une fiche
 * d'audit est un faux fait — et un faux fait se lit, quand une absence se voit.
 * On permute donc les trois morceaux de la chaine ISO, sans jamais construire
 * de `Date`.
 */

/** La clef, rendue lisible. Aucune traduction : voir l'entete. */
export function libelle(cle: string): string {
  return cle.replace(/_/g, " ");
}

const nombre = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });

const euros = new Intl.NumberFormat("fr-FR", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Rien de renseigne. Un tiret cadratin plutot qu'un mot : le vide se voit, et
 * aucun terme du coeur n'a a etre invente ici. */
export const VIDE = "—";

/**
 * Une valeur de l'API, mise en forme d'apres le NOM de son champ.
 *
 * Volontairement generique : les composants n'enumerent pas les champs qu'ils
 * savent afficher. Un champ ajoute au coeur apparait donc a l'ecran sans
 * qu'une ligne de front change — et surtout sans qu'un champ ajoute passe
 * inapercu faute d'avoir ete prevu ici.
 */
export function valeur(cle: string, brute: unknown): string {
  if (brute === null || brute === undefined) return VIDE;
  if (typeof brute === "boolean") return brute ? "oui" : "non";
  if (typeof brute === "number") {
    return cle.endsWith("_eur") ? euros.format(brute) : nombre.format(brute);
  }
  if (typeof brute === "string") {
    const jour = ISO.exec(brute);
    return jour ? `${jour[3]}/${jour[2]}/${jour[1]}` : brute;
  }
  return String(brute);
}

/** Un entier destine a un compteur. Meme formateur, nom distinct : un compteur
 * de population n'est pas une mesure, et les confondre a deja coute cher a ce
 * projet. */
export function compte(brut: number): string {
  return nombre.format(brut);
}

/**
 * La classe qui porte le SEGMENT du cedant.
 *
 * Le segment `pp` releve d'une base legale distincte de celle du segment `pm` :
 * la distinction doit se voir a l'ecran, sur un lead comme sur un refus. Elle
 * est composee a partir du CODE que l'API rend — le libelle, lui, s'affiche tel
 * quel et n'est jamais recopie dans le front.
 *
 * C'est une fonction et non une expression ecrite dans le JSX pour une raison
 * precise : ici elle s'execute sous test, la ou une classe montee en ligne dans
 * un composant ne serait gardee par rien. Ce qui reste non couvert est
 * l'endroit d'appel — passer une constante au lieu du champ du lead ferait
 * disparaitre la distinction sans qu'aucun test ne rougisse.
 */
export function classeSegment(type_cedant: string): string {
  return `segment__${type_cedant}`;
}
