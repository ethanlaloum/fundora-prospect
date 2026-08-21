/**
 * Les compteurs de population, et le decompte des refus.
 *
 * ## Rien n'est enumere ici
 *
 * Le composant parcourt `statistiques` et rend ce qu'il y trouve, sans nommer un
 * seul compteur. Deux consequences, et la seconde est la vraie raison :
 *
 * - un compteur ajoute au coeur apparait a l'ecran sans qu'une ligne change ;
 * - un compteur ajoute au coeur **ne peut pas passer inapercu** faute d'avoir
 *   ete prevu ici. C'est le meme raisonnement que le test structurel des
 *   colonnes de fait : une liste ecrite a la main derive de sa source, une
 *   derivation ne le peut pas.
 *
 * ## Les reserves ne s'affichent que quand elles mordent
 *
 * `collecte_partielle` et `plafond_atteint` ne sont montres que **vrais**. Une
 * mise en garde permanente cesse d'etre lue — et ces deux-la disent que le
 * chiffre d'a cote ne couvre pas tout ce qu'il a l'air de couvrir.
 *
 * ## Les motifs de refus sont IMPRIMES, jamais ecrits
 *
 * Les clefs d'`ecartes` sont les motifs decides par le coeur. Le front les
 * affiche sans en connaitre un seul : c'est exactement la frontiere de la
 * Phase 7, et `tests/test_front_sans_vocabulaire.py` echouerait si l'un d'eux
 * etait recopie ici.
 *
 * **Les motifs ne sont plus cliquables**, et c'est une regression assumee.
 * Le tirage passait par `/ecartes`, qui LIT LA BASE — or l'ecran est alimente
 * depuis le chemin direct depuis que « Actualiser » passe par le modele. Les
 * deux populations different : le compte affiche sur la pastille et la liste
 * tiree derriere auraient parle de deux choses en disant le meme mot.
 *
 * Deux chiffres qui se contredisent a l'ecran valent moins que pas de tirage.
 * Le retablir demande une route `/ecartes` qui interroge la source, pas la
 * base — un aller-retour de coeur, pas un raccourci de front.
 *
 * La liste vide ne rend rien — et il n'y a pas de cas « aucun refus » a ecrire,
 * parce que le constater demanderait de compter, ce que le front ne fait pas
 * (`tests/test_front_ne_recalcule_rien.py`). La contrainte a simplifie le
 * composant plutot que de le compliquer.
 */

import type { ReponseRecherche } from "../api/schema";
import { compte, libelle, rang } from "../format";

// Les compteurs du CHEMIN DIRECT, pas ceux de la base : ce ne sont pas les
// memes populations, donc pas les memes clefs. Le composant, lui, n'en nomme
// aucune — il rend ce qu'il recoit. Typer la source reelle plutot qu'une forme
// permissive fait dire au type d'ou viennent ces chiffres.
type Statistiques = ReponseRecherche["outil"]["statistiques"];

interface Props {
  statistiques: Statistiques;
}

export function Compteurs({ statistiques }: Props) {
  const entrees = Object.entries(statistiques);

  return (
    <section className="population">
      <ul className="compteurs">
        {entrees.map(([cle, brute], index) =>
          typeof brute === "number" ? (
            // Le rang sert au decalage de la cascade, jamais a la donnee : il
            // ordonne l'apparition des cartes, il ne decrit aucune population.
            <li className="compteur" key={cle} style={rang(index)}>
              <span className="compteur-valeur">{compte(brute)}</span>
              <span className="compteur-clef">{libelle(cle)}</span>
            </li>
          ) : null,
        )}
      </ul>

      {entrees.map(([cle, brute]) =>
        brute === true ? (
          <p className="reserve" key={cle}>
            {libelle(cle)}
          </p>
        ) : null,
      )}

      <ul className="refus">
        {Object.entries(statistiques.ecartes).map(([motif, combien]) => (
          <li className="refus-motif" key={motif}>
            <span className="refus-compte">{compte(combien)}</span>
            <span className="refus-libelle">{motif}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
