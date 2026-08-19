/**
 * Les filtres. Quatre champs vides, aucun defaut, aucune borne.
 *
 * Voir `api/client.ts` : ce que le front ne connait pas ne peut pas diverger du
 * coeur. Le formulaire ne se declenche qu'a la validation — une requete par
 * frappe ferait payer au serveur la vitesse de frappe, et le resume affiche
 * changerait sous les yeux du lecteur pendant qu'il le lit.
 */

import { useState } from "react";

import { CHAMPS_FILTRES, type Filtres as Valeurs } from "../api/client";
import { libelle } from "../format";

interface Props {
  valeurs: Valeurs;
  chargement: boolean;
  onValider: (valeurs: Valeurs) => void;
}

export function Filtres({ valeurs, chargement, onValider }: Props) {
  const [brouillon, setBrouillon] = useState<Valeurs>(valeurs);

  return (
    <form
      className="filtres"
      onSubmit={(evenement) => {
        evenement.preventDefault();
        onValider(brouillon);
      }}
    >
      {CHAMPS_FILTRES.map((cle) => (
        <label className="filtre" key={cle}>
          <span className="filtre-clef">{libelle(cle)}</span>
          <input
            className="filtre-saisie"
            name={cle}
            value={brouillon[cle]}
            onChange={(evenement) =>
              setBrouillon({ ...brouillon, [cle]: evenement.target.value })
            }
          />
        </label>
      ))}
      <button className="valider" type="submit" disabled={chargement}>
        {chargement ? "…" : "Actualiser"}
      </button>
    </form>
  );
}
