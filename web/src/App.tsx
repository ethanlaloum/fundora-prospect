/**
 * L'ecran. Il assemble, il n'interprete pas.
 *
 * ## Ce qui est affiche vient de la reponse, y compris la phrase
 *
 * `resume` est la seule redaction du projet, ecrite par `pipeline.resumer`. La
 * recopier ou la reformuler ici en ferait une seconde redaction — celle qui
 * dira « 25 classables » le jour ou le coeur dira « 49 classables parmi les 50
 * enrichis ». Le front l'imprime.
 *
 * De meme, `departements`, `periode` et `montant_min_eur` sont affiches depuis
 * la REPONSE et non depuis les filtres saisis : quand les champs sont vides,
 * c'est le coeur qui a decide, et l'ecran doit montrer ce qu'il a decide —
 * pas ce que le front croit avoir demande.
 *
 * ## Un etat vide n'est pas un compte a zero
 *
 * L'absence de leads se lit sur `leads_rendus`, un compteur rendu par l'API, et
 * non sur la longueur du tableau. Les deux coincident aujourd'hui ; ils
 * cesseront de coincider le jour ou une coupe s'insere entre les deux, et c'est
 * exactement le defaut « le compteur decrit un budget, pas une population » que
 * ce projet a deja paye trois fois.
 *
 * ## Deux chargements separes, et deux erreurs separees
 *
 * Les refus ne sont pas dans la reponse de `/leads` : les compter et les lister
 * sont deux questions, et la seconde ne se pose que si on clique. Un echec sur
 * l'une ne doit pas effacer l'autre — un ecran qui se vide entierement parce
 * qu'une liste secondaire a echoue fait disparaitre le resume et les compteurs,
 * c'est-a-dire ce qui permettait de comprendre ce qui se passe.
 */

import { useEffect, useState } from "react";

import {
  FILTRES_VIDES,
  lireEvenement,
  lireFiltres,
  lireRecherche,
  lireSorties,
  type Filtres as Valeurs,
} from "./api/client";
import type {
  ReponseEvenement,
  ReponseFiltres,
  ReponseRecherche,
  ReponseSorties,
} from "./api/schema";
import { Compteurs } from "./composants/Compteurs";
import { FicheEvenement } from "./composants/FicheEvenement";
import { Filtres } from "./composants/Filtres";
import { ListeLeads } from "./composants/ListeLeads";
import { ListeSorties } from "./composants/ListeSorties";
import { presenterAnalyse } from "./comparatif";
import { libelle, valeur } from "./format";

function Requete({ reponse }: { reponse: ReponseRecherche["outil"] }) {
  return (
    <dl className="requete">
      <div className="champ">
        <dt>{libelle("departements")}</dt>
        <dd>{reponse.departements.join(", ")}</dd>
      </div>
      <div className="champ">
        <dt>{libelle("periode")}</dt>
        <dd>
          {valeur("debut", reponse.periode.debut)} → {valeur("fin", reponse.periode.fin)}
        </dd>
      </div>
      <div className="champ">
        <dt>{libelle("montant_min_eur")}</dt>
        <dd>{valeur("montant_min_eur", reponse.montant_min_eur)}</dd>
      </div>
    </dl>
  );
}

export function App() {
  const [filtres, setFiltres] = useState<Valeurs>(FILTRES_VIDES);
  const [reponse, setReponse] = useState<ReponseRecherche | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [chargement, setChargement] = useState(true);

  const [ficheOuverte, setFicheOuverte] = useState<string | null>(null);
  const [fiche, setFiche] = useState<ReponseEvenement | null>(null);
  const [erreurFiche, setErreurFiche] = useState<string | null>(null);

  // L'aide de saisie : un seul appel, au chargement. Son echec n'est pas
  // remonte a l'ecran — les champs restent utilisables sans elle, et une
  // banniere rouge pour une aide manquante ferait croire a une panne.
  const [aides, setAides] = useState<ReponseFiltres | null>(null);

  const [depuis, setDepuis] = useState("");
  const [sorties, setSorties] = useState<ReponseSorties | null>(null);
  const [erreurSorties, setErreurSorties] = useState<string | null>(null);

  useEffect(() => {
    // `abandonne` evite qu'une reponse lente ecrase une reponse rapide partie
    // apres elle : l'ecran afficherait alors des chiffres qui ne correspondent
    // plus aux filtres visibles, ce qui se lit comme un resultat.
    let abandonne = false;
    setChargement(true);
    lireRecherche(filtres)
      .then((recue) => {
        if (abandonne) return;
        setReponse(recue);
        setErreur(null);
      })
      .catch((souci: unknown) => {
        if (abandonne) return;
        setReponse(null);
        setErreur(souci instanceof Error ? souci.message : String(souci));
      })
      .finally(() => {
        if (!abandonne) setChargement(false);
      });
    return () => {
      abandonne = true;
    };
  }, [filtres]);

  useEffect(() => {
    if (ficheOuverte === null) {
      setFiche(null);
      setErreurFiche(null);
      return;
    }
    let abandonne = false;
    lireEvenement(ficheOuverte)
      .then((recue) => {
        if (abandonne) return;
        setFiche(recue);
        setErreurFiche(null);
      })
      .catch((souci: unknown) => {
        if (abandonne) return;
        setFiche(null);
        setErreurFiche(souci instanceof Error ? souci.message : String(souci));
      });
    return () => {
      abandonne = true;
    };
    // La fiche ne depend PAS des filtres : elle designe un cas par son
    // identifiant, pas une population. La recharger a chaque changement de
    // filtre laisserait croire qu'elle en depend.
  }, [ficheOuverte]);

  useEffect(() => {
    let abandonne = false;
    lireFiltres()
      .then((recue) => {
        if (!abandonne) setAides(recue);
      })
      .catch(() => undefined);
    return () => {
      abandonne = true;
    };
  }, []);

  useEffect(() => {
    let abandonne = false;
    lireSorties(depuis)
      .then((recue) => {
        if (abandonne) return;
        setSorties(recue);
        setErreurSorties(null);
      })
      .catch((souci: unknown) => {
        if (abandonne) return;
        setSorties(null);
        setErreurSorties(souci instanceof Error ? souci.message : String(souci));
      });
    return () => {
      abandonne = true;
    };
    // Les sorties ne dependent pas non plus des filtres de recherche : une
    // sortie du flux est un fait date sur un cedant, pas une population.
  }, [depuis]);

  return (
    <main className="page">
      <header className="entete">
        <h1>fundora-prospect</h1>
        <p className="sous-titre">
          Cessions de fonds de commerce publiees au BODACC. Le prospect est la
          societe cedante, celle qui encaisse.
        </p>
      </header>

      <Filtres
        aides={aides}
        chargement={chargement}
        onValider={setFiltres}
        valeurs={filtres}
      />

      {erreur ? <p className="erreur">{erreur}</p> : null}
      {erreurFiche ? <p className="erreur">{erreurFiche}</p> : null}
      {fiche ? (
        <FicheEvenement onFermer={() => setFicheOuverte(null)} reponse={fiche} />
      ) : null}

      {reponse ? (
        <>
          <p className="resume">{reponse.outil.resume}</p>
          <Requete reponse={reponse.outil} />
          <Compteurs statistiques={reponse.outil.statistiques} />

          {/* L'analyse du modele : zone visuellement distincte, jamais a la
              place d'un chiffre. Quand elle manque — clef absente, panne, solde
              epuise — la reserve prend sa place et les leads restent entiers.
              La degradation doit SE VOIR, pas seulement figurer dans la
              reponse. */}
          {(() => {
            const analyse = presenterAnalyse(reponse.analyse);
            return (
              <>
                <section
                  className={analyse.disponible ? "analyse" : "analyse analyse--absente"}
                >
                  <h3>{libelle("analyse")}</h3>
                  <p className="analyse-texte">{analyse.texte}</p>
                </section>

                {reponse.outil.statistiques.leads_rendus === 0 ? (
                  <p className="vide">Aucun lead a afficher pour ces filtres.</p>
                ) : (
                  <ListeLeads
                    analyses={analyse.encarts}
                    leads={reponse.outil.leads}
                    onFiche={setFicheOuverte}
                  />
                )}
              </>
            );
          })()}
        </>
      ) : null}

      {erreurSorties ? <p className="erreur">{erreurSorties}</p> : null}
      {sorties ? (
        <ListeSorties depuis={depuis} onDepuis={setDepuis} reponse={sorties} />
      ) : null}
    </main>
  );
}
