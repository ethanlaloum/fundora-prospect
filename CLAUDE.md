# fundora-prospect

Plugin Claude Code de détection et qualification de prospects investisseurs,
construit exclusivement sur des données publiques légales.

Projet vitrine pour un entretien d'alternance développeur chez Fundora
(plateforme française de private equity, statut CIF, agrément AMF).

## Contexte métier

Fundora permet aux particuliers d'investir en private equity dès 100 €.
L'objectif commercial est d'identifier des prospects capables d'engager un
ticket d'au moins 10 000 €.

Signal exploité : le BODACC publie les **cessions de fonds de commerce avec le
prix de vente**. Un cédant récent dispose de liquidités fraîches, d'un horizon
de réinvestissement et d'un profil entrepreneur — l'ICP exact de Fundora.

Signaux secondaires : dissolutions avec boni de liquidation, radiations
post-cession.

## Cible — décidé au gate Phase 0

**Le prospect principal est la SOCIÉTÉ CÉDANTE, pas ses dirigeants.**

Le produit de cession arrive sur le compte de la personne morale qui a vendu
le fonds. Il n'y descend vers les associés que si la société est ensuite
liquidée. Remonter aux dirigeants pour les démarcher repose donc sur une
inférence trop faible — et sur des personnes que l'annonce ne nomme pas.

Conséquences :

- **Segment principal : cédant personne morale toujours active.** Prospection
  B2B, intérêt légitime solide, **~898 cas/an en PACA** (mesuré Phase 1).
  Société active = trésorerie encore au bilan, à placer.
  *Ne pas confondre avec les ~1 046/an, qui comptent **tous** les cédants —
  voir l'attribution du volume plus bas.*
- **Segment secondaire : cédant personne physique.** ~135 cas/an en PACA.
  Conservé, mais **explicitement marqué dans le modèle comme relevant d'une
  base légale distincte** (prospection de personne physique ≠ B2B). Ne pas
  mélanger les deux segments dans un même export sans le champ qui les
  distingue.
- **Annonces sans cédant précédent : exclues.** Les 13 % d'annonces sans
  `listeprecedentproprietaire` sont des mises en activité, pas des cessions.
  Aucun cédant, donc aucun prospect. Filtre dur dès le client BODACC.

## Ce que l'exploration Phase 0 a établi

Chiffres mesurés sur un échantillon de 1 200 annonces réparti sur 12 mois
glissants en PACA (`familleavis="vente"`, 4 498 annonces au total).

**Les annonces sont rédigées côté acheteur.** `acte.vente.categorieVente`
vaut « Achat d'un fonds par… », « Mise en activité suite à achat ». Le cédant
— notre prospect — est dans `listeprecedentproprietaire.personne`, avec son
`typePersonne` (`pm`/`pp`), sa `denomination` et son SIREN sous
`numeroImmatriculation.numeroIdentification`.

**Le prix n'est pas dans un champ dédié.** Il est en clair dans
`listeetablissements.etablissement.origineFonds`, sous une forme très
régulière :

> `établissement principal acquis par achat au prix stipulé de 70000.00 euros`

Un motif naïf `prix stipulé de X euros` extrait déjà 86 % des montants
(1 032/1 200). Les sous-objets `acte`, `listeetablissements`, `listepersonnes`,
`listeprecedentproprietaire` sont des **JSON encodés en string** : il faut les
déplier avant tout parsing.

Distribution des prix : médiane 110 k€, p90 450 k€, max 6,2 M€.
23,2 % dépassent 200 k€.

Croisement prix × type de cédant :

| Cédant | Annonces | Prix extrait | > 200 k€ | Extrapolé /an PACA |
|---|---|---|---|---|
| Personne morale | 805 (67 %) | 803 | 240 | **~900** |
| Personne physique | 236 (20 %) | 223 | 36 | ~135 |
| Absent | 159 (13 %) | 6 | 3 | exclu |
| **Tous cédants** | 1 200 | 1 032 | **279** | **~1 046** |

### Attribution du volume — à ne pas se tromper

Le chiffre de **~1 046/an** compte **tous les cédants confondus**. Les cédants
personne morale en representent 86 % (240/279), soit **~900/an avant toute
exclusion de qualite**.

Le volume final mesure en Phase 1 est de **~895/an**. La difference se
decompose ainsi :

| Etape | Volume | Écart | Cause |
|---|---|---|---|
| Tous cédants > 200 k€ | ~1 046 | — | — |
| Recentrage sur les personnes morales | ~900 | **−14 %** | **décision de cible** |
| Exclusion apports, devises obsolètes, actes anciens | ~898 | −0,5 % | qualité de donnée |

**L'essentiel de la baisse vient du recentrage sur la cible, pas des filtres
de qualité** — ceux-ci retirent environ 5 leads. Formuler l'inverse
attribuerait au parser un effet qui appartient a l'arbitrage commercial.

**Deux chiffres à ne jamais confondre** :

- **86 %** est la *part* des personnes morales parmi les cessions > 200 k€
  (240/279). C'est ce qu'on **garde**.
- **14 %** est ce que le recentrage **écarte** (~1 046 → ~900).

Écrire « le recentrage écarte 86 % » inverse les deux. L'erreur est apparue
deux fois dans ce projet ; elle vient de ce que 86 % est le chiffre le plus
frappant, donc celui qu'on retient sans son référent.

Formulation correcte pour le README : « ~898 cessions de plus de 200 k€ par an
en PACA avec un cédant personne morale, sur ~1 046 cessions de plus de 200 k€
tous cédants confondus. »

`url_complete` fournit l'URL de publication par annonce : la contrainte de
traçabilité est satisfiable nativement, sans reconstruction d'URL.

### Les trois pièges de `origineFonds`

Mesurés par `explore/probe_origine_fonds.py`. Ce sont les constats qui
structurent le parser.

**1. Le champ peut décrire une transaction ANTÉRIEURE à la publication.**

599 annonces nationales citent un montant en francs, réparties de 2008 à
**2026**. Le franc a cessé d'avoir cours en 2002 : une annonce publiée en 2026
qui affiche un prix en francs décrit une transaction vieille de plus de 24 ans.
Et 94,5 % de ces annonces ont un cédant renseigné — **le filtre cédant ne les
attrape pas**, 43 % sont même des cédants personne morale.

Conséquence : des montants en euros sont périmés de la même façon, et **ils
sont invisibles**. Un montant en francs se trahit par sa devise ; une cession
de 2015 republiée en 2026 en euros ne se trahit par rien.

Seul garde disponible : `acte.descriptif` contient parfois « Acte en date du
JJ/MM/AAAA », comparable à `dateparution`. Couverture **40,2 % seulement**.
Écart mesuré sur la cible : médiane 33 j, p75 50 j, p95 145 j, max 1 184 j.
1,45 % dépassent 1 an, 0,96 % dépassent 2 ans — la masse est au-delà de
2 ans, ce qui signale deux populations distinctes. La cassure est là, d'où le
seuil de 24 mois.

**2. Achat et apport se distinguent lexicalement.**

- achat au comptant → `acquis par achat au prix stipulé de X`
- apport en nature → `acquis par apport au montant évalué à X`

« prix stipulé » contre « montant évalué ». Le discriminant est fiable, pas
heuristique. Voir la règle métier associée en Contrainte 6.

**Aucun code d'activité normalisé dans BODACC.** Inventaire des 32 champs de
premier niveau et de toutes les clés imbriquées : pas de NAF, pas d'APE.
`region_code` est un code région INSEE, `codeRCS` vaut littéralement « RCS ».
Zéro des 271 valeurs d'`activite` contient un motif NAF.

`listeetablissements.etablissement.activite` est de la prose libre : **264
valeurs distinctes sur 271**, jusqu'à 908 caractères. Un lexique de validation
sur un champ pareil serait une liste ouverte, donc une liste noire déguisée —
exactement ce que la contrainte 4 interdit. Le champ est donc **substitué dans
les fixtures**, et le critère secteur du scoring sera keyé sur le **code APE
obtenu via `recherche-entreprises.api.gouv.fr` en Phase 3**, nomenclature
fermée et validable.

**3. Les annonces multi-établissements sont négligeables : 0,1 %.**

1 annonce sur 1 200. En dessous du seuil de décision de 5 % : on **marque
l'annonce ambiguë et on passe**, sans implémenter la somme conditionnelle.

La règle reste écrite ici si le volume changeait : un seul cédant et tous les
établissements valorisés → somme ; plusieurs cédants sans mapping
établissement → cédant → ambigu ; valorisation partielle → somme marquée
partielle. Détail par établissement conservé dans le breakdown dans tous les
cas.

Aucune annonce ne contient plusieurs `prix stipulé` pour un même
établissement. À vérifier en Phase 1 : 12,7 % des annonces ont zéro
établissement, ce qui recoupe largement mais pas exactement les 13 % sans
cédant — les deux filtres ne sont peut-être pas redondants.

## Contraintes non négociables

Ces règles sont le cœur du projet, pas des détails. Un CIF régulé ne peut pas
exploiter une base constituée illégalement.

1. **Aucun scraping.** Uniquement des APIs publiques documentées.
2. **Domaines autorisés, en dur dans le code :**
   - `bodacc-datadila.opendatasoft.com`
   - `recherche-entreprises.api.gouv.fr`
   Tout autre domaine doit lever une exception.
3. **Traçabilité obligatoire.** Chaque lead porte `source`, `base_legale`,
   `date_collecte`, `url_publication`. Un lead sans provenance complète ne doit
   pas pouvoir être sérialisé.
4. **Zéro donnée personnelle réelle dans le repo.** Les fixtures de test sont
   anonymisées (noms de personnes et adresses remplacés par des valeurs
   factices) avant tout commit. Les raisons sociales et SIREN peuvent rester.

   **L'anonymisation ne se limite pas à `listepersonnes`.** Mesuré en Phase 0
   sur 100 annonces réelles, les noms de personnes fuient par quatre champs,
   dont trois sont hors `listepersonnes` :

   | Champ | Nature | Occurrences avec nom |
   |---|---|---|
   | `acte.descriptif` | texte libre | 25/99 |
   | `acte.vente.opposition` | texte libre — **nom + adresse complète** | 22/99 |
   | `commercant` | semi-structuré | 20/100 |
   | `listepersonnes.personne.administration` | texte libre — dirigeants | 24/25 |

   S'y ajoutent les champs structurés : `*.personne.nom`, `prenom`, `nomUsage`,
   et toutes les branches `adresse*` / `adresseSiegeSocial`.

   L'anonymisation doit donc traiter le texte libre, pas seulement des chemins
   de champs.

   **Elle est vérifiée par une LISTE BLANCHE, pas une liste noire.** Un test
   qui cherche des noms connus laisse passer tous ceux qu'on n'a pas anticipés.
   Les champs à texte libre des fixtures doivent matcher **exactement** un
   gabarit synthétique connu ; tout contenu non reconnu fait échouer le test.
   Ça impose au recorder de *remplacer intégralement* le texte libre plutôt que
   d'y masquer des morceaux : on reconstruit la phrase, on ne la nettoie pas.

   **La substitution se fait À LA CAPTURE.** Le recorder substitue en mémoire
   avant d'écrire sur disque. Aucune donnée personnelle réelle ne doit jamais
   exister dans le répertoire de travail — le `.gitignore` protège du commit,
   pas d'une archive du dossier ni d'un partage d'écran. Les dumps
   d'exploration vont dans `~/.cache/fundora-prospect/`, hors du dépôt.

   **Un hook `.githooks/pre-commit` versionné lance ce test.** Activé par
   `git config core.hooksPath .githooks`. `.git/hooks/` ne serait pas versionné
   et disparaîtrait au premier clone. Le hook reste contournable par
   `--no-verify` : c'est un filet, la garantie est le test dans `pytest`.
   Git conserve l'historique — un nom commité une fois est exposé le jour où le
   dépôt passe en public.
5. **Scoring explicable.** Chaque score sort avec le détail de son calcul.
   Pas de boîte noire.
6. **Un apport en nature n'est pas une cession.** Règle métier, pas commodité
   de parsing : dans un apport, le cédant reçoit **des parts sociales, pas du
   cash**. Il n'a aucune liquidité à placer et n'est donc pas un prospect
   Fundora, quel que soit le montant affiché. Les apports sont rejetés avec un
   motif explicite, jamais scorés à zéro — un zéro se noierait dans le flux,
   un rejet motivé est auditable.

## Stack

- Python 3.11+, `httpx`, `pydantic`, `pytest`, `ruff`
- Serveur MCP en stdio (SDK `mcp`)
- Pas de base de données : sortie JSON sur disque

## Méthode de travail

**Tu travailles phase par phase. Tu ne passes JAMAIS à la phase suivante sans
mon accord explicite.**

À chaque phase :
1. Tu annonces ce que tu vas faire et tu attends mon OK si c'est ambigu.
2. Tu écris les tests AVANT l'implémentation.
3. Tu implémentes.
4. Tu lances `pytest` et `ruff check` et tu me montres la sortie réelle.
5. Tu commits avec un message clair.
6. Tu t'arrêtes et tu me demandes si on continue.

Règles de test :
- Les tests unitaires tournent sur des **fixtures JSON figées** dans
  `tests/fixtures/`, capturées depuis les vraies APIs puis anonymisées.
  Pas de mocks inventés à la main : les fixtures viennent du réel.
- Les tests réseau sont marqués `@pytest.mark.network` et exclus par défaut.
- Si un test échoue, tu corriges le code, pas le test — sauf si le test est
  faux, et alors tu me l'expliques d'abord.

Ne crée pas de fichier dont on n'a pas besoin dans la phase courante.

## Plan des phases

### Phase 0 — Socle + exploration API (J1 matin)
Repo, venv, `pyproject.toml`, pytest, ruff, `.gitignore`.
Script jetable `explore/dump_bodacc.py` qui récupère 5 annonces réelles de type
vente/cession et affiche la structure complète des champs.
**Objectif : comprendre la donnée avant d'écrire quoi que ce soit.**
Gate : je valide la structure des champs avec toi.

### Phase 1 — Client BODACC (J1 après-midi)
`src/fundora_prospect/bodacc.py` : recherche d'annonces filtrée par type, date
et département, avec whitelist de domaines appliquée **au transport HTTP** —
un `httpx.BaseTransport` custom qui lève avant d'ouvrir la connexion, pas un
`if` dans un helper qu'un futur appel pourrait contourner. Plus cache disque.

Le vrai travail est le **parsing du prix de cession**, en texte semi-structuré
dans `listeetablissements.etablissement.origineFonds`.

Le parser répond à une seule question : **« ce montant décrit-il bien la
transaction annoncée ? »** C'est de la qualité de donnée. Trois gardes, par
ordre de fiabilité :

| Garde | Discriminant | Couverture |
|---|---|---|
| Devise | `francs`, `FRF`, `FRANCS FRANCAIS` → rejet | totale |
| Nature | `montant évalué` → apport, rejet (contrainte 6) | totale |
| Fraîcheur de l'acte | écart acte → parution **> 24 mois** → rejet | 40 % |

Le seuil de 24 mois est un seuil de **qualité de donnée, pas de pertinence
commerciale**. Un acte de 20 mois est une donnée valide mais vieille : c'est au
scoring de la déclasser, pas au parser de la supprimer. Sinon, élargir la
fenêtre métier obligerait à modifier `prix.py`.

Sortie : `PrixCession(montant, devise, methode, texte_source, qualification,
confiance)`. `confiance` porte l'écart acte → parution, ou le fait qu'il soit
indatable.

Extraction du cédant depuis `listeprecedentproprietaire` (tantôt objet, tantôt
liste — indivision, 1,6 %), avec son `typePersonne` et son SIREN normalisé
(l'API le rend espacé : `325 662 559`). Exclusion des annonces sans cédant.

Gate : tests unitaires sur fixtures + 1 test réseau. Taux de parsing mesuré et
affiché **par segment**, et taux de rejet ventilé par motif. Référence à battre
sur le sous-ensemble cédant personne morale : **99,8 %**.

### Phase 2 — Modèle et grille de pondération (J2 matin)

**Ce n'est pas un modèle. C'est une grille de pondération à dire d'expert.**
Aucune donnée de conversion n'existe pour la calibrer : les poids sont des
hypothèses commerciales, pas des coefficients appris. Le vocabulaire du code et
de la documentation doit le dire — `GrillePonderation`, jamais `model`,
`predict` ou `training`. Une grille présentée comme un modèle laisse croire à
une validation empirique qui n'a pas eu lieu, et c'est indéfendable devant un
CIF.

Les poids vivent dans un **fichier de configuration séparé**, rechargeable sans
toucher au code : ils seront recalibrés dès qu'un retour commercial existera,
et ça ne doit pas être une modification de `scoring.py`.

**Le montant est normalisé en échelle LOGARITHMIQUE.** Le critère serait sinon
linéaire sur une distribution qui ne l'est pas — médiane 110 k€, max 6,2 M€.
Le log préserve l'ordre, empêche le haut de la distribution d'écraser le reste,
et rend de nouveau lisible l'écart entre 200 et 400 k€, là où vit le volume.
C'est aussi le sens métier : passer de 200 à 400 k€ change la capacité
d'investissement, passer de 5 à 6 M€ non.

**Le plafond n'est pas une saturation métier.** Il est placé très haut (p99) et
sert uniquement à **borner une valeur aberrante mal parsée**. Un plafond bas
rendrait 6,2 M€ et 1 M€ équivalents alors que le premier est un meilleur
prospect : ce serait détruire de l'information, pas corriger une échelle.

**Les montants aberrants ne sont pas ramenés au plafond.** Une donnée dont on
ignore si elle est juste ne doit pas atterrir en tête du classement. Même
traitement que les événements non retenus : hors classement, avec motif.

**Test de corrélation de rang.** Sur une population déjà filtrée à plus de
200 k€, le montant peut dominer. Un test mesure la corrélation de Spearman
entre le classement de la grille complète et le classement par montant seul,
**sur les seuls événements retenus** — inclure les refus polluerait les rangs.

Si la corrélation reste élevée après le passage en log, **on ne retouche pas
les poids pour faire passer un seuil**. On documente le résultat tel quel : sur
une population filtrée à plus de 200 k€, le montant domine et les autres
critères départagent à montant comparable. C'est une conclusion valide, pas un
échec. Le test mesure et affiche ; ce qu'il garantit, c'est que les autres
critères **discriminent réellement à montant égal** — s'ils ne le font pas, ils
sont du code mort et le test échoue.

#### Résultat : 0,998 → 0,790 après correction de la fraîcheur

| Forme de la fraîcheur | Corrélation score / montant |
|---|---|
| Plateau 0–18 mois *(version initiale)* | **0,9980** |
| Décroissance dès J1, demi-vie 180 j | **0,7895** |
| | **Δ = −0,2085** |

Mesuré sur 505 événements classables, PACA, 12 mois. **19,2 % des paires sont
désormais classées différemment d'un tri par montant seul** — la grille produit
un classement propre, plus une réécriture du prix.

La correction : **la fraîcheur décroît dès le premier jour, sans plateau.**
La version initiale accordait une contribution pleine jusqu'à 18 mois — c'était
une *fenêtre de pertinence commerciale* là où il fallait un *critère de
discrimination*. Sur une recherche portant sur 12 mois, toute la population
tombait dans le plateau.

Raison métier : une cession de trois semaines et une de onze mois ne sont pas
le même prospect. Dans le premier cas le produit est encore en trésorerie et la
décision de placement n'est pas prise ; dans le second l'argent a déjà trouvé
une destination. **Le délai est le critère le plus décisif du métier.**

La forme de la décroissance est en configuration (`demi_vie` ou `lineaire`),
pas en dur. La demi-vie modélise mieux le phénomène : la probabilité que le
cash soit encore disponible décroît continûment, sans date de bascule.

#### Analyse de la version initiale, conservée pour mémoire

Mesuré sur 518 annonces PACA réparties sur 12 mois, événements retenus
uniquement. Le classement de la grille est, à ce stade, **un tri par montant**.

La cause n'est pas la pondération, c'est la **forme du critère de fraîcheur**.
La spécification dit « fenêtre 0–18 mois, décroissance au-delà » : sur cette
fenêtre, la fraîcheur vaut 1,0 pour tout le monde. C'est un plateau. Deux
cessions de même montant à 3 et à 15 mois obtiennent exactement le même score.
Or une recherche porte normalement sur les 12 derniers mois — donc **toute la
population tombe dans le plateau**.

Les trois autres critères sont alors inertes simultanément :

| Critère | État | Cause |
|---|---|---|
| Fraîcheur | plateau à 1,0 | fenêtre pleine ≥ fenêtre de recherche |
| Secteur | neutre | pas de code APE avant la Phase 3 |
| Département | poids 0 | choix délibéré, périmètre PACA homogène |

Le score est donc une fonction monotone du seul montant, et 0,998 est le
résultat attendu, pas une anomalie. Les 0,002 manquants viennent des quelques
actes assez anciens pour sortir du plateau.

**Corrigé** — voir ci-dessus. La leçon à retenir : un critère peut être
correctement pondéré et rester inerte si sa *forme* ne discrimine pas sur la
population réelle. La pondération n'était pas en cause, la forme l'était.

`models.py` : `LiquidityEvent`, `Lead`, `ScoreBreakdown` (pydantic).
`scoring.py` : fonction pure et déterministe. Critères :
- montant de cession (pondération forte, plafonnée)
- fraîcheur : fenêtre 0–18 mois, décroissance au-delà
- secteur d'activité — **keyé sur le code APE, indisponible avant la Phase 3**.
  Le critère existe dans la grille dès la Phase 2 mais rend une contribution
  neutre, avec le motif « APE non disponible » affiché dans le breakdown. Un
  critère silencieusement absent est un trou dans l'explicabilité.
- département

**La fraîcheur se calcule depuis la date de l'ACTE, pas depuis la parution.**
L'écart médian est de 33 jours mais p95 = 145 jours, soit près de 5 mois
consommés sur une fenêtre de 18 : compter depuis la parution surestimerait
systématiquement la fraîcheur. Repli sur `dateparution` quand l'acte n'est pas
datable (60 % des cas), avec l'écart porté par le champ `confiance` du
`PrixCession` pour que le breakdown dise laquelle des deux dates a servi.

Rappel du découpage : le parser tranche la validité de la donnée (seuil dur à
24 mois), le scoring tranche la pertinence commerciale (fenêtre 18 mois,
décroissance). Ne pas mélanger les deux.
Sortie : score 0–100 + détail par critère.
Gate : tests paramétrés sur les cas limites (prix nul, date future, secteur
inconnu, montant extrême).

### Phase 3 — Enrichissement ✅ FAIT

Périmètre volontairement réduit à **deux signaux** : statut administratif et
code APE. Pas d'effectif, pas de forme juridique, **pas de dirigeants** — la
réponse de l'API en contient, ils sont supprimés à la capture et le modèle ne
peut pas les porter.

**Le statut est une PORTE, pas un poids.** Une société radiée n'est pas « un
peu moins bonne » : la personne morale n'existe plus, et nous avons décidé de
ne pas poursuivre les associés. Binaire, donc porte. `statut_diffusion ≠ O`
ferme aussi — opposition INSEE explicite. Le statut `INCONNU` ne ferme rien :
un lead sans enrichissement reste un lead valide.

**Le critère secteur reste à poids nul.** Le code APE est disponible, mais
aucune base ne permet de hiérarchiser les secteurs sans donnée de conversion.
Les 10 points sont reportés sur la fraîcheur — d'abord parce qu'un score sur
100 dont le maximum réel serait 90 est un mensonge d'échelle, ensuite parce que
la fraîcheur est le seul critère dont la pondération soit motivée métier. Ce
n'est **pas** une amélioration du classement : un poids orphelin a été
redistribué.

Mesures : sections I 52,4 % / G 21,0 % / C 10,5 % / L 8,6 %. **Section K = 0 %**
— l'hypothèse d'écarter les véhicules financiers portait sur une population
inexistante, la règle n'a pas été implémentée. Statuts : 69,7 % actives,
26,1 % inconnues, 4,2 % cessées.

### Phase 3 bis — Provenance (non faite)
`enrichment.py` : appel à `recherche-entreprises.api.gouv.fr` par SIREN.

**L'enrichissement n'est pas ce qui crée le lead** — BODACC fournit déjà SIREN
et raison sociale du cédant, donc le lead existe sans cette phase. C'est un
**affineur de score**, avec un usage prioritaire qui vaut à lui seul plus que
tout le reste :

> **La société cédante est-elle toujours active ?**
> Active → la trésorerie de cession est encore au bilan, à placer : c'est le
> prospect. Radiée → le cash est descendu aux associés, la personne morale
> n'est plus prospect et le scoring doit être différent.

Le reste de l'enrichissement (activité, effectif, date de création) est
secondaire. Vérifier aussi le statut de diffusion INSEE : une entreprise non
diffusible est écartée.

`provenance.py` : la traçabilité, appliquée à la sérialisation. Un `Lead`
incomplet doit lever une erreur de validation.
Gate : un test prouve qu'un lead sans provenance ne peut pas être exporté.

### Phase 4 — Serveur MCP (J3 matin)
`mcp_server.py` en stdio, exposant :
- `search_liquidity_events(departement, mois, montant_min)`
- `enrich_company(siren)`
- `score_lead(event)`
Gate : test d'intégration avec un client MCP in-process.

### Phase 5 — Plugin + hook + démo (J3 après-midi)
Structure du plugin :
```
.claude-plugin/plugin.json
skills/scan-liquidity-events/SKILL.md
skills/score-lead/SKILL.md
hooks/hooks.json
.mcp.json
```
**Attention : les dossiers `skills/`, `hooks/` et `agents/` vont à la RACINE du
plugin, jamais dans `.claude-plugin/`.** Seul `plugin.json` y va. C'est
l'erreur la plus fréquente et elle échoue silencieusement.
`commands/` est un format legacy — on n'en crée pas.

Hook `PreToolUse` qui bloque tout appel réseau hors whitelist, avec un message
d'erreur explicite. Il doit être démontrable en live.

README : architecture, choix de conformité, et le **volume réel mesuré**
(nombre de cessions > 200 k€ sur 12 mois en PACA).
Gate : démo end-to-end en une commande.

## Si le temps manque

Priorité de coupe, dans cet ordre : Phase 3 enrichissement → Phase 4 serveur
MCP (repli sur des skills appelant des scripts).

Ordre confirmé au gate Phase 0 : le lead existe sans l'enrichissement, puisque
BODACC porte déjà SIREN et raison sociale du cédant. Si la Phase 3 saute, on
perd la distinction société active / radiée — le scoring est moins fin, mais
le pipeline sort quand même des leads exploitables.
Ne coupe jamais : le parsing du prix, le scoring explicable, le hook de
whitelist. Ce sont les trois choses qui font la valeur du projet en entretien.