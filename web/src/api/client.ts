/**
 * La frontiere avec l'API, et le seul endroit du front ou du JSON devient un
 * type.
 *
 * ## Aucun defaut n'est recopie ici — un champ vide n'est pas envoye
 *
 * L'API a des defauts (la region, la fenetre en mois, la limite) et des bornes
 * (`MOIS_MAX`, `LIMITE_MAX`). Les repeter dans le front — en valeur initiale
 * d'un `<input>`, en attribut `min`/`max`, en texte indicatif — serait ecrire
 * des VALEURS dans le front : precisement ce que la Phase 7 s'interdit, et
 * precisement ce qui derive au premier elargissement de fenetre.
 *
 * Le front part donc de champs **vides** et n'envoie que ce qui est saisi. La
 * premiere requete ne porte aucun parametre : c'est le coeur qui decide, et sa
 * reponse dit ce qu'il a retenu (`departements`, `periode`, `montant_min_eur`),
 * ce que l'ecran affiche. Un defaut qu'on ne connait pas ne peut pas diverger.
 *
 * Meme raisonnement pour les bornes : le front envoie ce qu'on saisit et
 * **affiche le refus** tel qu'il vient (422 et son `detail`, qui dit deja la
 * forme attendue).
 *
 * ## Le seul `as` du front
 *
 * `fetch` rend du non-type par construction : c'est ici, et nulle part ailleurs,
 * que la forme des reponses est affirmee, en s'appuyant sur `schema.d.ts` —
 * genere depuis des reponses REELLES et regenere par `tests/test_types_web.py`,
 * qui echoue si le fichier est perime. Passe cette ligne, `tsc --noEmit` en mode
 * strict fait le reste : un champ que l'API ne rend pas ne compile pas.
 */

import type { ReponseLeads } from "./schema";

/** Le proxy Vite ; l'API elle-meme n'ecoute que sur la boucle locale. */
const BASE = "/api";

/**
 * Les filtres, en texte brut de bout en bout.
 *
 * Pas de conversion en nombre : le front n'a rien a calculer, et une valeur
 * qu'il ne parse pas est une valeur qu'il ne peut pas deformer. La validation
 * appartient a FastAPI, qui la fait deja.
 */
export interface Filtres {
  departement: string;
  mois: string;
  montant_min: string;
  limite: string;
}

/** Les champs, dans l'ordre d'affichage. Ce sont des noms de parametres de la
 * route — des clefs, donc, pas des valeurs. */
export const CHAMPS_FILTRES = ["departement", "mois", "montant_min", "limite"] as const;

export const FILTRES_VIDES: Filtres = {
  departement: "",
  mois: "",
  montant_min: "",
  limite: "",
};

/** Ce que l'API renvoie quand elle refuse un argument : son message, tel quel. */
interface Refus {
  detail?: unknown;
}

async function lire<T>(chemin: string, parametres: Filtres): Promise<T> {
  const requete = new URLSearchParams();
  for (const [cle, saisie] of Object.entries(parametres)) {
    // Un champ vide n'est pas un filtre : ne pas l'envoyer laisse le defaut du
    // coeur s'appliquer, au lieu de le deviner ici.
    if (saisie !== "") requete.set(cle, saisie);
  }

  const reponse = await fetch(`${BASE}${chemin}?${requete}`);
  const corps: unknown = await reponse.json().catch(() => null);

  if (!reponse.ok) {
    // Le message vient du serveur — le front n'a pas a formuler un refus qu'il
    // n'a pas decide. Le repli ne nomme que la route et le code HTTP, deux
    // choses qu'il connait de son cote de la frontiere.
    const detail = (corps as Refus | null)?.detail;
    throw new Error(
      typeof detail === "string" ? detail : `${chemin} : reponse ${reponse.status}`,
    );
  }
  return corps as T;
}

export function lireLeads(filtres: Filtres): Promise<ReponseLeads> {
  return lire<ReponseLeads>("/leads", filtres);
}
