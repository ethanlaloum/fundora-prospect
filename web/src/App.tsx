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
 */

import { useEffect, useState } from "react";

import { FILTRES_VIDES, lireLeads, type Filtres as Valeurs } from "./api/client";
import type { ReponseLeads } from "./api/schema";
import { Compteurs } from "./composants/Compteurs";
import { Filtres } from "./composants/Filtres";
import { ListeLeads } from "./composants/ListeLeads";
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

  return (
    <main className="page">
      <header className="entete">
        <h1>fundora-prospect</h1>
        <p className="sous-titre">
          Cessions de fonds de commerce publiees au BODACC. Le prospect est la
          societe cedante, celle qui encaisse.
        </p>
      </header>

      <Filtres chargement={chargement} onValider={setFiltres} valeurs={filtres} />

      {erreur ? <p className="erreur">{erreur}</p> : null}

      {reponse ? (
        <>
          <p className="resume">{reponse.resume}</p>
          <Requete reponse={reponse} />
          <Compteurs statistiques={reponse.statistiques} />
          {reponse.statistiques.leads_rendus === 0 ? (
            <p className="vide">Aucun lead a afficher pour ces filtres.</p>
          ) : (
            <ListeLeads leads={reponse.leads} />
          )}
        </>
      ) : null}
    </main>
  );
}
