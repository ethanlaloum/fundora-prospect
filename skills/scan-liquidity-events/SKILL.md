---
name: scan-liquidity-events
description: Trouve des prospects investisseurs en cherchant les cessions de fonds de commerce publiees au BODACC. A utiliser quand on demande des cessions, des cedants, des prospects, des evenements de liquidite, ou « qui vient de vendre son fonds » sur un departement ou une region — par exemple « trouve-moi les cessions de plus de 300 k€ dans le 06 sur 6 mois ».
---

# Chercher des evenements de liquidite

## Ce que fait cette competence

Le BODACC publie les cessions de fonds de commerce **avec le prix de vente**.
Un cedant recent dispose de tresorerie fraiche : c'est le signal exploite ici.

Appeler l'outil MCP **`search_liquidity_events`**. Il execute tout le pipeline
et rend des leads **deja scores et tries**. Un seul appel suffit : ne pas
enchainer `enrich_company` ou `score_lead` sur chaque resultat.

## Traduire la demande

| Ce que dit l'utilisateur | Parametre |
|---|---|
| « dans le 06 », « Alpes-Maritimes » | `departement="06"` — toujours **deux chiffres entre guillemets** |
| « en PACA », « dans la region » | `departement="PACA"` |
| « dans le 06 et le 13 » | `departement="06,13"` |
| « sur 6 mois », « depuis 6 mois » | `mois=6` |
| « plus de 300 k€ », « au-dessus de 300 000 » | `montant_min=300000` |
| « les 10 meilleurs » | `limite=10` |

Sans precision : `mois=12`, `montant_min=0`, `limite=25`.

## Presenter le resultat

**Toujours donner le resume avant la liste.** Il contient le decompte des
annonces ecartees avec leur motif — c'est ce qui rend le resultat auditable :

> 668 annonces publiees, 600 rapatriees seulement (plafond de rapatriement
> atteint), 140 sans cedant ou illisibles, 460 exploitables, 49 classables
> parmi les 50 enrichis, 334 sous le montant minimum, 6 apport, 2 absent,
> 2 acte trop ancien, 1 societe cedante cessee. 25 rendus sur 49 classables
> parmi les 50 enrichis (limite atteinte) ; 66 candidats non enrichis donc
> non classes, faute de budget d'appels : relancer avec une limite plus
> haute pour les voir.

**Ne pas raccourcir ce resume en le recopiant.** Chaque nombre porte sa
condition d'obtention, et trois populations y sont distinctes :

- **ecarte** — juge, avec un motif. C'est le seul vrai refus.
- **tronque** — classable, mais hors des N premiers.
- **non enrichi** — jamais examine, faute de budget d'appels.

« 49 classables » sans « parmi les 50 enrichis » se lit comme une propriete du
departement, alors que c'est une propriete de l'appel : le nombre de dossiers
examines vaut `2 x limite`. Le dire entier, ou ne pas le dire.

Puis les leads, du meilleur au moins bon. Pour chacun : le score, la
denomination du cedant, son SIREN, le montant, la date de l'acte, et l'URL de
publication au BODACC.

Si l'utilisateur demande **pourquoi** un lead a tel score, le detail est dans
`breakdown` : chaque critere y porte ses points et le motif du calcul.

## Trois choses a ne pas dire

**Le prospect est la societe cedante, pas l'acheteur.** Les annonces BODACC
sont redigees du point de vue de l'acquereur ; l'outil rend bien le cedant.
Ne jamais presenter l'acheteur comme le prospect.

**Ce n'est pas une liste d'appel.** L'outil qualifie *ou* se trouve la
liquidite fraiche et *a quel moment*. Il ne produit ni coordonnees, ni contact
nominatif. Si on demande des emails ou des telephones, expliquer que ce n'est
pas le perimetre et que l'activation passe par des canaux conformes.

**Le score n'est pas une prediction.** C'est une grille de ponderation a dire
d'expert, sans donnee de conversion pour la calibrer. Ne pas parler de
probabilite de conversion.

## Si le resultat est vide

Regarder le resume avant de conclure a une panne. Le plus souvent, le
`montant_min` est trop haut ou la periode trop courte. Le decompte des
ecartes le dit.
