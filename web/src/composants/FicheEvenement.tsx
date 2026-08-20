/**
 * La fiche d'un evenement : le seul endroit qui reponde a « pourquoi
 * celui-la ? ».
 *
 * ## Un lead OU un refus, jamais les deux
 *
 * L'API garantit l'invariant, un test le verrouille dans les deux sens, et
 * l'ecran le montre : un prospect et son refus ne coexistent pas.
 *
 * ## Le journal dit A QUI il se rapporte
 *
 * `transitions` arrive vide dans deux situations qui n'ont rien a voir : le
 * cedant n'a jamais change de statut, ou **aucun cedant n'est identifie**. Cote
 * API, la seconde est une branche a un `if` — sans elle, `transitions(siren=None)`
 * perd son filtre et rend le journal de TOUTES les societes, presente comme
 * celui-ci. Pas une fuite : une attribution fausse, ce qui est pire dans une
 * fiche d'audit, parce qu'une absence declenche une verification quand un faux
 * fait la remplace.
 *
 * Le front ne peut pas deviner laquelle des deux — et n'a pas a le faire. Il
 * affiche le SIREN auquel le journal se rapporte, juste au-dessus. Un tiret
 * cadratin a cette place dit tout : aucune societe n'est nommee, donc aucune
 * bascule ne peut lui etre attribuee.
 *
 * ## Les listes vides se declarent, sans etre comptees
 *
 * `revisions[0]` plutot que `revisions.length` : le verrou interdit de compter,
 * et c'est ici exactement ce qu'il faut faire — savoir s'il y a un premier
 * element n'est pas denombrer une population. Une section vide et muette se
 * lirait comme une section qui n'a pas fini de charger.
 */

import type { ReactNode } from "react";

import type { ReponseEvenement } from "../api/schema";
import { classeSegment, libelle, valeur, VIDE } from "../format";
import { Champs } from "./Champs";
import { DetailLead } from "./DetailLead";

interface Props {
  reponse: ReponseEvenement;
  onFermer: () => void;
}

function Section({
  titre,
  attribution,
  vide,
  children,
}: {
  titre: string;
  /** A qui ou a quoi cette section se rapporte. Rendue MEME quand la section
   * est vide : c'est justement la qu'elle porte l'information. */
  attribution?: ReactNode;
  vide: boolean;
  children: ReactNode;
}) {
  return (
    <section className="fiche-section">
      <h3>{titre}</h3>
      {attribution ? <p className="attribution">{attribution}</p> : null}
      {vide ? <p className="vide">{VIDE}</p> : children}
    </section>
  );
}

export function FicheEvenement({ reponse, onFermer }: Props) {
  const porteur = reponse.lead ?? reponse.ecarte;
  const identifiant = porteur?.id ?? null;
  const siren = porteur?.siren ?? null;

  return (
    <article
      className={["fiche", porteur ? classeSegment(porteur.type_cedant) : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <header className="fiche-entete">
        <h2>
          {libelle("id")} {valeur("id", identifiant)}
        </h2>
        <button className="fermer" onClick={onFermer} type="button">
          ✕
        </button>
      </header>

      {reponse.lead ? <DetailLead lead={reponse.lead} /> : null}
      {reponse.ecarte ? (
        <div className="fiche-refus">
          <Champs entrees={Object.entries(reponse.ecarte)} />
        </div>
      ) : null}

      <Section titre={libelle("revisions")} vide={!reponse.revisions[0]}>
        <ul className="revisions">
          {reponse.revisions.map((revision) => (
            <li className="revision" key={revision.remplacee_a}>
              <p className="revision-date">
                {libelle("remplacee_a")} {valeur("remplacee_a", revision.remplacee_a)}
              </p>
              <Champs entrees={Object.entries(revision.contenu)} />
            </li>
          ))}
        </ul>
      </Section>

      <Section
        attribution={
          <>
            {libelle("siren")} <strong>{valeur("siren", siren)}</strong>
          </>
        }
        titre={libelle("transitions")}
        vide={!reponse.transitions[0]}
      >
        <ul className="transitions">
          {reponse.transitions.map((transition) => (
            <li className="transition" key={`${transition.observe_a}-${transition.statut_apres}`}>
              <Champs entrees={Object.entries(transition)} />
            </li>
          ))}
        </ul>
      </Section>
    </article>
  );
}
