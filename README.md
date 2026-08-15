
# fundora-prospect

**Aucun scraping.** Ce projet n'exploite que des publications légales
obligatoires, via deux APIs publiques documentées : le BODACC et
`recherche-entreprises.api.gouv.fr`. Tout autre domaine lève une exception, et
la restriction est appliquée au transport HTTP — pas dans une fonction qu'un
appel distrait pourrait contourner.

Sur cette base :

> **~898 cessions de fonds de commerce de plus de 200 000 € par an en
> Provence-Alpes-Côte d'Azur, avec un cédant personne morale identifié, son
> SIREN et l'URL de sa publication au BODACC.**

Chiffre **mesuré**, pas estimé. Reproductible :

```bash
.venv/bin/python -m pytest -m network -q -s
```

---

## Le raisonnement : du BODACC au prospect

Fundora permet d'investir en private equity dès 100 €, et cherche des
prospects capables d'engager un ticket d'au moins 10 000 €. La difficulté
commerciale n'est pas de trouver des gens riches : c'est de les trouver **au
moment où ils ont du cash à placer**.

Le BODACC publie les cessions de fonds de commerce **avec le prix de vente**.
C'est un signal de liquidité daté, nominatif et public.

**La chaîne :**

1. Une cession de fonds de commerce est publiée au BODACC, prix compris.
2. Le prix révèle une trésorerie fraîche, à une date connue.
3. Le cédant est, dans deux tiers des cas, **une société** — le produit de
   cession arrive sur son compte et y reste tant qu'elle n'est pas liquidée.
4. Une société qui vient d'encaisser plusieurs centaines de milliers d'euros,
   **toujours active**, et qui n'a pas encore arbitré est l'ICP de Fundora.
   Radiée, le cash est descendu aux associés : ce n'est plus un prospect.
5. L'annonce fournit nativement le SIREN du cédant et l'URL de publication :
   la traçabilité est un champ, pas une reconstruction.

### Le point contre-intuitif

**Les annonces sont rédigées côté acheteur.** Le champ `categorieVente` dit
« Achat d'un fonds par une personne morale », et le champ `commercant` nomme
l'acquéreur.

Le prospect — celui qui encaisse — est dans `listeprecedentproprietaire`.

Qui n'ouvre pas la donnée cible l'acheteur, c'est-à-dire exactement la personne
qui vient de *dépenser* son cash. La différence n'est pas cosmétique : elle
inverse la cible.

### Le prix n'est pas dans un champ

Il est en texte libre, dans `listeetablissements.etablissement.origineFonds` :

```
établissement principal acquis par achat au prix stipulé de 70000.00 euros
```

La forme est régulière, mais elle sert aussi à dire des choses très
différentes — un apport en nature, un montant en francs, une transaction
vieille de vingt ans. Ce parsing est le cœur technique du projet, et la
section [Limites connues](#limites-connues) explique pourquoi il ne peut pas
être fiable à 100 %.

### Un exemple complet

Annonce réelle, anonymisée :

```json
{
  "id": "A20260153319",
  "dateparution": "2026-08-13",
  "url_complete": "https://www.bodacc.fr/pages/annonces-commerciales-detail/?q.id=id:A20260153319",
  "acte": {
    "descriptif": "Acte en date du 25/07/2026 enregistre le 24/07/2026.",
    "vente": { "categorieVente": "Achat d'un fonds par une personne morale" }
  },
  "listeprecedentproprietaire": {
    "personne": {
      "denomination": "LE FOURNIL D ORNELLA",
      "typePersonne": "pm",
      "numeroImmatriculation": { "numeroIdentification": "852 872 563" }
    }
  },
  "listeetablissements": {
    "etablissement": {
      "origineFonds": "établissement principal acquis par achat au prix stipulé de 185000.00 euros"
    }
  }
}
```

Noter la structure : l'annonce est celle d'un **achat**, et le prospect est le
`listeprecedentproprietaire` — la boulangerie qui vient de vendre, pas
l'acquéreur.

Ce que le pipeline en tire, avec le détail du calcul :

```
LiquidityEvent  A20260153319
  cédant        LE FOURNIL D ORNELLA  (personne morale, SIREN 852872563)
  montant       185 000 EUR                    qualification : achat
  acte          2026-07-25   parution 2026-08-13   écart 19 jours
  statut        ACTIVE — société active, trésorerie de cession au bilan
  activité      APE 10.71C   section C
  provenance    https://www.bodacc.fr/...?q.id=id:A20260153319

Score 73,20 / 100
  montant       31,70 pts   185 000 EUR, échelle log entre 10 000 et 1 580 000 EUR
  fraîcheur     41,50 pts   21 jours depuis la date d'acte ; décroissance demi-vie
                            dès le premier jour, demi-vie 180 jours
  secteur        0,00 pts   code APE 10.71C hors liste prioritaire ; poids 0
  département    0,00 pts   département 13 ; poids 0 — périmètre PACA homogène
```

Le statut `ACTIVE` est ce qui autorise ce lead à être classé : une société
radiée sort du classement avec son motif, parce que son produit de cession est
déjà descendu aux associés.

Chaque point est justifié, y compris les critères qui ne rapportent rien. Aucun
score ne sort sans son détail, et `somme(contributions) == score` est vérifié
par un test.

### Ce que cet outil ne fait pas

**C'est un outil de qualification, pas un carnet d'adresses.** Il indique
*où se trouve la liquidité fraîche* et *à quel moment*. Il ne produit ni
coordonnées personnelles, ni liste d'appel.

L'activation commerciale passe par des canaux conformes, hors du périmètre de
cet outil : partenariats avec des conseillers en gestion de patrimoine,
ciblage par audience, approche B2B vers la personne morale. Confondre les deux
serait une faute — de conformité autant que de méthode.

---

## Les trois décisions structurantes

### 1. La cible est la société cédante, pas ses dirigeants

**Problème.** Deux tiers des cédants sont des personnes morales. On peut être
tenté de remonter à leurs dirigeants, nominatifs et contactables.

**Décision.** Le prospect est la **personne morale elle-même**.

**Pourquoi l'alternative est écartée.** Le produit de cession arrive sur le
compte de la société. Il ne descend vers les associés que si elle est ensuite
liquidée. Cibler les dirigeants suppose donc une distribution qui n'a pas eu
lieu — une inférence non soutenue par l'annonce, portant sur des personnes que
l'annonce ne nomme même pas.

**Ce que ça coûte.** Le recentrage écarte **14 %** du volume : de ~1 046
cessions > 200 k€ tous cédants confondus, à ~900 avec un cédant personne
morale. En échange : prospection B2B, intérêt légitime solide, aucune
inférence sur des personnes physiques.

> Les cédants personnes physiques (~135/an) sont conservés comme **segment
> secondaire**, explicitement marqué dans le modèle comme relevant d'une base
> légale distincte. Les deux segments ne sont jamais mélangés dans un export.

### 2. L'anonymisation des fixtures est une liste blanche

**Problème.** Les tests tournent sur des annonces réelles figées. Ces annonces
contiennent des noms et des adresses. Git conserve l'historique : un nom
commité une fois reste exposé le jour où le dépôt passe en public.

**Décision.** Un test parcourt les fixtures et **refuse tout ce qu'il ne
reconnaît pas** : gabarit ancré pour les champs à texte libre, vocabulaire
fermé pour les champs structurés, lexique mot à mot pour `origineFonds`. La
substitution est faite **à la capture**, en mémoire, avant toute écriture
disque. Un hook `pre-commit` versionné rejoue le test.

**Pourquoi l'alternative est écartée.** Une liste noire ne trouve que ce qu'on
a anticipé.

**Preuve.** La liste blanche a refusé
`listeetablissements.etablissement.enseigne`, un champ que je n'avais pas
identifié comme sensible. Une enseigne peut valoir « Chez Michel » ou
« Boulangerie Dupont ». Aucune recherche de noms connus ne l'aurait signalé.

### 3. Le scoring est une grille à dire d'expert, pas un modèle

**Problème.** Il faut classer les événements. La tentation est d'appeler ça un
modèle.

**Décision.** C'est une **grille de pondération à dire d'expert**, et le code
le dit : `GrillePonderation`, `evaluer`, `ContributionCritere`. Aucun `model`,
`predict` ou `train`. Les poids vivent dans `config/ponderation.toml`, chargé
au runtime — les recalibrer ne touche aucun `.py`.

**Pourquoi l'alternative est écartée.** Aucune donnée de conversion n'existe :
on ne sait pas quels leads se transforment. Présenter ces poids comme un modèle
laisserait croire à une validation empirique qui n'a pas eu lieu.

**Contrôle.** Une corrélation de rang mesure si le classement est autre chose
qu'un tri par prix déguisé. Elle est publiée, y compris quand elle est
mauvaise — voir [Limites connues](#limites-connues).

---

## Conformité

Fundora est une plateforme de private equity au statut de **conseiller en
investissements financiers (CIF), agréée par l'AMF**. Un acteur régulé ne peut
pas exploiter une base constituée illégalement : la conformité n'est donc pas
une case à cocher en fin de projet, c'est une contrainte d'architecture.

| Contrainte | Mise en œuvre | Vérifié par |
|---|---|---|
| Aucun scraping | Deux APIs publiques documentées, aucun HTML parsé | — |
| Domaines autorisés en dur | `TransportWhitelist` : lève **avant** d'ouvrir la connexion | `tests/test_http.py` |
| Traçabilité de chaque lead | `url_complete`, SIREN et date fournis nativement par l'annonce | `tests/test_bodacc.py` |
| Zéro donnée personnelle au dépôt | Liste blanche + substitution à la capture + hook `pre-commit` | `tests/test_anonymisation.py` |
| Base légale par segment | `type_personne` porté jusqu'au lead, jamais dans le score | `tests/test_bodacc.py` |
| Scoring explicable | `somme(contributions) == score`, motif obligatoire par critère | `tests/test_scoring.py` |
| Opposition INSEE respectée | `statut_diffusion ≠ O` ⇒ lead écarté avec motif | `tests/test_enrichment.py` |
| Pas de données hors périmètre | `dirigeants` supprimé à la capture, absent du modèle | `tests/test_enrichment.py` |

La whitelist est vérifiée au **transport HTTP** et non dans une fonction
utilitaire : à cet endroit, aucun chemin de code ne peut l'éviter — ni une
redirection 302 vers l'extérieur, ni un sous-domaine, ni une URL construite
dynamiquement.

Les entreprises non diffusibles au sens INSEE seront écartées à
l'enrichissement.

---

## Architecture

```
  BODACC (API Opendatasoft)
        │
        │   TransportWhitelist ─── domaine hors liste → exception
        │   TransportCache ─────── réponses hors dépôt (~/.cache)
        ▼
  bodacc.py        dépliage des sous-objets JSON-string
        │          extraction du cédant (listeprecedentproprietaire)
        │          → sans cédant : écarté (13 % du flux, mises en activité)
        ▼
  prix.py          « ce montant décrit-il la transaction annoncée ? »
        │          → apport (montant évalué)      : rejeté, règle métier
        │          → francs / FRF                 : rejeté, devise obsolète
        │          → acte de plus de 24 mois      : rejeté, qualité de donnée
        ▼
  enrichment.py    recherche-entreprises, par SIREN — DEUX signaux
        │          → societe cessee            : hors classement (porte)
        │          → non diffusible INSEE      : hors classement (porte)
        │          → API muette                : lead VALIDE, statut inconnu
        ▼
  models.py        LiquidityEvent — le fait, avec sa provenance
        │
        ▼
  scoring.py       grille de pondération ← config/ponderation.toml
        │          → non retenu ou aberrant : hors classement, avec motif
        ▼
  Lead + ScoreBreakdown
```

Le découpage qui compte : **`prix.py` tranche la qualité de la donnée,
`scoring.py` tranche la pertinence commerciale.** D'où deux seuils distincts —
24 mois dans le parser, décroissance continue dans la grille. Élargir la
fenêtre commerciale ne doit jamais obliger à modifier le parser.

---

## Limites connues

Cette section est la plus importante du document. Un pipeline de prospection
qui ne connaît pas ses angles morts en produit sans le savoir.

### Le champ `origineFonds` peut décrire une transaction antérieure

**599 annonces citent un montant en francs, et elles sont publiées de 2008 à
2026.** Le franc a cessé d'avoir cours en 2002 : une annonce publiée en 2026
avec un prix en francs décrit une transaction vieille de plus de vingt ans.

Pire, **le filtre cédant ne les attrape pas** : 94,5 % d'entre elles ont un
cédant renseigné, dont 43 % de personnes morales.

Conséquence directe : **des montants en euros sont périmés de la même façon, et
ils sont invisibles.** Un montant en francs se trahit par sa devise ; une
cession de 2015 republiée en 2026 en euros ne se trahit par rien.

**Atténuation partielle.** `acte.descriptif` porte parfois « Acte en date du
JJ/MM/AAAA », comparable à la date de parution. Au-delà de 24 mois d'écart, la
donnée est rejetée. Ordre de grandeur du bruit résiduel : 1 à 2 %.

### 60 % des actes ne sont pas datables

Le garde ci-dessus **ne couvre que 40 % du flux**. Pour les 60 % restants, il
n'existe aucun moyen de dater la transaction.

Le repli est la date de parution, et l'incertitude est portée dans le champ
`confiance` : le breakdown dit toujours laquelle des deux dates a servi. Comme
l'écart médian acte → parution est de 33 jours mais que le p95 atteint
145 jours, ce repli **surestime systématiquement la fraîcheur**.

### Deux formulations de prix échappent au parser

Le parser reconnaît `prix stipulé de X` (achat) et `montant évalué à X`
(apport). Deux autres formulations existent, **sans mention de devise** :

```
Etablissement principal acquis par achat pour un montant de 85 000.
Achat pour le prix de 280 000.
```

Fréquence mesurée : **2 sur 1 041 `origineFonds` non vides, soit 0,19 %.**
Elles ne sont pas parsées, et le montant est donc perdu.

Ces formes n'ont pas été ajoutées : sans marqueur de devise, le motif
attraperait des nombres qui ne sont pas des prix, et le gain plafonne à 0,2 %.
La limite est ici plutôt que dans un `TODO` — c'est le test d'anonymisation par
liste blanche qui l'a révélée, en refusant un mot inconnu dans une fixture.

### La grille n'est pas calibrée

Les poids — 55 pour le montant, 35 pour la fraîcheur, 10 pour le secteur, 0
pour le département — sont des **hypothèses commerciales**. Aucune donnée de
conversion n'existe pour les valider.

Ils sont recalibrables sans toucher au code, et `config/ponderation.toml` porte
la date de calibration et le motif de chaque pondération. Mais recalibrable
n'est pas calibré.

### Le montant domine le classement

Corrélation de rang entre le score complet et un tri par montant seul, mesurée
sur 505 événements classables :

| Forme du critère de fraîcheur | Corrélation |
|---|---|
| Plateau 0–18 mois *(version initiale)* | **0,998** |
| Décroissance dès le premier jour, demi-vie 180 jours | **0,790** |
| Idem, après report du poids orphelin du secteur (35 → 45) | **0,710** |

La première version accordait une contribution pleine jusqu'à 18 mois. C'était
une *fenêtre de pertinence commerciale* là où il fallait un *critère de
discrimination* : sur une recherche portant sur 12 mois, toute la population
tombait dans le plateau et la fraîcheur ne départageait rien. Le score n'était
alors qu'une fonction monotone du montant.

La correction — décroissance dès le premier jour — fait tomber la corrélation
à 0,790, et **19,2 % des paires sont désormais classées différemment d'un tri
par montant**. La valeur descend ensuite à 0,710, mécaniquement : les 10 points
du critère secteur, laissé orphelin faute de base défendable, ont été reportés
sur la fraîcheur. **Ce n'est pas une amélioration du classement** — un poids
sans emploi a été redistribué, rien n'a été calibré. Un test le vérifie directement : une cession de 250 k€ vieille
de deux semaines passe devant une cession de 600 k€ vieille de vingt-deux mois.

La leçon vaut au-delà de ce projet : **un critère peut être correctement
pondéré et rester totalement inerte si sa forme ne discrimine pas sur la
population réelle.** La pondération n'était jamais en cause.

0,790 reste élevé, et c'est attendu : sur une population déjà filtrée à plus de
200 k€, le montant domine et les autres critères départagent à montant
comparable. Le seuil d'alerte de la configuration déclenche un avertissement,
pas un échec — on ne retouche pas des poids pour faire passer un test.

### Le critère secteur reste à poids nul — pour une autre raison qu'avant

Le code APE est désormais disponible : l'enrichissement le récupère, il est
stocké et affiché. Le critère n'est plus bloqué techniquement.

**Il reste à poids nul parce qu'aucune base ne permet de hiérarchiser les
secteurs.** Il n'existe pas de donnée de conversion. Affirmer que la
restauration convertit mieux que le BTP serait inventer un signal — exactement
ce qui a été refusé pour le département, et l'accepter ici serait incohérent.

La distribution mesurée montre que l'enjeu est de toute façon faible. Sur 105
cédants personnes morales enrichis :

| Section APE | Part |
|---|---|
| I — Hébergement et restauration | 52,4 % |
| G — Commerce | 21,0 % |
| C — Industrie manufacturière | 10,5 % |
| L — Activités immobilières | 8,6 % |
| autres (F, S, J, M, N, R) | 7,5 % |

Deux sections font 73 % du flux. Une pondération sectorielle reviendrait pour
l'essentiel à trancher « restauration contre le reste », sans rien pour
l'étayer.

**Une hypothèse de départ s'est révélée fausse**, et c'est ce à quoi sert une
mesure : je supposais qu'il faudrait écarter les cédants de la **section K
(activités financières)**, véhicules déjà accompagnés et hors ICP. Mesure :
**K représente 0 % du flux.** Les 8,6 % que je pensais y trouver sont en
section L (immobilier), pour laquelle l'argument « professionnel de la
finance » ne tient pas. La règle n'a pas été implémentée.

Si une hiérarchie sectorielle devait exister un jour, elle porterait sur la
**section** — 21 valeurs, seul niveau qu'un humain puisse défendre, et le seul
stable à travers la révision de nomenclature ci-dessous.

### Une transition de nomenclature NAF est en cours

L'API sert deux codes d'activité pour la même entreprise :

```
activite_principale        = "10.71C"   NAF rév. 2
activite_principale_naf25  = "10.71H"   NAF 2025
```

Les deux sont conservés côte à côte plutôt que d'en choisir un. Aucune
pondération ne repose sur un code d'activité, donc rien ne casse aujourd'hui —
mais toute liste de codes écrite en dur sur NAF rév. 2 se périmerait. Les
sections (lettres A–U) survivent à la révision, pas les sous-classes.

### Un quart des enrichissements n'aboutit pas

Sur 142 cédants personnes morales disposant d'un SIREN, **26,1 % ressortent
avec un statut inconnu** : l'API ne trouve pas l'entreprise, ou rend une
entreprise dont le SIREN ne correspond pas à celui demandé — un contrôle
explicite rejette ce second cas plutôt que d'enrichir un lead avec le statut
d'une société sans rapport.

Ces leads restent valides et classables, avec le motif dans le breakdown. Mais
pour un quart du flux, la question « la société est-elle encore active ? » reste
sans réponse. À l'autre bout, **4,2 % des cédants sont déjà radiés** et sortent
du classement : peu de volume, mais ce sont exactement les bons à retirer.

---

## Reproduire les chiffres

```bash
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
git config core.hooksPath .githooks     # active le garde-fou RGPD
```

| Commande | Ce qu'elle produit |
|---|---|
| `.venv/bin/python -m pytest -q` | 302 tests unitaires, sur fixtures figées, sans réseau |
| `.venv/bin/python -m pytest -m network -q -s` | volume annuel, taux de parsing par segment, corrélation de rang |
| `.venv/bin/python explore/dump_bodacc.py` | structure de la donnée, taux de présence du prix |
| `.venv/bin/python explore/probe_origine_fonds.py` | les montants en francs, les annonces multi-établissements |
| `.venv/bin/python tools/record_fixtures.py` | recapture les fixtures, anonymisées à l'écriture |

Chaque chiffre de ce README sort d'une de ces commandes.

**Note sur la reproductibilité** : les mesures réseau tirent un échantillon
frais à chaque exécution. Les valeurs varient de quelques unités d'un run à
l'autre — ~895 à ~898 pour le volume annuel. Les ordres de grandeur sont
stables, les décimales ne le sont pas.

---

## Suite prévue

Exposition en serveur MCP, puis packaging en plugin Claude Code avec un hook
`PreToolUse` bloquant les appels hors whitelist — un second verrou, au niveau
de l'agent, complémentaire de celui posé au transport HTTP.

Rien de tout cela n'existe à ce jour. Ce README ne décrit que ce qui tourne.
