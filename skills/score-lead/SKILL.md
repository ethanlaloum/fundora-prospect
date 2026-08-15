---
name: score-lead
description: Explique ou calcule le score d'un prospect issu d'une cession de fonds de commerce. A utiliser quand on demande pourquoi un lead a tel score, ce que vaudrait une cession decrite a la main, ou si une societe cedante est encore active — par exemple « combien vaudrait une cession de 400 k€ faite il y a deux mois ? » ou « pourquoi ce lead est-il devant l'autre ? ».
---

# Scorer et expliquer un lead

## Deux outils, deux usages

**`score_lead`** applique la grille a une cession decrite explicitement, sans
lancer de recherche. Pour « combien vaudrait une cession de 400 k€ faite il y
a deux mois ? ».

**`enrich_company`** verifie l'etat d'une societe par son SIREN. Pour « cette
societe est-elle encore active ? ».

Pour une recherche de prospects, utiliser plutot `search_liquidity_events` :
il score deja tout ce qu'il rend.

## Les quatre criteres

| Critere | Poids | Comportement |
|---|---|---|
| Montant | 55 | echelle **logarithmique** entre 10 000 et 1 580 000 € |
| Fraicheur | 45 | decroit **des le premier jour**, demi-vie 180 jours |
| Secteur | 0 | inactif — voir plus bas |
| Departement | 0 | inactif — perimetre homogene |

**Le montant est en echelle log**, pas lineaire : passer de 200 a 400 k€ change
la capacite d'investissement, passer de 5 a 6 M€ non.

**La fraicheur decroit des le premier jour**, sans palier, et se compte depuis
la **date de l'acte** quand elle est connue — pas depuis la publication. Une
cession de trois semaines et une de onze mois ne sont pas le meme prospect.

**Secteur et departement pesent zero, deliberement.** Rien ne permet de
hierarchiser les secteurs ni les departements sans donnee de conversion.
Inventer un ordre serait fabriquer un signal. Le code APE est quand meme
collecte et affiche, comme metadonnee.

## Expliquer un score

Le `breakdown` porte, pour chaque critere, ses points et le motif du calcul.
S'en servir litteralement : le projet garantit que la somme des contributions
egale le score. Ne jamais inventer de justification.

## Expliquer un refus

Un evenement peut ressortir **non classable**, avec un motif. Ce n'est pas un
score de zero, c'est une sortie du classement. Les motifs possibles :

- **societe cedante cessee** — le produit de cession est descendu aux
  associes, la personne morale n'est plus prospectable
- **entreprise non diffusible** — opposition INSEE explicite, non exploitee
- **apport en nature** — le cedant a recu des parts, pas du cash
- **devise obsolete** — montant en francs, donc transaction anterieure a 2002
- **acte trop ancien** — plus de 24 mois entre l'acte et la publication
- **montant aberrant** — hors des bornes de plausibilite

Restituer le motif tel quel. Il est concu pour etre auditable.

## Le cadrage a tenir

Ce n'est **pas un modele predictif**. Les poids sont des hypotheses
commerciales a dire d'expert : aucune donnee de conversion n'existe pour les
calibrer. Un score de 90 ne veut pas dire « 90 % de chances de convertir ». Il
veut dire que ce lead sort en tete de cette grille-la, dont les poids sont
lisibles dans `src/fundora_prospect/config/ponderation.toml`.
