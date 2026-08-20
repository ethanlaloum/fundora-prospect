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
  lireEcartes,
  lireComparatif,
  lireEvenement,
  lireFiltres,
  lireLeads,
  lireSorties,
  type Filtres as Valeurs,
} from "./api/client";
import type {
  ReponseComparatif,
  ReponseEcartes,
  ReponseEvenement,
  ReponseFiltres,
  ReponseLeads,
  ReponseSorties,
} from "./api/schema";
import { Comparatif } from "./composants/Comparatif";
import { Compteurs } from "./composants/Compteurs";
import { FicheEvenement } from "./composants/FicheEvenement";
import { Filtres } from "./composants/Filtres";
import { ListeEcartes } from "./composants/ListeEcartes";
import { ListeLeads } from "./composants/ListeLeads";
import { ListeSorties } from "./composants/ListeSorties";
import { libelle, valeur } from "./format";

function Requete({ reponse }: { reponse: ReponseLeads }) {
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
  const [reponse, setReponse] = useState<ReponseLeads | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [chargement, setChargement] = useState(true);

  const [motifOuvert, setMotifOuvert] = useState<string | null>(null);
  const [ecartes, setEcartes] = useState<ReponseEcartes | null>(null);
  const [erreurEcartes, setErreurEcartes] = useState<string | null>(null);

  const [ficheOuverte, setFicheOuverte] = useState<string | null>(null);
  const [fiche, setFiche] = useState<ReponseEvenement | null>(null);
  const [erreurFiche, setErreurFiche] = useState<string | null>(null);

  // L'aide de saisie : un seul appel, au chargement. Son echec n'est pas
  // remonte a l'ecran — les champs restent utilisables sans elle, et une
  // banniere rouge pour une aide manquante ferait croire a une panne.
  const [aides, setAides] = useState<ReponseFiltres | null>(null);

  // Le comparatif ne part QUE sur demande : il declenche un appel au modele et
  // une recherche BODACC. Le lancer au chargement ferait payer des tokens a qui
  // vient seulement lire ses leads.
  const [comparatif, setComparatif] = useState<ReponseComparatif | null>(null);
  const [erreurComparatif, setErreurComparatif] = useState<string | null>(null);
  const [comparaisonEnCours, setComparaison] = useState(false);

  const [depuis, setDepuis] = useState("");
  const [sorties, setSorties] = useState<ReponseSorties | null>(null);
  const [erreurSorties, setErreurSorties] = useState<string | null>(null);

  useEffect(() => {
    // `abandonne` evite qu'une reponse lente ecrase une reponse rapide partie
    // apres elle : l'ecran afficherait alors des chiffres qui ne correspondent
    // plus aux filtres visibles, ce qui se lit comme un resultat.
    let abandonne = false;
    setChargement(true);
    lireLeads(filtres)
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
    if (motifOuvert === null) {
      setEcartes(null);
      setErreurEcartes(null);
      return;
    }
    let abandonne = false;
    lireEcartes(filtres, motifOuvert)
      .then((recue) => {
        if (abandonne) return;
        setEcartes(recue);
        setErreurEcartes(null);
      })
      .catch((souci: unknown) => {
        if (abandonne) return;
        setEcartes(null);
        setErreurEcartes(souci instanceof Error ? souci.message : String(souci));
      });
    return () => {
      abandonne = true;
    };
  }, [filtres, motifOuvert]);

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

      <p className="lancer">
        <button
          className="valider"
          disabled={comparaisonEnCours}
          onClick={() => {
            setComparaison(true);
            lireComparatif(filtres)
              .then((recue) => {
                setComparatif(recue);
                setErreurComparatif(null);
              })
              .catch((souci: unknown) => {
                setComparatif(null);
                setErreurComparatif(souci instanceof Error ? souci.message : String(souci));
              })
              .finally(() => setComparaison(false));
          }}
          type="button"
        >
          {comparaisonEnCours ? "…" : "Comparer les trois voies"}
        </button>
      </p>

      {erreurComparatif ? <p className="erreur">{erreurComparatif}</p> : null}
      {comparatif ? <Comparatif reponse={comparatif} /> : null}

      <Filtres
        aides={aides}
        chargement={chargement}
        onValider={(saisis) => {
          // Les refus ouverts appartiennent a la recherche precedente : un
          // motif peut ne plus exister sous les nouveaux filtres, et sa liste
          // resterait a l'ecran comme si elle decrivait encore quelque chose.
          setMotifOuvert(null);
          setFiltres(saisis);
        }}
        valeurs={filtres}
      />

      {erreur ? <p className="erreur">{erreur}</p> : null}
      {erreurFiche ? <p className="erreur">{erreurFiche}</p> : null}
      {fiche ? (
        <FicheEvenement onFermer={() => setFicheOuverte(null)} reponse={fiche} />
      ) : null}

      {reponse ? (
        <>
          <p className="resume">{reponse.resume}</p>
          <Requete reponse={reponse} />
          <Compteurs
            motifOuvert={motifOuvert}
            onMotif={(motif) => setMotifOuvert(motif === motifOuvert ? null : motif)}
            statistiques={reponse.statistiques}
          />
          {erreurEcartes ? <p className="erreur">{erreurEcartes}</p> : null}
          {ecartes ? <ListeEcartes onFiche={setFicheOuverte} reponse={ecartes} /> : null}
          {reponse.statistiques.leads_rendus === 0 ? (
            <p className="vide">Aucun lead a afficher pour ces filtres.</p>
          ) : (
            <ListeLeads leads={reponse.leads} onFiche={setFicheOuverte} />
          )}
        </>
      ) : null}

      {erreurSorties ? <p className="erreur">{erreurSorties}</p> : null}
      {sorties ? (
        <ListeSorties depuis={depuis} onDepuis={setDepuis} reponse={sorties} />
      ) : null}
    </main>
  );
}
