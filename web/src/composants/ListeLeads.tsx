/**
 * La liste des leads, et le depliage d'un lead.
 *
 * ## L'ordre vient de l'API
 *
 * Les leads arrivent deja classes, du meilleur au moins bon. Le front ne trie
 * pas : un tri place devant un classement est un filtre — la lecon de la
 * Phase 4 — et un tri qui REORDONNE un classement produit un ordre que le coeur
 * n'a jamais decide, sans que rien ne le signale a l'ecran.
 *
 * ## Pas de tableau HTML, et ce n'est pas un choix esthetique
 *
 * Un `<table>` aurait demande `colSpan={COLONNES.length}` pour la ligne
 * depliee, c'est-a-dire un `.length` — que le verrou
 * `tests/test_front_ne_recalcule_rien.py` refuse. Le verrou est volontairement
 * brutal : un `.length` legitime est indiscernable a la lecture d'un `.length`
 * qui remplace un compteur de l'API.
 *
 * La sortie est une liste de fiches en grille CSS, ou chaque cellule porte le
 * NOM de son champ. Elle n'a donc pas de ligne d'en-tete a maintenir, elle
 * survit au retrecissement de l'ecran, et elle dit au lecteur quel champ il
 * regarde — ce qui est le sujet d'un outil d'audit.
 *
 * ## Le detail est generique, l'en-tete est choisi
 *
 * Les sept colonnes de l'en-tete sont une selection — un choix de mise en
 * forme, sur des clefs. Le depliage, lui, rend **tout le reste** du lead sans
 * l'enumerer : un champ ajoute par le coeur s'y affiche, au lieu d'y manquer en
 * silence.
 */

import { useState } from "react";

import type { ReponseLeads } from "../api/schema";
import { classeSegment, libelle, valeur } from "../format";
import { DetailLead } from "./DetailLead";

type Lead = ReponseLeads["leads"][number];

const COLONNES = [
  "score",
  "cedant",
  "type_cedant_libelle",
  "montant_eur",
  "jours_ecoules",
  "departement",
  "statut_cedant",
] as const;

/** Deja visibles dans l'en-tete de la ligne : les repeter dans le depliage
 * ferait lire deux fois la meme chose. `id` s'y ajoute — il n'est pas un fait
 * a lire mais la clef du lien vers la fiche, et il est affiche par le bouton. */
const DANS_L_ENTETE = new Set<string>([...COLONNES, "id"]);

interface Props {
  leads: ReponseLeads["leads"];
  /** Ouvre la fiche complete d'un evenement — revisions et transitions
   * comprises, que la liste ne porte pas. */
  onFiche: (identifiant: string) => void;
}

function Fiche({ lead, onFiche }: { lead: Lead; onFiche: Props["onFiche"] }) {
  const [ouvert, setOuvert] = useState(false);

  return (
    // Le segment du cedant devient une classe, composee a partir de la VALEUR
    // que l'API rend. Le front n'ecrit ni « pm » ni « pp » : il les recoit. Ce
    // qui est marque a l'ecran est une distinction de base legale, pas une
    // nuance de presentation — voir `segment__pp` dans la feuille de style.
    <article
      className={["lead", classeSegment(lead.type_cedant), ouvert ? "ouvert" : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <button
        aria-expanded={ouvert}
        className="lead-entete"
        onClick={() => setOuvert(!ouvert)}
        type="button"
      >
        {COLONNES.map((cle) => (
          <span className={`cellule cellule__${cle}`} key={cle}>
            <span className="cellule-clef">{libelle(cle)}</span>
            <span className="cellule-valeur">{valeur(cle, lead[cle])}</span>
          </span>
        ))}
      </button>

      {ouvert ? (
        <>
          <DetailLead lead={lead} masquees={DANS_L_ENTETE} />
          <p className="vers-la-fiche">
            <button className="lien" onClick={() => onFiche(lead.id)} type="button">
              {libelle("id")} {lead.id}
            </button>
          </p>
        </>
      ) : null}
    </article>
  );
}

export function ListeLeads({ leads, onFiche }: Props) {
  return (
    <div className="leads">
      {leads.map((lead) => (
        <Fiche key={lead.id} lead={lead} onFiche={onFiche} />
      ))}
    </div>
  );
}
