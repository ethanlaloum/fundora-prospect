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
  B2B, **~898 cas/an en PACA** (mesuré Phase 1).
  Société active = trésorerie encore au bilan, à placer.
  *Cette ligne portait « intérêt légitime solide » jusqu'à la Phase 3 bis.
  Retiré : le projet ne qualifie pas la base de traitement, il documente sa
  source. Voir le champ `base_legale` en Phase 3 bis.*
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

   **La base de données de la Phase 6 est le premier stockage DURABLE soumis à
   cette contrainte.** Jusqu'ici le seul stockage persistant du projet était un
   cache HTTP jetable. La base, elle, accumule — et elle accumule des noms de
   personnes : `_denomination` (`bodacc.py:97`) retombe sur
   `nom + nomUsage + prenom` quand le cédant est une personne physique, soit
   ~20 % des cédants. Le champ `cedant_denomination` **est** un nom de personne
   sur ce segment.

   Conséquence, décidée au gate de la Phase 6 : le fichier SQLite vit **hors du
   dépôt**, `~/.cache/fundora-prospect/prospects.db`, surchargeable par
   `FUNDORA_DB`. Le `.gitignore` est un filet, pas la garantie — même
   raisonnement que pour les dumps d'exploration. Voir la Phase 6.
5. **Scoring explicable.** Chaque score sort avec le détail de son calcul.
   Pas de boîte noire.
6. **Un apport en nature n'est pas une cession.** Règle métier, pas commodité
   de parsing : dans un apport, le cédant reçoit **des parts sociales, pas du
   cash**. Il n'a aucune liquidité à placer et n'est donc pas un prospect
   Fundora, quel que soit le montant affiché. Les apports sont rejetés avec un
   motif explicite, jamais scorés à zéro — un zéro se noierait dans le flux,
   un rejet motivé est auditable.

## Audit d'historique avant passage en public

Réalisé sur `git log --all`, tous chemins, toutes branches, y compris les blobs
devenus inatteignables.

**Périmètre couvert.** 100 objets analysés : chaque version de chaque fichier
ayant jamais existé, plus les messages de commit et les identités d'auteur.
Les **25 versions historiques de fixtures** ont été revalidées une à une contre
la liste blanche courante — chemins déclarés, gabarits, vocabulaire fermé,
lexique d'`origineFonds`.

**Résultat : aucune donnée personnelle dans l'historique.**

- `explore/out/` — les dumps bruts — n'a jamais été commité : zéro occurrence.
- Les quatre champs à risque (`acte.descriptif`, `acte.vente.opposition`,
  `commercant`, `listepersonnes.personne.administration`) sont substitués dès
  le tout premier commit de fixtures.
- Aucun nom, adresse réelle, téléphone, email, IBAN ni secret.
- Les 30 alertes du balayage automatique sont toutes des faux positifs :
  l'adresse synthétique `1 Rue de la Fixture`, le mot « token » dans une
  variable Python, et les URL d'attaque volontaires des tests de whitelist.

**Une seule résidu réel, non personnel.** Huit blobs antérieurs à la décision
de substitution portent **25 valeurs `activite` réelles** — des descriptions
d'activité commerciale : « Meunerie », « Gîte rural », « Négoce et distribution
de produits pétroliers ». Vérifié : aucune ne contient de marqueur de donnée
personnelle. Leur substitution ultérieure était une décision de **rigueur** —
un texte libre ouvert n'est pas validable par liste blanche — et non la
correction d'une fuite.

**Pas de réécriture d'historique.** Ces valeurs ne sont pas des données
personnelles, et un `filter-repo` changerait tous les SHA : sur un projet dont
l'historique de décisions est lui-même un livrable, le coût dépasse largement
le bénéfice.

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
- **Un test qui garde une contrainte se vérifie par mutation.** On altère
  délibérément l'implémentation et on confirme que le test échoue. Un test vert
  ne prouve rien tant qu'on ne l'a pas vu rougir : c'est la seule façon de
  distinguer un garde-fou d'un test décoratif. Un cas s'est déjà produit sur ce
  projet (« vacuous test », commit `0dfda0c`).

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

### Leçon générale : un chiffre frappant se détache de son référent

**Trois occurrences sur ce projet.** Ce n'est plus un accident, c'est un
mécanisme, et il mérite d'être nommé.

| Chiffre | Ce qu'il désignait vraiment | Ce qu'il est devenu en circulant |
|---|---|---|
| **86 %** | la *part* des personnes morales parmi les cessions > 200 k€ — ce qu'on **garde** | « le recentrage écarte 86 % » — l'inverse exact |
| **~1 046/an** | volume **tous cédants confondus** | attaché au segment personne morale, qui vaut ~898 |
| **0 %** | aucune occurrence de section K **sur 105 cédants enrichis** | « K représente 0 % du flux », contredit par un cas observé depuis |

Le schéma est toujours le même : **le chiffre est plus mémorable que sa
condition d'obtention.** On retient « 86 % », « 1 046 », « 0 % » ; on oublie
« parmi les cessions > 200 k€ », « tous cédants confondus », « sur cet
échantillon-là ». Le chiffre se met alors à circuler seul, et il finit par être
réutilisé dans un contexte où il est faux — souvent en signifiant l'inverse.

Un quatrième cas a été trouvé lors de l'audit final : le README annonçait
encore « 35 pour la fraîcheur, 10 pour le secteur » alors que la Phase 3 avait
reporté ces poids à 45 et 0. Même mécanisme, appliqué à un paramètre : la
valeur avait survécu au changement de sa source.

**Règles de travail qui en découlent :**

1. **Un chiffre ne s'écrit jamais sans son référent** dans la même phrase.
   « 86 % des cessions > 200 k€ ont un cédant personne morale », jamais « 86 %
   des cessions ».
2. **Quand deux chiffres proches existent, écrire les deux ensemble** avec ce
   qui les sépare. ~1 046 tous cédants / ~898 personnes morales, jamais l'un
   sans l'autre.
3. **Un chiffre issu d'un échantillon dit son échantillon.** « aucune
   occurrence sur les 105 cédants enrichis », pas « 0 % du flux ».
4. **Tout paramètre cité dans la documentation doit être vérifiable contre sa
   source.** Les poids, seuils et bornes vivent dans la configuration ou le
   code : la documentation les recopie, donc elle dérive. Les recontrôler fait
   partie de la relecture finale, pas de la bonne volonté.

### Leçon générale : un symbole jamais construit échappe à tous les tests

`Provenance` et `Lead` étaient du code mort depuis la Phase 2. **Les 382 tests
verts du commit `854d662` ne l'ont pas signalé**, et c'est structurel : un test
ne peut pas échouer sur du code qu'il n'appelle pas. *(Chiffre daté du moment
de la découverte, pas de l'état courant de la suite.)* La couverture ne le voit pas non plus — une classe
jamais instanciée n'apparaît dans aucun rapport comme une ligne manquante,
elle apparaît comme une ligne de `class` exécutée à l'import.

Seule une analyse du graphe d'usage le trouve. Le bon critère n'est pas
« symbole jamais importé » — trop large, il signale chaque constante locale —
mais **« nom qui n'apparaît jamais en position d'appel, `X(...)`, dans tout le
dépôt »**. `Lead` n'apparaissait nulle part ; `Provenance` n'apparaissait que
dans l'annotation `Lead.provenance: Provenance`. **Une annotation n'est pas un
usage : elle ne prouve que l'intention.**

**L'audit est un verrou versionné, pas un script jetable :**
`tools/symboles_morts.py`, lancé par `tests/test_symboles_morts.py`. Le projet
a un verrou par contrainte — transport pour les domaines, liste blanche pour
l'anonymisation, porte unique pour la traçabilité. Le code mort était la seule
vérification restée déclarative, et c'est celle qui a laissé passer un défaut
pendant cinq phases.

Le test vérifie deux choses séparées : que le dépôt est propre, **et que
l'audit lui-même a des dents** sur des cas fabriqués. Un audit qui rendrait
toujours « rien à signaler » passerait le premier point sans rien garantir.

Résultat au 2026-08-16 sur les 56 classes et fonctions publiques de `src/` :
6 vivants sans appel direct, **tous justifiés** — trois outils MCP enregistrés
par `@serveur.tool`, trois types utilisés par attribut (`Qualification.ACHAT`,
`GrillePonderation.defaut()`). **Aucun code mort.** Vérifié en relançant
l'audit sur le commit précédent : il y signale exactement `Lead` et
`Provenance`, et rien d'autre.

Deux règles apprises en écrivant l'outil :

- **`@dataclass` ne justifie rien.** Il transforme la classe sur place, il ne
  la confie à aucun appelant. Seul un décorateur qui *enregistre* le symbole
  (`@serveur.tool`) explique une absence d'appel. La distinction compte ici :
  `ResultatRecherche` et `GrillePonderation` sont des dataclasses gelées.
- **L'outil ne résout pas les types, il lit des noms.** `provenance.assembler()`
  compte pour `assembler` sans vérifier le module à gauche du point, donc un
  homonyme d'une autre bibliothèque marquerait notre symbole vivant à tort.
  Assumé : sans cette tolérance, l'audit signalait `assembler` et `serialiser`
  comme morts alors que le serveur MCP les appelle à chaque lead. **Un audit
  qui crie au loup est désactivé dans la semaine.** Le biais va donc vers le
  silence — il peut manquer un mort, il ne doit pas en inventer.

### Leçon générale : un tri en amont est un filtre

Découvert en Phase 4, mais valable bien au-delà de ce projet.

Le serveur MCP n'enrichit que le haut du panier — l'enrichissement coûte un
appel API par lead. Ce pré-classement triait d'abord sur le **montant seul**,
alors que le classement final combine montant et fraîcheur. Conséquence : une
cession fraîche mais modeste n'entrait jamais dans le top-N enrichi, donc
n'était **jamais rendue**. Le biais que la Phase 2 avait éliminé du classement
était réintroduit par la porte de service.

**Règle : tout tri placé en amont d'un pipeline est un filtre, et doit obéir
aux mêmes règles que le classement final.** Un « simple tri pour optimiser »
qui n'utilise pas les mêmes critères que le classement change silencieusement
l'ensemble des résultats possibles. Il ne réordonne pas : il supprime.

Le symptôme est traître parce que la sortie reste plausible — elle est
simplement amputée de ce qu'on ne verra jamais.

**Corollaire trouvé en Phase 3 bis : le compte rendu doit dire la troncature.**
`leads_classables` comptait les leads **après** la coupe à `limite`. Sur une
mesure réelle — 06, six mois, > 300 k€ — il annonçait « 25 classables » sur
115 candidats, ce qui se lit comme 90 refus de la grille. La réalité mesurée :
**49 classables, 25 rendus, 65 candidats jamais enrichis** faute de budget
d'appels, et **un seul** vrai refus à ce stade (société cédante cessée).

Trois catégories que le décompte confondait, et qu'il sépare désormais :
**écarté** (jugé, avec motif) / **tronqué** (classable, hors des N premiers) /
**non enrichi** (jamais examiné). Seule la première est un refus. Le résumé
étant recopié tel quel à l'utilisateur, c'est exactement là que le chiffre
détaché de son référent se propage.

#### Le troisième étage : la correction n'était montée que d'un cran

Trouvé le 2026-08-17 en relisant la sortie de `demo.sh`, après une question
posée en direct sur la démo.

La Phase 3 bis avait remonté le compteur au-dessus de la coupe **finale**
(`leads[:limite]`). Mais la coupe **amont** — `candidats[: limite * 2]`, le
budget d'enrichissement — était restée en dessous. Le compteur restait donc
plafonné à **2 × `limite`**, et il **saturait en silence** dès que la
population dépassait ce budget.

Mesuré le 2026-08-17 sur la même population — 06, six mois, > 300 k€ :

| `limite` | Plafond 2× | Classables annoncés |
|---|---|---|
| 5 *(celui de `demo.sh`)* | 10 | **10 — saturé** |
| 25 | 50 | 49 |
| 50 | 100 | 96 |

`demo.sh` annonçait donc « **10 classables** » sur une population qui en
contient au moins 96 — et c'est le seul jeu de paramètres qu'un recruteur voit.
Le mot « classable » promet un jugement de la grille ; il rapportait combien de
dossiers la grille avait eu **le droit de regarder**.

Le champ s'appelle désormais **`classables_parmi_les_enrichis`**, et le résumé
écrit « 10 classables **parmi les 10 enrichis** ». Le nom porte sa condition
d'obtention, ce qui est la règle 1 des leçons de ce projet appliquée à un
identifiant et non plus à une phrase de documentation.

**La leçon qui s'ajoute : corriger un compteur, c'est le remonter au-dessus de
TOUTES les coupes, pas de la dernière rencontrée.** Un pipeline qui tronque à
plusieurs étages redonne le même défaut à chaque étage laissé en dessous. La
correction de Phase 3 bis était juste et incomplète — et son commentaire, en
disant « se compte AVANT la coupe » au singulier, a rendu l'étage restant
invisible pendant deux phases.

**Corollaire de méthode : renommer plutôt qu'augmenter le budget.** L'autre
option était d'enrichir un nombre fixe de candidats quelle que soit la limite
d'affichage — le chiffre serait devenu exact. Refusée : elle fait payer ~100
appels API à qui n'en demande que 5. Nommer juste coûte zéro appel, et
l'information manquante (`candidats_non_enrichis`) était déjà affichée à côté.

**`demo.sh` appelle désormais avec `limite=25`**, le défaut de l'outil et la
valeur citée par le README — même requête, mêmes chiffres aux deux endroits.
Coût mesuré le 2026-08-17, cache froid : **6,8 s à `limite=5` contre 10,6 s à
`limite=25`**, pour 40 appels API de plus. Le compteur annonce alors
« 49 classables parmi les 50 enrichis » au lieu de saturer à 10.

Ce qui a fait apparaître une **troisième** troncature, d'affichage cette fois :
25 leads font 75 lignes, soit plusieurs écrans. La démo n'en imprime que 5 —
et le dit (`[5 premiers affiches sur 25 rendus — troncature d'ecran, pas un
refus]`). Sans cette ligne, l'écran contredirait le résumé qui vient d'annoncer
« 25 rendus », sous les yeux du spectateur. Même règle qu'ailleurs : **une coupe
qui ne se déclare pas se lit comme un résultat.**

#### Le jumeau : `annonces_examinees`

Cherché délibérément après la correction — *si un compteur ment, son voisin
ment peut-être de la même façon.* Il mentait, et pire.

`annonces_examinees` était compté après **deux** coupes : le plafond de
rapatriement (600) et le filtre `construire_annonce` du client BODACC. Mesuré
le 2026-08-16 sur le 06, six mois :

| Population | Volume |
|---|---|
| Publiées au BODACC | **662** |
| Rapatriées (plafond 600) | **600** — 62 jamais lues |
| Exploitables | **458** — 142 sans cédant, sans décompte nulle part |

Le compteur annonçait **458**, soit **69 % de la population présentée comme la
totalité** — et le plafond mordait dans la mesure même que le README citait.
Les 142 annonces sans cédant sont un filtre dur documenté depuis la Phase 0,
mais elles n'apparaissaient dans aucun compteur : ni dans le total, ni dans
`ecartes`.

Remplacé par `annonces_publiees` / `annonces_rapatriees` /
`annonces_exploitables` / `sans_cedant_ou_illisibles` / `plafond_atteint`. Les
réserves ne s'affichent que **quand elles mordent** : une mise en garde
permanente cesse d'être lue.

`rechercher` rend désormais un `ResultatRecherche` qui porte, à côté de la
liste, ce que la recherche **n'a pas regardé**. Coût : une requête `limit=0`
par recherche. C'est le prix du seul nombre qui dise ce qu'on ignore.

**La leçon générale :** un compteur nommé d'après une population doit être
calculé sur cette population. Sinon il ne décrit pas un résultat, il décrit un
budget — et le lecteur, lui, le lira comme un résultat.

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

### Phase 3 bis — Provenance ✅ FAIT

`provenance.py` : la traçabilité, appliquée à la sérialisation.

**Une porte de sortie unique, pas une fonction d'aide.** `serialiser` n'accepte
qu'un `Lead`, donc une `Provenance` validée. Le contrôle de type n'est pas de
la défense d'usage : c'est lui qui ferme le contournement. Tant qu'un second
chemin existe — un dict monté à la main à côté — la contrainte ne vaut que par
la discipline de celui qui écrit le prochain appel.

**Le défaut corrigé était exactement celui-là.** `Provenance` et `Lead`
existaient depuis la Phase 2 mais n'étaient construits nulle part : le serveur
MCP assemblait sa réponse à la main et n'y mettait qu'**un** des quatre champs
(`url_publication`). La contrainte 3 était documentée, testée nulle part, et
fausse en production. *Un modèle défini n'est pas une garantie tant que rien
n'oblige à passer par lui* — à rapprocher de la leçon « un tri en amont est un
filtre » : dans les deux cas, le code réel contournait la règle écrite.

Les quatre champs sont obligatoires **et non vides** : `""` satisfait le type
`str` et passerait le contrôle d'obligation, laissant un champ présent et muet.
L'URL doit être absolue, sinon la provenance n'est pas vérifiable par un tiers.

Un lead qui échoue au contrôle **sort du flux avec son motif**
(`provenance incomplete`), au même titre qu'un apport ou une société radiée.
Ni rendu sans provenance, ni perdu en silence, ni propagé en exception jusqu'au
client MCP.

#### `base_legale` est descriptif, jamais une qualification juridique

**Décision explicite, verrouillée par un test.** Le champ dit d'où vient la
donnée et quel segment elle concerne — deux choses vérifiables. Il ne nomme
aucune base de traitement et ne cite aucun article.

Qualifier un traitement relève du **DPO de l'exploitant**, qui seul connaît la
finalité réelle, les durées de conservation et l'information des personnes. Une
formulation juridique assurée, écrite ici par un outil de détection, donnerait
l'apparence d'une analyse qui n'a pas eu lieu : c'est un risque pour
l'exploitant, pas une garantie.

Le test interdit `rgpd`, `article` et `intérêt légitime` dans le champ, pour
tous les types de cédant. Sans lui, la première relecture qui trouve le champ
« trop vague » y remettrait une citation.

La formule « intérêt légitime solide » figurait dans la section « Cible » de ce
fichier et dans le README ; elle a été retirée des deux au même moment. La
laisser aurait garanti la dérive : un vocabulaire disponible dans le document
de référence finit par descendre dans un champ exporté, et le test l'aurait
alors bloqué sans que personne comprenne pourquoi.

Trois segments, trois textes distincts : personne morale (B2B), personne
physique (« qualification à établir avant toute utilisation »), et type non
renseigné — qui retombe sur le traitement prudent, parce qu'un segment qu'on ne
sait pas nommer n'est pas du B2B établi.

Gate : ✅ un test prouve qu'un lead sans provenance ne peut pas être exporté.
Vérifié par mutation — cinq altérations de l'implémentation, cinq détectées.

**Mesuré, pas déduit.** Sur une exécution réseau réelle du 2026-08-16 (06, six
mois, > 300 k€) : `provenance incomplete` = **0 sur 458 annonces examinées**, et
les 25 leads rendus portent les quatre champs. C'était le résultat attendu, mais
« devrait valoir 0 » est la formule qui a produit tous les défauts de ce projet.
Le raisonnement plausible ne remplace pas la mesure — voir la leçon sur les
symboles jamais construits.

`demo.sh` a un quatrième acte : les quatre champs d'un lead réel, puis le même
lead privé de son URL, qui ne se sérialise pas. Les actes 2 et 3 barrent ce qui
**entre**, le 4 barre ce qui **sort**.

### Phase 4 — Serveur MCP ✅ FAIT

`search_liquidity_events` execute **le pipeline complet** et rend des leads
deja scores et tries. Ecart assume a la lettre de la spec : trois outils
strictement granulaires obligeraient le modele a orchestrer des dizaines
d'appels, ce qui est lent et indemontrable en direct. `enrich_company` et
`score_lead` restent exposes pour inspecter un cas isole.

**La sortie porte les motifs de refus**, ventiles : « 668 annonces publiees,
600 rapatriees seulement (plafond de rapatriement atteint), 140 sans cedant ou
illisibles, 460 exploitables, 49 classables parmi les 50 enrichis, 334 sous le
montant minimum, 6 apport, 2 absent, 2 acte trop ancien, 1 societe cedante
cessee ». L'auditabilite doit etre visible dans le transport, pas seulement
dans les tests.

*Cette phrase citait encore le format d'avant la Phase 3 bis — « 458 annonces
examinees, 5 classables » — jusqu'au 2026-08-17. L'exemple de `SKILL.md` aussi,
et lui est du prompt. Voir la leçon sur le chiffre qui survit à sa source ;
l'exemple de `SKILL.md` est désormais **régénéré depuis `_resume` par un
test**, parce que la recopie manuelle avait déjà échoué deux fois.*

**Le pre-classement avant enrichissement se fait sur le SCORE PROVISOIRE, pas
sur le montant.** L'enrichissement coute un appel API par lead, donc seul le
haut du panier est enrichi — mais trier sur le montant reintroduirait le biais
que la Phase 2 a corrige, et une cession fraiche mais modeste ne serait jamais
enrichie donc jamais rendue.

Les descriptions d'outils sont du prompt, pas de la documentation : elles
disent le format attendu (`"06"` et non `6`), les unites, et que les resultats
sortent deja tries. Le type `str | int` rattrape un modele qui passerait un
entier, le schema JSON le refuserait avant normalisation.

### Phase 4 — specification d'origine
`mcp_server.py` en stdio, exposant :
- `search_liquidity_events(departement, mois, montant_min)`
- `enrich_company(siren)`
- `score_lead(event)`
Gate : test d'intégration avec un client MCP in-process.

### Phase 5 — Plugin + hook + démo ✅ FAIT

Arborescence conforme : `skills/` et `hooks/` a la RACINE, seul `plugin.json`
dans `.claude-plugin/`. Verifie par un test, parce que l'erreur echoue
silencieusement.

**Les deux verrous sont scenarises explicitement.** Le hook barre l'agent, le
transport barre le code, et la demo montre qu'aucun des deux ne suffit seul —
le hook ne voit pas une URL cachee dans un fichier `.py`. Montrer la limite
rend la demonstration plus forte : un recruteur technique la verrait de toute
facon, et s'il la repere avant nous la demo devient une demo de vendeur. La
limite est verrouillee par un test.

Message de refus : tient en une hauteur d'ecran, cite la contrainte 2 par son
numero, et vise un domaine evocateur (`www.linkedin.com`) plutot qu'un
`example.com` abstrait.

`./demo.sh` en une commande, trois actes : pipeline reel, hook, transport.

### Phase 5 — specification d'origine
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

## Phase 6 — interface web sur le même cœur

Le plugin Claude Code reste. On ajoute une seconde surface, pas un
remplacement :

```
coeur Python  ─┬─  mcp_server.py   ->  Claude Code
               └─  api.py (FastAPI) ->  navigateur
```

**Le back-end appelle le code Python directement.** Il n'appelle pas l'API
Claude pour exécuter le pipeline : un score qui traverse un LLM cesse d'être
reproductible et auditable, ce qui détruit l'argument central du projet.

### Étape 1 ✅ — le pipeline est descendu dans le cœur

`pipeline.py` porte `executer`, `resumer`, `normaliser_departements` et
`evaluer_hypothese`. `mcp_server.py` est passé de 440 à 253 lignes, dont
l'essentiel est désormais des descriptions d'outils — c'est-à-dire du prompt.

Les deux fonctions réseau — `rechercher` et `enrichir` — sont des **paramètres**
de `executer`, avec les vraies fonctions en défaut. Chaque surface est sa
propre racine de composition. C'est aussi ce qui garde vivantes les douze
substitutions de `tests/test_mcp_server.py` : les deux raisons sont vraies, et
il faut dire les deux.

`LIMITE_MAX` a perdu un double rôle au passage : il bornait l'argument `limite`
**et**, sous la forme `LIMITE_MAX * 2`, le budget d'appels API. Le budget
s'appelle désormais `PLAFOND_ENRICHISSEMENTS`, avec `CANDIDATS_PAR_LEAD` pour
le facteur. Encore un nom qui promettait une chose et en décrivait deux.

### Étape 1 bis ✅ — les motifs de refus se décident à un seul endroit

`motif_ecart` et `repartir` sont partagés par la recherche en direct et par le
job de collecte à venir. Ce qui divergerait sinon n'est pas la boucle — trois
`if` — mais le **vocabulaire des motifs** et l'**ordre des tests**.

**Ce vocabulaire n'était gardé par aucun test.** Mutation faite avant d'écrire
la moindre ligne : remplacer `str(prix.qualification)` par la chaîne `"ecarte"`
laissait les 436 tests verts. Les tests existants vérifiaient que `ecartes`
était non vide et que sa somme était positive — jamais ce qu'il y avait dedans.
C'est le même angle mort que « un symbole jamais construit échappe à tous les
tests », appliqué à une **valeur** au lieu d'un symbole. `tests/test_pipeline.py`
le ferme, vérifié par quatre mutations.

### Décisions du gate Phase 6

**On ne calcule pas à la volée.** Un job de collecte balaye sans contrainte de
temps de réponse et écrit en base ; l'API ne fait que lire.
`PLAFOND_ENRICHISSEMENTS` et le plafond de rapatriement cessent d'être des
limites subies.

**La base vit hors du dépôt.** Voir la contrainte 4 : c'est le premier stockage
durable du projet à porter des noms de personnes.

**Le score n'est jamais figé en base.** Il est recalculé à la lecture. La
fraîcheur décroît dès le premier jour, demi-vie 180 jours, sans plateau : un
score stocké est faux le lendemain, et le figer industrialiserait dans une
table le défaut signature de ce projet — un chiffre qui survit à sa source. La
grille est par ailleurs rechargeable sans toucher au code ; un score gelé
annulerait cette propriété. Et `evaluer` est pure, déterministe, avec
`aujourdhui` en paramètre explicite : elle a déjà la forme qu'exige le recalcul.

Pas de colonne de score « à titre historique » non plus. **Une colonne que rien
ne lit est de la donnée morte, et `tools/symboles_morts.py` ne voit pas les
colonnes.** Le seuil où ce choix se rediscuterait est de l'ordre de quelques
centaines de milliers de lignes — la France entière sur dix ans — et la réponse
serait alors une colonne matérialisée avec un job de recalcul, pas un score
gelé à la collecte.

**On stocke aussi les annonces écartées.** Sans elles, `ecartes` devient un
nombre figé qu'on ne peut plus recalculer ni justifier. Les seules qui restent
invisibles sont celles sans cédant : `construire_annonce` rend `None`, il n'y a
même pas d'`id`. Elles ne peuvent être que **comptées**.

**`montant_min` disparaît de la collecte.** Le job ramasse tout ; le seuil
devient un filtre de lecture. Sinon le relever imposerait une recollecte.

**Ré-enrichissement : 30 jours pour les actives, jamais pour les cessées.** Une
société ne redevient pas active. Cette phrase est une affirmation tant qu'un
test ne la prouve pas — il en faut un.

**`evenement_revision` est conservée.** Un rectificatif BODACC est
indistinguable d'une régression de notre parser si on écrase, et on n'aurait
aucun moyen de savoir lequel des deux vient de se produire. C'est la seule
trace qui permette de trancher.

**Le périmètre reste PACA, mais le job prend la liste de départements en
paramètre.** Le coût est nul et l'élargissement débloquera le critère
département, laissé à poids nul avec la mention « prêt à servir si le périmètre
s'élargit ».

### L'asymétrie de population entre les deux surfaces — écrite exprès

**Le serveur MCP reste en direct ; l'API lit la base. Les deux ne verront donc
pas la même population.** Le choix est délibéré : le chemin direct se démontre
bien en entretien, et le basculer sur la base sera un changement d'une ligne
dans `mcp_server`. Mais une asymétrie tue devient un bug ; écrite, elle reste
un choix.

Ce qui les sépare, et ce qui ne les sépare pas :

| | MCP en direct | API sur base |
|---|---|---|
| Scoring | `evaluer`, même grille | `evaluer`, même grille |
| Provenance | `provenance.serialiser` | `provenance.serialiser` |
| Motifs de refus | `motif_ecart` | `motif_ecart` |
| Annonces rapatriées | plafond 600 | tout |
| Candidats enrichis | `2 × limite`, plafond 200 | tous |
| Fenêtre | celle de la requête | celle de la dernière collecte |

**Aucune divergence de jugement, une divergence de population.** Mesuré le
2026-08-17 sur le 06, six mois, > 300 k€ : 668 annonces publiées, 600
rapatriées, 460 exploitables, 116 candidats — dont **50 enrichis** à
`limite=25`. Sur cette recherche-là, le MCP juge donc au mieux 50 des 116
candidats, là où la base les portera tous.

C'est exactement la leçon « un tri en amont est un filtre », mais installée
cette fois **entre deux surfaces** au lieu d'être à l'intérieur d'une seule.
Elle est acceptable tant qu'elle est déclarée. Le jour où quelqu'un comparera
un résultat MCP et un résultat web sans savoir ça, il conclura à un bug de
scoring et cherchera au mauvais endroit.

## Si le temps manque

Priorité de coupe, dans cet ordre : Phase 3 enrichissement → Phase 4 serveur
MCP (repli sur des skills appelant des scripts).

Ordre confirmé au gate Phase 0 : le lead existe sans l'enrichissement, puisque
BODACC porte déjà SIREN et raison sociale du cédant. Si la Phase 3 saute, on
perd la distinction société active / radiée — le scoring est moins fin, mais
le pipeline sort quand même des leads exploitables.
Ne coupe jamais : le parsing du prix, le scoring explicable, le hook de
whitelist. Ce sont les trois choses qui font la valeur du projet en entretien.