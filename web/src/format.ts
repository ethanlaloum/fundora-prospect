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

import type { CSSProperties } from "react";

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
 * Le rang d'un element dans sa liste, passe au CSS.
 *
 * Il sert au decalage de la cascade — chaque ligne apparait un cran apres la
 * precedente. Le calcul du delai, son pas et son plafond vivent dans la feuille
 * de style : le front ne multiplie rien, il transmet un rang. Ecrire
 * `index * 24` ici mettrait une duree dans du TypeScript, hors du fichier de
 * jetons, ou aucun verrou ne la verrait.
 *
 * Ce n'est pas un compteur : le rang ne decrit aucune population, il ordonne
 * des elements deja rendus. Un `.length` n'aurait pas ete permis, celui-ci
 * l'est — et il s'execute sous test, ce qu'une expression ecrite dans le JSX
 * ne ferait pas.
 */
export function rang(index: number): CSSProperties {
  return { "--rang": index } as CSSProperties;
}

/**
 * Le score, passe au CSS pour etre dessine.
 *
 * Meme regle que `rang` : le front transmet la valeur, la feuille de style en
 * fait une largeur. Ecrire la proportion ici la mettrait dans du TypeScript, et
 * surtout ferait passer un champ numerique de l'API dans une expression —
 * exactement ce que `tests/test_front_ne_recalcule_rien.py` interdit.
 *
 * Le jeton s'appelle `--jauge` et NON `--score`, pour la meme raison que les
 * graisses s'appellent `--graisse-*` : un tiret devant le nom d'un champ
 * numerique se lit comme une soustraction pour un balayage textuel, et le
 * verrou l'a signale des la premiere execution. Il avait raison de le faire —
 * distinguer les deux demanderait de savoir lire le CSS, pas de chercher un
 * motif. C'est la troisieme fois sur ce projet : un nom de jeton ne reprend
 * jamais un nom de champ.
 *
 * La jauge ne remplace pas le nombre, elle l'accompagne : une barre seule
 * demanderait au lecteur d'estimer une valeur que l'API a rendue exacte.
 */
export function jauge(score: number): CSSProperties {
  return { "--jauge": score } as CSSProperties;
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
