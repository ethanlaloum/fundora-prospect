/**
 * Une grille clef / valeur, generique.
 *
 * Elle n'enumere aucun champ : elle rend ce qu'on lui donne. Deux surfaces s'en
 * servent — le depliage d'un lead et la fiche d'un ecarte — et c'est justement
 * pour ca qu'elle ne connait rien de l'un ni de l'autre. Un composant qui
 * saurait quels champs porte un lead saurait aussi les oublier.
 *
 * Seule exception, `url_publication` : elle sort en lien. C'est le champ qui
 * rend un fait verifiable par un tiers, et un lien se clique quand une chaine
 * se recopie a la main.
 */

import { libelle, valeur } from "../format";

export function Champs({ entrees }: { entrees: [string, unknown][] }) {
  return (
    <dl className="champs">
      {entrees.map(([cle, brute]) => (
        <div className="champ" key={cle}>
          <dt>{libelle(cle)}</dt>
          <dd>
            {cle === "url_publication" && typeof brute === "string" ? (
              <a href={brute} rel="noreferrer" target="_blank">
                {brute}
              </a>
            ) : (
              valeur(cle, brute)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
