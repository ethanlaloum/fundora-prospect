/**
 * Les sorties du flux : les cedants qui ont cesse, dates.
 *
 * ## Ce que ca vaut, et pourquoi ca merite un ecran
 *
 * `active -> cessee` date le moment ou la societe cedante a disparu, donc ou le
 * produit de cession est descendu aux associes. C'est la **date de sortie du
 * prospect**. Un decompte d'ecartes dit *combien* de societes cessees sont
 * refusees ; il ne dit jamais *depuis quand*. C'est la seule question que le
 * journal tranche, et elle n'etait visible nulle part.
 *
 * ## Deux grandeurs, jamais confondues
 *
 * `transitions_observees` compte TOUTES les bascules, `sorties_observees`
 * seulement celles qui font sortir du flux. Un `inconnu -> active` est une
 * bascule et n'est pas une perte. Les deux viennent de l'API — le front n'a
 * pas le droit de compter, et ici il n'en a meme pas les moyens : la liste ne
 * porte que les sortants.
 *
 * ## La fenetre part vide
 *
 * Comme les filtres de recherche : le front ne connait aucun defaut. Vide, la
 * route rend tout le journal, et l'ecran affiche la date que l'API dit avoir
 * retenue — pas celle que le front croit avoir demandee.
 */

import type { ReponseSorties } from "../api/schema";
import { compte, libelle, valeur } from "../format";
import { Champs } from "./Champs";

interface Props {
  reponse: ReponseSorties;
  depuis: string;
  onDepuis: (depuis: string) => void;
}

// Pas de lien vers une fiche : une sortie concerne une SOCIETE, et la seule
// route de detail est celle d'une ANNONCE. Fabriquer le lien demanderait de
// choisir laquelle de ses annonces ouvrir — un choix que l'API ne fait pas et
// que le front n'a pas a inventer. Le SIREN est affiche, il suffit a chercher.
export function ListeSorties({ reponse, depuis, onDepuis }: Props) {
  return (
    <section className="sorties">
      <h2>{libelle("sorties")}</h2>

      <label className="filtre filtre--seul">
        <span className="filtre-clef">{libelle("depuis")}</span>
        {/* `type="date"` rend exactement le format ISO que la route attend.
            Ce n'est pas du confort : une saisie libre obligerait le front a
            reformater, donc a connaitre le format d'un autre module. */}
        <input
          className="filtre-saisie"
          onChange={(evenement) => onDepuis(evenement.target.value)}
          type="date"
          value={depuis}
        />
      </label>

      <p className="sorties-compte">
        <strong>{compte(reponse.sorties_observees)}</strong> {libelle("sorties_observees")} —{" "}
        <strong>{compte(reponse.transitions_observees)}</strong>{" "}
        {libelle("transitions_observees")}
        {reponse.depuis ? ` — ${libelle("depuis")} ${valeur("depuis", reponse.depuis)}` : null}
      </p>

      {reponse.sorties[0] ? (
        <ul className="sorties-liste">
          {reponse.sorties.map((sortie) => (
            <li className="sortie" key={`${sortie.siren}-${sortie.observe_a}`}>
              <Champs entrees={Object.entries(sortie)} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="vide">
          Le journal ne porte aucune bascule sur cette fenetre. Il se remplit au
          second passage du job de collecte, quand un statut change.
        </p>
      )}
    </section>
  );
}
