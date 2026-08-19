/**
 * Le detail d'un lead : ses champs, le calcul de son score, sa provenance.
 *
 * Partage entre le depliage d'une ligne de la liste et la fiche d'un evenement.
 * Deux rendus separes auraient fini par diverger — l'un montrant un champ que
 * l'autre oublie — et c'est precisement sur le detail du calcul que la
 * contrainte 5 interdit de varier : le breakdown doit etre le meme partout.
 */

import type { ReponseLeads } from "../api/schema";
import { libelle, valeur } from "../format";
import { Champs } from "./Champs";

type Lead = ReponseLeads["leads"][number];

const COLONNES_CONTRIBUTION = ["critere", "points", "poids", "motif"] as const;

/** Rendu ailleurs, ou rendu a part : les deux sous-objets, et l'URL — que le
 * bloc de provenance porte deja. La provenance est la porte de sortie du lead :
 * c'est elle qui fait foi sur l'URL, pas une copie a cote. */
const A_PART = new Set<string>(["breakdown", "provenance", "url_publication"]);

function Contributions({ lead }: { lead: Lead }) {
  return (
    <table className="breakdown">
      <thead>
        <tr>
          {COLONNES_CONTRIBUTION.map((cle) => (
            <th key={cle}>{libelle(cle)}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {lead.breakdown.map((contribution) => (
          <tr key={contribution.critere}>
            {COLONNES_CONTRIBUTION.map((cle) => (
              <td className={`contribution__${cle}`} key={cle}>
                {valeur(cle, contribution[cle])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

interface Props {
  lead: Lead;
  /** Les clefs deja montrees ailleurs par l'appelant — l'en-tete d'une ligne
   * de liste, par exemple. Vide pour une fiche, qui montre tout. */
  masquees?: ReadonlySet<string>;
}

export function DetailLead({ lead, masquees }: Props) {
  const reste = Object.entries(lead).filter(
    ([cle]) => !A_PART.has(cle) && !masquees?.has(cle),
  );

  return (
    <div className="lead-detail">
      <Champs entrees={reste} />
      <Contributions lead={lead} />
      <Champs entrees={Object.entries(lead.provenance)} />
    </div>
  );
}
