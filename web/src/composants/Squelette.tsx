/**
 * La place que les resultats vont prendre, en attendant qu'ils arrivent.
 *
 * ## Pourquoi pas un tourniquet
 *
 * Un tourniquet dit « ca tourne ». Un squelette dit « voila ce qui vient, et ou
 * ca se posera » : l'ecran ne saute pas au moment de la reponse, ce qui compte
 * sur une liste dense ou le lecteur a deja commence a viser une colonne.
 *
 * ## Il ne porte AUCUN texte, et ce n'est pas une economie
 *
 * Un squelette qui afficherait un libelle, un zero ou un tiret ferait lire un
 * resultat la ou il n'y en a pas encore — le defaut que ce projet traque
 * partout ailleurs, glisse dans un etat transitoire. Des blocs gris, et rien.
 * `aria-hidden` pour la meme raison : il n'y a rien a annoncer.
 *
 * ## Le nombre de blocs est ecrit, pas calcule
 *
 * Il ne represente aucune population : c'est un remplissage d'ecran, pas un
 * compte. Le deduire d'une limite de recherche lui donnerait l'air d'annoncer
 * combien de leads vont venir, ce que personne ne sait a ce moment-la.
 */

export function Squelette() {
  return (
    <div aria-hidden="true" className="squelette">
      <div className="squelette-bloc squelette-bloc--resume" />
      <div className="squelette-bloc" />
      <div className="squelette-bloc" />
      <div className="squelette-bloc" />
      <div className="squelette-bloc" />
    </div>
  );
}
