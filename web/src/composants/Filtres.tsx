/**
 * Les filtres. Quatre champs vides, aucun defaut, aucune borne ecrite ici.
 *
 * Voir `api/client.ts` : ce que le front ne connait pas ne peut pas diverger du
 * coeur. Le formulaire ne se declenche qu'a la validation — une requete par
 * frappe ferait payer au serveur la vitesse de frappe, et le resume affiche
 * changerait sous les yeux du lecteur pendant qu'il le lit.
 *
 * ## L'unite de chaque champ vient de l'API
 *
 * Le libelle d'un champ est sa clef prettifiee, et **une clef ne dit pas son
 * unite**. Constate en usage reel sur cet ecran : « Avril » saisi dans `mois`,
 * et `limite=25` lue comme 25 millions d'euros. Les deux fois, le champ etait
 * correctement nomme et completement ambigu.
 *
 * L'aide de saisie vient donc de `/filtres` — description, defaut, bornes.
 * L'ecrire ici en ferait une valeur recopiee, celle qui derive au premier
 * elargissement de fenetre.
 *
 * Tant que `/filtres` n'a pas repondu, les champs restent utilisables sans
 * aide : une aide manquante gene, une saisie bloquee empeche.
 */

import { useState } from "react";

import { CHAMPS_FILTRES, type Filtres as Valeurs } from "../api/client";
import type { ReponseFiltres } from "../api/schema";
import { libelle, valeur } from "../format";

type Aide = ReponseFiltres["filtres"][number];

interface Props {
  valeurs: Valeurs;
  chargement: boolean;
  aides: ReponseFiltres | null;
  onValider: (valeurs: Valeurs) => void;
}

/** Ce que le champ attend, puis ce qu'il vaut si on le laisse vide. Les deux
 * viennent de l'API ; les bornes aussi, quand elle en declare. */
function Aide({ aide }: { aide: Aide }) {
  const bornes = [aide.minimum, aide.maximum]
    .filter((borne) => borne !== null)
    .map((borne) => valeur("borne", borne));

  return (
    <span className="filtre-aide">
      {aide.description}
      {bornes[0] ? ` [${bornes.join(" – ")}]` : null}
      {aide.defaut === null ? null : ` — ${libelle("defaut")} ${valeur("defaut", aide.defaut)}`}
    </span>
  );
}

export function Filtres({ valeurs, chargement, aides, onValider }: Props) {
  const [brouillon, setBrouillon] = useState<Valeurs>(valeurs);
  const parNom = new Map((aides?.filtres ?? []).map((aide) => [aide.nom, aide]));

  return (
    <form
      className="filtres"
      onSubmit={(evenement) => {
        evenement.preventDefault();
        onValider(brouillon);
      }}
    >
      {CHAMPS_FILTRES.map((cle) => {
        const aide = parNom.get(cle);
        return (
          <label className="filtre" key={cle}>
            <span className="filtre-clef">{libelle(cle)}</span>
            <input
              className="filtre-saisie"
              name={cle}
              onChange={(evenement) =>
                setBrouillon({ ...brouillon, [cle]: evenement.target.value })
              }
              value={brouillon[cle]}
            />
            {aide ? <Aide aide={aide} /> : null}
          </label>
        );
      })}
      <button className="valider" type="submit" disabled={chargement}>
        {chargement ? "…" : "Actualiser"}
      </button>
    </form>
  );
}
