/**
 * Les evenements REFUSES, pour un motif donne.
 *
 * ## Un ecarte n'est pas un lead, et sa forme le dit
 *
 * Ni score, ni classement, ni bloc de provenance, ni detail du calcul — parce
 * que l'API n'en rend aucun. Ce n'est pas une omission de l'affichage : lui
 * donner la forme d'un lead rouvrirait un chemin par lequel quelque chose qui
 * ressemble a un lead quitte le systeme sans etre passe par la porte unique
 * (`provenance.serialiser`). C'est le defaut de la Phase 3 bis, qui reviendrait
 * ici par une route d'audit.
 *
 * D'ou une **fiche de faits** et non une ligne classee : pas de rang, pas de
 * colonne de tete, pas de depliage. Ce qu'un refus doit porter, c'est son motif
 * et son `url_publication` — de quoi verifier chez le tiers que le refus est
 * fonde.
 *
 * ## Rien n'est enumere, et surtout pas compte
 *
 * Les champs sont rendus tels que l'API les envoie. Les deux nombres affiches
 * — combien correspondent au filtre, combien sont rendus — viennent d'elle
 * aussi : `correspondants` et `rendus`. Les recalculer depuis la liste
 * donnerait le second et jamais le premier, donc ferait passer une coupe pour
 * un resultat.
 */

import type { ReponseEcartes } from "../api/schema";
import { classeSegment, compte, libelle } from "../format";
import { Champs } from "./Champs";

interface Props {
  reponse: ReponseEcartes;
  /** Ouvre la fiche complete : revisions du fait et transitions du cedant, que
   * la liste ne porte pas. */
  onFiche: (identifiant: string) => void;
}

export function ListeEcartes({ reponse, onFiche }: Props) {
  return (
    <section className="ecartes">
      <p className="ecartes-compte">
        <strong>{compte(reponse.rendus)}</strong> {libelle("rendus")} —{" "}
        <strong>{compte(reponse.correspondants)}</strong> {libelle("correspondants")}
      </p>

      <ul className="ecartes-liste">
        {reponse.ecartes.map((ecarte) => (
          <li className={`ecarte ${classeSegment(ecarte.type_cedant)}`} key={ecarte.id}>
            <Champs entrees={Object.entries(ecarte)} />
            <p className="vers-la-fiche">
              <button className="lien" onClick={() => onFiche(ecarte.id)} type="button">
                {libelle("id")} {ecarte.id}
              </button>
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
