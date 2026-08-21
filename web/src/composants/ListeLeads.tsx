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
import { classeSegment, jauge, libelle, rang, valeur } from "../format";
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
  /** `{id: analyse}` du modele, sur l'ecran de comparatif. L'encart se trouve
   * par ACCES A LA CLEF, jamais par appariement : chercher le bon lead pour
   * chaque analyse serait du recalcul, et un lead sans entree n'en invente
   * pas. Vide quand l'analyse est indisponible — donc aucun encart, et les
   * leads restent entiers. */
  analyses?: Record<string, string>;
}

function Fiche({
  lead,
  onFiche,
  analyse,
  index,
}: {
  lead: Lead;
  onFiche: Props["onFiche"];
  analyse: string | undefined;
  index: number;
}) {
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
      style={rang(index)}
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
            {/* La jauge accompagne le nombre, elle ne le remplace pas : une
                barre seule ferait estimer une valeur que l'API rend exacte.
                Elle cite une CLEF, comme les classes de cellule — sa largeur,
                elle, est calculee par la feuille de style. */}
            {cle === "score" ? (
              <span aria-hidden="true" className="jauge" style={jauge(lead.score)} />
            ) : null}
          </span>
        ))}
      </button>

      {analyse ? (
        // Zone visuellement distincte : c'est du commentaire, jamais la source
        // d'un chiffre. Elle vit hors du depliage pour rester lisible sans
        // ouvrir la carte.
        <p className="analyse-encart">{analyse}</p>
      ) : null}

      {ouvert ? (
        // L'enveloppe est de la MISE EN FORME, pas une decision : elle donne au
        // depliage une ligne de grille a animer, faute de quoi la hauteur ne
        // s'interpole pas. Ce qui est rendu a l'interieur, et quand, n'a pas
        // change — voir `.lead-deplie` dans la feuille de style.
        <div className="lead-deplie">
          <div className="lead-deplie-contenu">
            <DetailLead lead={lead} masquees={DANS_L_ENTETE} />
            <p className="vers-la-fiche">
              <button className="lien" onClick={() => onFiche(lead.id)} type="button">
                {libelle("id")} {lead.id}
              </button>
            </p>
          </div>
        </div>
      ) : null}
    </article>
  );
}

export function ListeLeads({ leads, onFiche, analyses }: Props) {
  return (
    <div className="leads">
      {/* La ligne de clefs, une fois pour toute la liste. Repetee sur chaque
          carte, elle occupait autant de place que les donnees et faisait lire
          vingt-cinq fois la meme chose.

          Elle rend les MEMES clefs, dans le meme ordre, sur la meme grille :
          une seconde liste de colonnes se serait desalignee au premier ajout.
          Sous 800 px, la grille se replie et cette ligne disparait au profit
          des clefs par cellule — la feuille de style bascule les deux ensemble,
          faute de quoi une colonne se lirait sans son nom. */}
      <div className="leads-entete">
        {COLONNES.map((cle) => (
          <span className={`cellule cellule__${cle}`} key={cle}>
            {libelle(cle)}
          </span>
        ))}
      </div>

      {leads.map((lead, index) => (
        <Fiche
          analyse={analyses?.[lead.id]}
          index={index}
          key={lead.id}
          lead={lead}
          onFiche={onFiche}
        />
      ))}
    </div>
  );
}
