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

#### La limite de l'outil : il voit des symboles, pas des expressions

Trouvée en Phase 6, par un cas concret. `provenance.base_legale` s'écrit :

```python
return BASES_LEGALES.get(type_cedant, BASES_LEGALES[TypeCedant.INCONNU])
```

Ce repli **ne peut jamais tirer** : les trois membres de `TypeCedant` sont tous
des clés de `BASES_LEGALES`. C'est du code mort, et l'audit ne le voit pas.

Ce n'est pas un défaut de l'implémentation, c'est son périmètre : `collecter`
ne ramasse que les `ClassDef` et `FunctionDef` de **premier niveau** dans
`src/`. Une branche morte à l'intérieur d'une fonction, un argument par défaut
inatteignable, une clause `else` que rien ne peut atteindre — rien de tout cela
n'est un symbole, donc rien de tout cela n'est audité.

**On ne corrige pas l'outil.** Détecter du code inatteignable demande une
analyse de flux, pas une lecture de noms : c'est un autre outil, avec un autre
taux de faux positifs, et la règle « un audit qui crie au loup est désactivé
dans la semaine » s'appliquerait immédiatement. La limite est écrite ici pour
qu'on sache où l'audit s'arrête, pas pour être comblée.

Ce que ça implique en pratique : **une mutation qui survit ne prouve pas
toujours un trou de test.** Elle peut porter sur du code que rien n'atteint. Il
faut vérifier laquelle des deux avant de conclure — sinon on écrit un test pour
garder une ligne qui ne s'exécute jamais.

### Leçon générale : vérifier qu'une chose existe n'est pas vérifier ce qu'elle dit

Découvert en Phase 6 en extrayant `motif_ecart`. Avant d'écrire la moindre
ligne, une mutation pour s'assurer que les tests couvraient le code déplacé :
remplacer le motif de refus par la chaîne `"ecarte"`.

**Les 436 tests sont restés verts.**

Les tests existants vérifiaient `assert stats["ecartes"]` et
`assert sum(stats["ecartes"].values()) > 0`. La structure était là, non vide,
et son contenu n'était lu par personne. Un motif écrit « apport en nature »
d'un côté et « apport » de l'autre aurait cassé tout comptage agrégeant les
deux sources sans qu'aucun test ne rougisse.

#### Les six visages du même mécanisme

| Ce qu'on vérifiait | Ce qu'on croyait vérifier | Pourquoi c'était aveugle |
|---|---|---|
| **Le symbole est défini** (`Lead`, `Provenance`) | qu'il fonctionne | un test ne peut pas échouer sur du code qu'il n'appelle pas |
| **Le compteur a une valeur** (`annonces_examinees`) | qu'il décrit sa population | il décrivait un budget, sous un nom qui promet un total |
| **L'exemple est présent** (`SKILL.md`) | qu'il est à jour | la valeur avait survécu au changement de sa source |
| **La structure est non vide** (`ecartes`) | qu'elle dit la bonne chose | la présence et le contenu sont deux propriétés distinctes |
| **Le nombre est exact** (`annonces_exploitables == 3`) | qu'il désigne la bonne grandeur | le corpus rendait deux grandeurs égales |
| **Le code traite bien l'entrée** (`collecte` avec `enrichis`) | qu'il traite bien le RÉEL | l'entrée était fabriquée, la source ne la produit jamais |

Le mécanisme commun : **ce qui est facile à vérifier se substitue à ce qui
compte.** Présence, nom, non-vacuité, existence — quatre propriétés bon marché
qui se laissent tester en une ligne, et qui passent toutes pour des raisons
sans rapport avec ce qu'on voulait garantir. Le test est vert, la propriété
n'est pas gardée, et personne ne le sait parce que le vert est indistinguable
du vert.

#### La règle et sa technique

**Toute assertion de présence doit être doublée d'une assertion de contenu.**
`assert charge["breakdown"]` ne vaut rien seul ; il faut dire ce que le
breakdown doit contenir.

**Et la seconde se vérifie par MUTATION DE CONTENU** — remplacer la valeur par
une autre valeur non vide et de même type. Pas par une valeur absente : mettre
`None` ou `""` fait rougir l'assertion de présence et donne l'illusion d'une
couverture. C'est précisément la différence entre les deux propriétés.

#### Balayage systématique, Phase 6

Douze mutations de contenu passées sur toute la suite, aucune ne touchant à la
présence d'une structure. Résultat : **cinq survivantes, dont quatre vrais
trous.**

| Mutation | Résultat |
|---|---|
| `breakdown` : le motif d'un critère porte le nom du critère | **trou — contrainte 5** |
| le motif du critère montant devient « contribution calculée » | **trou — contrainte 5** |
| le motif de la fraîcheur perd le nombre de jours | **trou — contrainte 5** |
| `annonces_exploitables` compte les candidats | **trou** |
| `base_legale` : le repli `INCONNU` rend le texte B2B | survit — code inatteignable |
| `SOURCE` nomme une autre origine | détectée |
| `enrichis` compte les candidats | détectée |
| `date_collecte` ignore la date passée | détectée |
| `siren` rend la dénomination | détectée |
| `statut_motif` porte le statut | détectée |
| le résumé perd le libellé du motif | détectée |

**Trois des quatre trous portent sur la contrainte 5**, et tous viennent du
même test : `assert contribution.motif.strip()`. Il vérifie qu'un motif existe.
Or la contrainte ne demande pas qu'un motif existe, elle demande que **le
détail du calcul** soit là — de quoi refaire l'opération. Un motif générique et
non vide la viole tout en passant le test. Les nouveaux tests exigent donc les
nombres qui permettent de recalculer : le montant d'entrée et ses deux bornes,
le nombre de jours et la forme de la décroissance.

Le cas `base_legale` n'est pas un trou de test du tout : la mutation survit
parce que le code est **inatteignable**. Voir la limite de
`tools/symboles_morts.py`, plus haut — l'audit voit des symboles, pas des
expressions.

#### Le quatrième trou est d'une autre famille : ce n'est pas l'assertion, c'est le corpus

Les trois premiers viennent d'une assertion trop faible. Celui-ci vient d'une
assertion **juste**, appliquée à un jeu de données qui ne pouvait pas la mettre
en défaut.

`annonces_exploitables` était asserté par `assert stats["annonces_exploitables"]
== 3`, ce qui est une assertion de contenu en bonne et due forme. Mais le corpus
du test contenait trois annonces qui étaient **toutes** des candidates. Sur ce
jeu-là, `len(annonces)` et `len(candidats)` valent tous les deux 3 : le test
était vert quelle que soit celle des deux qu'on lui donnait. Il n'a jamais rien
gardé.

**Règle : un test qui ne peut pas distinguer deux valeurs n'en garde aucune.
Le corpus doit être choisi pour qu'elles diffèrent.** Ici il fallait des
annonces exploitables mais jamais candidates — des apports, qui existent en
quantité dans le flux réel.

C'est une famille distincte parce que le remède est distinct. Contre une
assertion faible, on renforce l'assertion. Contre un corpus dégénéré, renforcer
l'assertion ne sert à rien : il faut construire le cas où les deux grandeurs se
séparent. Et rien dans la lecture du test ne signale le problème — l'assertion
est spécifique, le nombre est exact, tout a l'air rigoureux.

La question à se poser devant tout test de compteur : **existe-t-il, dans ce
corpus, une autre grandeur qui vaudrait le même nombre ?** Si oui, le test ne
départage pas.

Les quatre trous ont été fermés, et les quatre mutations sont rejouées : quatre
détectées. La suite passe de 446 à 450 tests.

#### Le sixième visage : un test alimenté à la main, sur une donnée que la source ne produit jamais

C'est le plus difficile à voir des six, et pour une raison structurelle :
**aucune mutation du code de production ne le révèle.**

Le cas, au palier 2. `lire` accepte un dict `collecte` porteur des compteurs de
population. Le test qui vérifiait que la réserve « l'étendue de la collecte
n'est pas connue » disparaît bien lui passait ceci :

```python
collecte={
    "annonces_publiees": 662,
    ...
    "classables_parmi_les_enrichis": 1,   # <- n'existe que sur le chemin direct
    "enrichis": 1,                        # <- idem
}
```

Le test passait. `resumer` traitait correctement ce dict. Mais **la source
réelle — `entrepot.compteurs_de_collecte`, écrite un palier plus tard — ne
produit jamais ces deux clés** : ce sont des compteurs de budget
d'enrichissement, qui n'ont de sens que sur le chemin direct. Le test validait
un contrat que personne n'honore.

Pourquoi la mutation ne le voit pas : muter le code de production ne change pas
l'entrée du test. Le test continue de fabriquer son dict, et la mutation est
détectée ou non selon qu'elle touche le chemin *fabriqué*. Le défaut n'est pas
dans le code testé, il est dans **l'écart entre l'entrée du test et l'entrée
réelle** — un espace où aucune mutation ne va.

Ce que ça implique, et qui coûte plus cher que les cinq autres remèdes :

**Un test dont l'entrée est fabriquée ne prouve rien sur la production tant
qu'un autre test n'a pas branché le même chemin sur la vraie source.** Les
doubles restent légitimes — la suite entière repose dessus, et elle tourne en
5 secondes sans réseau grâce à eux. Mais chaque contrat entre deux modules doit
avoir **au moins un** test qui les branche réellement l'un sur l'autre.

Ici, c'est `tests/test_collecte.py::test_la_reserve_d_etendue_disparait_quand_le_job_a_tourne` :
il fait tourner le job, lit la table qu'il a remplie, et passe ces compteurs-là
à `resumer`. C'est ce test qui a montré que le dict du palier 2 était une
fiction — pas une mutation, pas une relecture.

Le signal à surveiller : **un littéral dans un test qui décrit la sortie d'un
autre module.** Chaque clé écrite à la main y est une hypothèse sur un contrat,
et une hypothèse non vérifiée finit par être fausse.

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

#### `collecte_ecart` : table VALIDÉE au gate, ABANDONNÉE au palier 3

Elle figurait dans le schéma proposé, elle a été validée, et elle n'existe pas.
La décision est écrite ici plutôt que d'avoir simplement disparu — sinon
quelqu'un relira le schéma initial, constatera la table manquante, et la
recréera en croyant réparer un oubli.

**Le motif.** Elle devait porter le décompte des refus par motif, une ligne par
`(collecte, motif)`. Mais la même proposition décidait de **stocker les annonces
écartées** dans `evenement`. Les deux décisions se contredisent sans que ça se
voie : dès lors que les écartés sont en base avec leur `qualification`, leur
décompte par motif se **recalcule** à la lecture, par la même `motif_ecart_faits`
que partout ailleurs.

La table aurait donc figé une valeur dérivable — et elle aurait dérivé le jour
du premier renommage de motif : la base aurait continué à servir « apport en
nature » quand le code dit « apport ». C'est la leçon « un paramètre recopié
dérive de sa source », appliquée à une table.

Ne restent en base que les **quatre nombres qu'aucune relecture ne peut
retrouver** : `annonces_publiees` (ce que le BODACC déclarait contenir),
`annonces_rapatriees` (ce qu'on en a lu), `sans_cedant_ou_illisibles` (écartées
avant d'avoir un `id`, donc sans ligne où être comptées) et `plafond_atteint`.

**Le test de recréation :** si une donnée peut se recalculer depuis ce qui est
déjà stocké, la stocker en second exemplaire crée une divergence future, pas une
commodité. Si elle ne le peut pas, elle doit être stockée. C'est le seul critère
qui a servi à trancher le contenu de `collecte`.

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

### Palier 1 ✅ — le schéma et la porte d'écriture

`entrepot.py` : `evenement` et `cedant`, `ouvrir`, `enregistrer`.

**Le verrou de la contrainte 3 survit au passage en base, et il en faut deux.**
`enregistrer` n'accepte qu'un `Lead` — même contrôle de type que
`provenance.serialiser`, pour la même raison. Mais une table est un second
chemin de sortie, et un `INSERT` écrit dans six mois ne demande la permission à
personne : les `CHECK` du schéma refusent une ligne intraçable **même en SQL
direct**. C'est le seul barrage qui protège du code pas encore écrit, exactement
comme `TransportWhitelist` au niveau réseau.

Les tests qui l'exercent écrivent donc du SQL à la main, littéralement ce que
ferait un futur distrait.

**On ne crée que ce qu'on utilise.** `collecte`, `cedant_journal` et
`evenement_revision` arrivent avec les paliers qui les lisent. Une table créée
d'avance est de la structure morte, et l'audit ne voit ni les tables ni les
colonnes. D'où `VERSION_SCHEMA` et une migration par palier.

Dix mutations, **zéro survivante** — après correction de deux trous que le
premier passage avait révélés :

- **`premiere_collecte`** était asserté sur deux collectes **à la même date**.
  Les trois colonnes de date y valaient le même jour : le test était vert quelle
  que soit celle qu'on lui donnait. Corpus dégénéré, rencontré la semaine même
  où la règle a été écrite plus haut — la connaître ne suffit pas, il faut la
  vérifier par mutation.
- **`PRAGMA foreign_keys = ON`** n'était gardé par rien. SQLite n'applique pas
  les clés étrangères par défaut : une contrainte déclarée mais désactivée est
  une garantie qui n'existe que sur le papier, et rien ne la distingue d'une
  garantie réelle à la lecture du schéma.

### Palier 2 ✅ — la lecture, et la preuve que rien n'est figé

`entrepot.evenements` rend des faits (`EvenementStocke` : le fait **et** la date
à laquelle il a été constaté). `pipeline.lire` les classe. Le stockage ne score
rien, le cœur ne connaît pas SQLite.

**Le test du palier :** deux lectures de la même ligne, à six mois d'écart,
rendent deux scores — le plus tardif étant le plus faible. Sans lui, « le score
est recalculé à la lecture » reste une intention : rien ne distingue un recalcul
d'une valeur figée tant qu'on ne lit qu'une fois. Un second test précise que
c'est bien la **fraîcheur** qui bouge et le montant qui ne bouge pas.

**`date_collecte` vient de la base, jamais de l'horloge du lecteur.** Une
provenance datée du jour de lecture prétendrait qu'on vient de consulter le
BODACC alors qu'on relit une ligne vieille d'une semaine. D'où le paramètre
`date_collecte_de` de `classer` : à la collecte c'est le jour même, en lecture
c'est la base. Le coder en dur était la mutation la plus tentante, et elle est
attrapée.

**Deux étapes de plus sont descendues dans le partagé**, parce qu'elles
existaient en double dès qu'une seconde surface lisait :

- `motif_ecart_faits` ne prend plus un type porteur mais **des faits**. Une
  `Annonce` fraîche et un `LiquidityEvent` relu portent les mêmes faits sous
  deux types : deux fonctions les auraient traités séparément et auraient fini
  par diverger sur un mot. Un test compare les deux chemins sur le produit
  cartésien des cinq qualifications et de trois seuils — **seule leur
  comparaison** voit ce genre d'écart, aucun test d'un chemin isolé ne le peut.
- `classer` porte le scoring, la porte du statut, la provenance, le tri et la
  troncature. `executer` et `lire` l'appellent tous les deux.

**`resumer` reste la seule rédaction du projet.** Les deux sources n'ont pas la
même population — en direct la grille ne voit que les dossiers *enrichis*, en
base elle voit tous les *candidats* — donc le référent change dans la phrase.
Les fragments diffèrent, l'assemblage est unique. Et quand les compteurs de
collecte manquent, le résumé le **dit** au lieu d'inventer un total : « l'étendue
de la collecte n'est pas connue ». Une base ne sait pas, par elle-même, ce
qu'elle n'a pas reçu.

**Le montant n'est pas filtré en SQL.** Le sortir en `WHERE` ferait disparaître
les écartés du décompte — « un tri en amont est un filtre », appliqué cette fois
à une clause. Un test le verrouille, et la mutation correspondante est attrapée.

Corpus de l'aller-retour choisi pour que **chaque paire de grandeurs proches se
sépare** : cédant `pm` et `pp`, statut actif / cessé / inconnu, date d'acte
présente et absente, événement retenu et écarté, SIREN présent et absent,
montants de part et d'autre du seuil. Deux corpus dégénérés ont déjà coûté deux
tests aveugles sur ce projet.

Quatorze mutations, **zéro survivante**.

### Palier 3 ✅ — le job de collecte

`collecte.py` : `balayer(connexion, departements=PACA, mois=12, …)`, avec
`rechercher` et `enrichir` en paramètres comme partout ailleurs dans le cœur.
Schéma v2 : la table `collecte`.

**Le TTL n'est plus une affirmation.** Trois règles, trois tests :
un SIREN jamais vu est enrichi ; une active de plus de 30 jours est resondée ;
une cessée ne l'est **jamais**, quel que soit son âge. Ce dernier test est
paramétré de 0 à 5 000 jours **de part et d'autre du seuil** — une cessée
fraîche seule serait verte même si c'était le délai, et non le statut, qui la
protégeait. Corpus dégénéré appliqué à un paramètre.

**`collecte_ecart` n'a pas été créée**, contrairement au schéma proposé. C'était
une erreur de ma conception initiale : depuis le palier 1 on stocke les annonces
écartées, donc leur décompte par motif se **recalcule** depuis `evenement` par
la même `motif_ecart_faits`. Une table qui le figerait dériverait au premier
renommage de motif. Ne sont stockés que les quatre nombres qu'aucune relecture
ne peut retrouver : `annonces_publiees`, `annonces_rapatriees`,
`sans_cedant_ou_illisibles`, `plafond_atteint`.

**La ligne de collecte est écrite AVANT le travail**, `terminee_a` à NULL. Un
balayage coupé laisse donc une trace qui se déclare incomplète, et le résumé le
répercute. S'il n'écrivait qu'à la fin, une interruption serait indistinguable
d'un balayage jamais lancé — et les compteurs du passage précédent seraient
servis comme s'ils étaient à jour. C'est le plafond de rapatriement compté comme
la totalité, déplacé d'un cran.

**`compteurs_de_collecte` retient la dernière ligne par département, pas la
somme.** Le job tourne périodiquement : additionner les passages compterait
plusieurs fois les mêmes annonces publiées, et le total gonflerait à chaque
exécution sans que rien n'ait changé dans la source.

**`resumer` branche désormais sur deux axes indépendants** — la source est-elle
connue, et y a-t-il un budget d'enrichissement — au lieu d'un seul « en direct
ou non ». La lecture peut très bien connaître ce que la source contenait sans
avoir les compteurs de budget, qui n'existent que sur le chemin direct. Un test
du palier 2 encodait cette confusion en fabriquant un dict `collecte` contenant
`enrichis` : il passait, mais décrivait une source qui n'existe pas. **Un test
qui fabrique son entrée finit par valider un contrat que personne n'honore.**

Seize mutations, **zéro survivante** — après correction d'un trou. La mutation
« le job n'a plus de déduplication par SIREN » a d'abord survécu, et elle a
révélé autre chose qu'un test manquant : **le dédoublonnage du job est redondant
avec celui de `sirens_a_enrichir`**. Le retirer ne change aucun appel API. Son
seul effet observable portait sur `cedants_distincts`, qui n'était asserté nulle
part et annonçait alors 10 sociétés là où il n'y en a qu'une. Les deux lignes se
ressemblent et ont deux rôles : l'une évite des appels, l'autre nomme une
grandeur. Un commentaire le dit, pour qu'aucune relecture n'en « simplifie » une.

### Palier 4 ✅ — le journal des transitions de statut

`cedant_journal` : **une ligne par CHANGEMENT observé, jamais par sondage.**

Trois choses n'y entrent pas, et c'est ce qui fait sa valeur :

- **La première observation n'est pas une transition.** `cedant.enrichi_a` la
  date déjà. L'écrire ferait ~3 300 lignes au premier balayage PACA, toutes
  sans information.
- **Un sondage qui confirme n'écrit rien.** Sinon la table grossit à chaque
  passage en ne disant rien de plus.
- **Une transition immobile est refusée par le schéma**, `CHECK (statut_avant
  <> statut_apres)` — le même barrage que les `CHECK` de traçabilité du
  palier 1 : il protège du code pas encore écrit.

**Ce n'est pas une table d'audit, c'est un signal métier.** `active → cessee`
date le moment où la société cédante a disparu, donc où le produit de cession
est descendu aux associés : c'est la **date de sortie du prospect**. Le lead ne
s'évanouit pas du classement, il en sort, et on sait quel jour. C'est la seule
question qu'un décompte d'écartés ne peut pas trancher — il dit *combien*,
jamais *depuis quand*.

`sortie_du_flux` est testée sur un cas qui n'en est pas une (`inconnu →
active`) : sans lui, une propriété qui rendrait toujours `True` passerait le
test nominal.

**`ResultatCollecte.transitions` et `.revisions` sont RELUS depuis la base**,
pas accumulés pendant la boucle. Un compteur tenu au vol dirait ce que le code
croit avoir écrit ; la relecture dit ce que la base contient. Les deux devraient
coïncider — c'est justement pour ça qu'il faut lire, sinon on ne le saurait
jamais.

### Palier 5 ✅ — les révisions de fait, et la première migration qui ne peut plus être implicite

`evenement.empreinte` + `evenement_revision`. Un rectificatif du BODACC et une
régression de notre parser produisent le même symptôme : un fait qui n'est plus
celui d'hier. **Écraser rend les deux indistinguables** ; la version remplacée
est la seule trace qui permette de trancher, et `champs_modifies` dit lequel a
bougé — un montant qui change seul ressemble à un rectificatif, un montant qui
s'annule sur des dizaines de lignes le même jour ressemble à un parser cassé.

**L'empreinte ne porte que les colonnes de FAIT.** Les dates de suivi en sont
exclues : elles bougent à chaque passage, et les inclure conclurait à un
changement du fait à chaque recollecte — une révision fantôme par ligne et par
balayage, dans la table même qui doit servir à distinguer un vrai changement.

**`date_collecte` date le FAIT STOCKÉ, `derniere_verification` date le
passage.** Les faire avancer ensemble ferait de la seconde un doublon de la
première, et on prétendrait avoir recollecté une donnée qu'on n'a fait que
reconfirmer.

**Le contenu archivé est un blob JSON, pas treize colonnes miroir.** Une trace
d'audit se lit en entier pour comparer deux versions ; des colonnes miroir
imposeraient une migration à chaque évolution d'`evenement`, alors que cette
table doit survivre à ces évolutions sans les suivre.

**`VERSION_SCHEMA` cesse ici d'être décoratif.** Les versions 1 et 2
n'ajoutaient que des tables, et `IF NOT EXISTS` suffisait. La v3 ajoute une
*colonne*, donc un `ALTER TABLE` — et surtout elle doit **calculer** les
empreintes des lignes existantes. Laisser `''` ferait conclure à un changement
dès la première recollecte : le faux positif de masse décrit ci-dessus.

#### Sept mutations survivantes sur huit — dont trois d'une famille déjà nommée

Balayage passé sur le code des deux paliers : **huit mutations, sept
survivantes au premier passage**, zéro après correction. La huitième
(`sorted(morceaux)`, qui ferait hacher un ensemble non ordonné) était déjà
gardée.

| Mutation | Premier passage | Ce qui manquait |
|---|---|---|
| `_ABSENT` vaut la chaîne `"None"` | **survit** | le test ne couvrait que la chaîne vide |
| `_SEPARATEUR` devient `""` | **survit** | aucun test sur la frontière entre valeurs |
| `transitions()` ignore `depuis` | **survit** | corpus à une seule date |
| `revisions()` ignore `depuis` | **survit** | idem |
| le `motif` du journal porte le statut | **survit** | `motif` n'était asserté nulle part |
| `Ecriture.nouveau` vaut toujours `True` | **survit** | `evenements_nouveaux` non asserté |
| `url_publication` sort de `COLONNES_DE_FAIT` | **survit** | 3 colonnes couvertes sur 13 |
| l'empreinte hache un ensemble non ordonné | détectée | — |

Trois enseignements, dont deux sont des rappels et un est nouveau.

**Rappel — le corpus dégénéré, encore, deux fois.** Les filtres `depuis` ne
pouvaient pas être pris en défaut parce que toutes les transitions du corpus
portaient la même date, et `evenements_nouveaux` ne pouvait pas l'être parce
que le corpus était entièrement neuf : `evenements_ecrits` et
`evenements_nouveaux` y valaient le même nombre. Les nouveaux corpus séparent
les grandeurs — trois balayages à trois dates, et un second passage qui réécrit
une ligne connue en n'en apportant qu'une seule.

**Rappel — un commentaire qui décrit un trou ne le referme pas.** Le
commentaire de `_ABSENT` disait déjà, noir sur blanc, que la mutation avait
survécu et que le cas de la chaîne vide n'était pas celui qu'il protégeait.
Constat juste, laissé tel quel : le test manquant n'avait pas été écrit. **Une
lucidité en commentaire n'est pas un garde-fou** — elle documente la dette, elle
ne la paie pas. Même chose pour la docstring du test de permutation, qui
invoquait encore un préfixe de nom retiré du code deux commits plus tôt : le
chiffre qui survit à sa source, appliqué cette fois à une justification.

**Nouveau — un CHAMP mort échappe à l'audit comme un symbole mort lui
échappait.** `Ecriture` était rendue avec trois champs ; un seul, `nouveau`,
était lu. Les deux autres justifiaient d'éviter à l'appelant de relire la base
— alors que `collecte` la relit, **délibérément**, parce que les journaux
doivent dire ce que la base contient et non ce que le code croit y avoir mis.
La classe étant construite, `tools/symboles_morts.py` la voyait vivante : il
audite des symboles, pas des attributs. C'est la même limite que pour les
branches inatteignables, déplacée d'un cran — et le même remède, l'écrire ici
plutôt que d'élargir l'outil.

**Nouveau — un test qui énumère les cas ne couvre que les cas énumérés.**
`test_chaque_colonne_de_fait_declenche_une_revision` est paramétré sur trois
colonnes. Il a l'air d'un test exhaustif — son nom dit « chaque » — et il en
laissait dix sans garde. Le remède n'est pas d'allonger la liste, qui dériverait
du schéma au premier ajout de colonne : c'est un test **structurel** qui dérive
`COLONNES_DE_FAIT` du `PRAGMA table_info` moins une liste de colonnes de suivi
écrite en clair. Ajouter une colonne au schéma sans la classer dans l'un des
deux camps fait désormais échouer la suite — le classement devient une décision,
plus un oubli.

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