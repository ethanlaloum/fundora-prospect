/**
 * Les trois voies sur les memes filtres, et les deux ecarts.
 *
 * ## Rien n'est calcule ici
 *
 * Les deux ecarts, les compteurs par voie, les durees et les tokens viennent
 * tous de l'API. Le front n'aligne pas deux listes pour voir si elles sont
 * egales : `effet_du_modele.identiques` est une AFFIRMATION du coeur, et c'est
 * ce qui la rend opposable.
 *
 * ## Le verdict avant les colonnes
 *
 * L'identite des deux voies est le point qui doit sauter aux yeux, et ce n'est
 * pas quelque chose que le lecteur deduit en comparant des chiffres — sinon on
 * lui ferait faire a la main le calcul qu'on interdit au JavaScript.
 *
 * ## Les deux ecarts ne partagent ni style ni mot
 *
 * `effet_du_modele` mesure ce que le modele a change ; `fraicheur_de_la_base`
 * mesure l'age de la derniere collecte. S'ils se ressemblaient, le second se
 * lirait comme le premier — et quelqu'un conclurait « le modele a filtre » sur
 * un ecart qui ne dit que l'anciennete d'un balayage.
 *
 * Aucune clef n'est nommee dans ce fichier : `lignesDEcart` les rend toutes.
 * C'est ce qui garantit qu'`arguments_respectes` reste colle a son ecart, quel
 * que soit le remaniement de mise en page.
 */

import type { ReponseComparatif } from "../api/schema";
import { lignesDEcart, presenterAnalyse } from "../comparatif";
import { compte, libelle, valeur } from "../format";
import { ListeLeads } from "./ListeLeads";

type Voie = ReponseComparatif["voies"]["direct"];

/** Les deux voies qui portent le comparatif. La base vient apres, en retrait —
 * elle mesure la fraicheur, pas le modele, et sa duree ecraserait les deux
 * autres a l'oeil sans rien dire du sujet. */
const PRINCIPALES = ["agent", "direct"] as const;

function Mesure({ nom, voie }: { nom: string; voie: Voie }) {
  return (
    <section className={`voie voie__${nom}`}>
      <h3>{libelle(nom)}</h3>
      <dl className="champs">
        {Object.entries(voie.mesure).map(([cle, brute]) =>
          // `appels_outil` est une liste d'objets : elle a son propre rendu.
          cle === "appels_outil" || cle === "ids_rendus" ? null : (
            <div className="champ" key={cle}>
              <dt>{libelle(cle)}</dt>
              <dd>{valeur(cle, brute)}</dd>
            </div>
          ),
        )}
      </dl>
    </section>
  );
}

/** Ce que le modele a REELLEMENT passe a l'outil. C'est la seule chose qui
 * puisse expliquer un ecart, et la cacher rendrait l'ecart mysterieux. */
function AppelsOutil({ appels }: { appels: Record<string, number | string>[] }) {
  return (
    <section className="appels">
      <h3>{libelle("appels_outil")}</h3>
      {appels[0] ? (
        <ul className="appels-liste">
          {appels.map((appel, rang) => (
            <li className="appel" key={JSON.stringify(appel)}>
              <span className="appel-rang">{compte(rang + 1)}</span>
              <dl className="champs">
                {Object.entries(appel).map(([cle, brute]) => (
                  <div className="champ" key={cle}>
                    <dt>{libelle(cle)}</dt>
                    <dd>{valeur(cle, brute)}</dd>
                  </div>
                ))}
              </dl>
            </li>
          ))}
        </ul>
      ) : (
        <p className="vide">Le modele n&rsquo;a appele aucun outil.</p>
      )}
    </section>
  );
}

function Ecart({ nom, ecart }: { nom: string; ecart: Parameters<typeof lignesDEcart>[0] }) {
  return (
    <section className={`ecart ecart__${nom}`}>
      <h3>{libelle(nom)}</h3>
      <dl className="champs">
        {lignesDEcart(ecart).map(([cle, brute]) => (
          <div className="champ" key={cle}>
            <dt>{libelle(cle)}</dt>
            <dd>{Array.isArray(brute) ? brute.join(", ") || "—" : valeur(cle, brute)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function Comparatif({ reponse }: { reponse: ReponseComparatif }) {
  const analyse = presenterAnalyse(reponse.analyse);
  const base = reponse.voies.base;

  return (
    <div className="comparatif">
      <div className="verdict">
        <Ecart ecart={reponse.effet_du_modele} nom="effet_du_modele" />
        <Ecart ecart={reponse.fraicheur_de_la_base} nom="fraicheur_de_la_base" />
      </div>

      <div className="voies">
        {PRINCIPALES.map((nom) => (
          <Mesure key={nom} nom={nom} voie={reponse.voies[nom]} />
        ))}
      </div>
      {base ? (
        <div className="voies voies--retrait">
          <Mesure nom="base" voie={base} />
        </div>
      ) : null}

      <AppelsOutil appels={reponse.voies.agent.mesure.appels_outil} />

      {/* L'analyse : zone visuellement distincte, jamais a la place d'un
          chiffre. Quand elle manque, la reserve prend sa place — la
          degradation se voit a l'ecran, pas seulement dans la reponse. */}
      <section className={analyse.disponible ? "analyse" : "analyse analyse--absente"}>
        <h3>{libelle("analyse")}</h3>
        <p className="analyse-texte">{analyse.texte}</p>
      </section>

      <ListeLeads analyses={analyse.encarts} leads={reponse.leads} onFiche={() => undefined} />
    </div>
  );
}
