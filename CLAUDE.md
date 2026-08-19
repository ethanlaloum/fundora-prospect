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

#### Les trois familles que l'audit ne voit pas

Elles se sont trouvées une par une, et elles ont la **même cause** : l'outil
ramasse les `ClassDef` et `FunctionDef` de **premier niveau** de `src/`, puis
cherche leur nom en position d'appel. Tout ce qui n'est pas un symbole de
premier niveau lui est invisible, quel que soit son degré de mort.

| Famille | Exemple sur ce projet | Pourquoi invisible |
|---|---|---|
| **Expressions inatteignables** | le repli `INCONNU` de `base_legale` | une branche n'est pas un symbole |
| **Attributs jamais lus** | `Ecriture.revision`, `Ecriture.transition` | la classe est construite, donc vivante |
| **Structures de données** | une table ou une colonne que rien ne lit | hors du langage audité |

Les trois se ressemblent à l'usage : du code qu'on lit, qu'on maintient, qu'on
migre — et que rien n'exécute. Aucune n'est signalée, et **aucune ne le sera** :
voir « on ne corrige pas l'outil », plus bas. Ce qui les rattrape est ailleurs —
la revue, la mutation, et pour les tables la règle « on ne crée que ce qu'on
utilise », qui les empêche d'exister plutôt que de les détecter.

**Famille 1 — les expressions.** Trouvée en Phase 6, par un cas concret.
`provenance.base_legale` s'écrit :

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

**Famille 2 — les attributs.** Trouvée au palier 5, sur `Ecriture`. La classe
était rendue avec trois champs ; **un seul, `nouveau`, était lu**. Les deux
autres se justifiaient par « éviter à l'appelant de relire la base » — alors que
`collecte` la relit délibérément, parce que les journaux doivent dire ce que la
base *contient* et non ce que le code croit y avoir mis. La justification
contredisait le design retenu, et personne ne l'a vu pendant deux commits.

L'audit, lui, ne pouvait pas la voir : `Ecriture(...)` apparaît en position
d'appel, donc la classe est vivante — et l'outil s'arrête là. Il ne descend pas
dans les champs, pas plus qu'il ne descend dans les branches. **Une classe
vivante peut être aux deux tiers morte.**

Le cas est plus insidieux que celui des expressions, parce qu'un champ mort ne
se contente pas de ne rien faire : il **affirme quelque chose**. Un lecteur qui
voit `Ecriture.transition` en conclut que l'appelant s'en sert, et se demande
lequel. C'est de la documentation fausse au format d'un type.

**Famille 3 — les tables et les colonnes.** Écrite au gate de la Phase 6, avant
d'avoir un cas : « une colonne que rien ne lit est de la donnée morte, et
`tools/symboles_morts.py` ne voit pas les colonnes ». C'est la raison pour
laquelle `collecte_ecart` n'a pas été créée et pour laquelle aucune colonne de
score n'existe. Ici la parade n'est pas la détection mais l'abstention : on ne
crée une table qu'au palier qui la lit.

**On ne corrige pas l'outil**, pour aucune des trois. Détecter du code
inatteignable demande une analyse de flux, pas une lecture de noms. Détecter un
attribut jamais lu demande de résoudre les types — or l'outil ne les résout
délibérément pas, et cette tolérance est ce qui l'empêche de crier au loup sur
les homonymes. Détecter une colonne morte demande de lire du SQL en chaînes.
Chacune est un autre outil, avec un autre taux de faux positifs, et la règle
« un audit qui crie au loup est désactivé dans la semaine » s'appliquerait
immédiatement. **Ces limites sont écrites pour qu'on sache où l'audit s'arrête,
pas pour être comblées.**

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
était lu. Voir la troisième famille dans les limites de
`tools/symboles_morts.py`, où les trois angles morts de l'audit sont écrits
ensemble.

**Nouveau — un test qui énumère les cas ne couvre que les cas énumérés.**
`test_chaque_colonne_de_fait_declenche_une_revision` est paramétré sur trois
colonnes. Il a l'air d'un test exhaustif — son nom dit « chaque » — et il en
laissait dix sans garde. Le remède n'est pas d'allonger la liste, qui dériverait
du schéma au premier ajout de colonne : c'est un test **structurel** qui dérive
`COLONNES_DE_FAIT` du `PRAGMA table_info` moins une liste de colonnes de suivi
écrite en clair. Ajouter une colonne au schéma sans la classer dans l'un des
deux camps fait désormais échouer la suite — le classement devient une décision,
plus un oubli.

### Leçon générale : la mutation n'est pas une vérification, c'est l'écriture du test

**C'est la mesure la plus importante du projet, parce qu'elle porte sur la
méthode elle-même et non sur le produit.**

Quatre paliers, quatre passes de mutation. Le chiffre qui compte est celui du
**premier passage** — combien de mutations survivaient avant qu'on corrige quoi
que ce soit :

| Palier | Survivantes au 1ᵉʳ passage | Après correction |
|---|---|---|
| 1 — schéma et porte d'écriture | **2 / 10** | 0 |
| 2 — lecture et recalcul | **0 / 14** | 0 |
| 3 — job de collecte | **1 / 16** | 0 |
| 4-5 — les deux journaux | **7 / 8** | 0 |

**Attention au piège de lecture, qui est le piège signature de ce projet.** Ce
tableau a d'abord été écrit « 0, 0, 0, 7 » — en comparant le chiffre *après
correction* des trois premiers paliers au chiffre *de premier passage* du
quatrième. Deux mesures différentes dans une même colonne. La série ci-dessus
applique la même mesure aux quatre.

**Ce qui a changé entre le palier 3 et le palier 4-5 n'est pas la difficulté du
code, c'est l'ordre des opérations.** Aux paliers 1 à 3, la mutation était
entrelacée avec l'écriture : on altérait l'implémentation à mesure qu'on
écrivait le test, souvent *avant* d'écrire la ligne de production
correspondante — le palier 3 bis en porte la trace explicite (« mutation faite
avant d'écrire la moindre ligne »). Aux paliers 4 et 5, le code et les tests ont
été écrits en entier, verts, et la passe de mutation est venue **ensuite**,
comme une relecture.

Sept sur huit. Le même auteur, la même suite, les mêmes règles déjà écrites dans
ce fichier — et deux des sept trous relevaient de familles nommées dans ce
document même. **Connaître la règle n'a pas suffi.**

L'explication tient en une phrase : *un test écrit après un code vert est écrit
pour confirmer ce que le code fait, pas pour interdire ce qu'il ne doit pas
faire.* On regarde l'implémentation, on assertionne ce qu'on y voit, et on
obtient un test qui décrit fidèlement le comportement courant — y compris ses
défauts. La mutation, elle, pose l'autre question : *que faudrait-il casser pour
que ce test rougisse ?* Posée pendant l'écriture, elle façonne l'assertion.
Posée après, elle ne fait plus que compter les dégâts.

**Règle de travail : aucune passe de mutation « finale ».** Chaque assertion
non triviale se mute au moment où on l'écrit, avant de passer à la suivante. La
passe globale reste utile — c'est elle qui a trouvé les sept — mais elle doit
être un filet, pas la méthode. Quand elle rapporte beaucoup, ce n'est pas une
bonne nouvelle sur sa propre efficacité : c'est le signal qu'on a écrit les
tests dans le mauvais ordre.

**Limite honnête de cette mesure.** Quatre points, des mutations choisies à la
main, et un nombre de mutations qui varie d'un palier à l'autre (8 à 16) —
ce n'est pas un protocole, c'est un faisceau. Il est écrit ici parce qu'aucune
autre trace du projet ne dit si sa méthode marche, et qu'un faisceau mesuré
vaut mieux qu'une conviction.

### Étape 2 ✅ — `api.py`, la surface web

Cinq routes, **126 lignes de code contre 172 pour `mcp_server`** : FastAPI
absorbe nativement la validation que l'autre surface fait à la main.

| Route | Rend |
|---|---|
| `GET /leads` | la sortie produit, même forme que `search_liquidity_events` |
| `GET /evenements/{id}` | un cas, **écarté compris**, avec révisions et transitions |
| `GET /collecte` | ce que la base sait, et quand elle a regardé |
| `GET /sorties` | les cédants qui ont cessé, datés |
| `POST /hypotheses` | le score d'une cession décrite à la main |

**Aucune route ne touche au réseau.** Le job collecte, l'API relit. Une route
d'enrichissement rouvrirait un appel API dans le temps de réponse — exactement
ce que la base a été créée pour supprimer.

**`127.0.0.1`, et ce n'est pas du confort.** Cette surface sert
`cedant_denomination`, qui *est* un nom de personne sur ~20 % des cédants
(contrainte 4). Le fichier SQLite vit déjà hors du dépôt pour cette raison ;
l'exposer annulerait la décision d'un cran plus loin. `HOTE_DEFAUT` n'est pas
surchargeable : le rendre configurable ferait de l'exposition un réglage.

**Une connexion par requête.** Les connexions `sqlite3` ne traversent pas les
threads et FastAPI exécute les routes synchrones dans un pool.

#### Les trois tests qui ne peuvent exister qu'entre deux surfaces

C'est la leçon du palier 2 — `motif_ecart_faits` comparé sur ses deux chemins —
appliquée cette fois entre deux façades. **Aucun test d'une surface isolée ne
peut voir une divergence :** chacune est verte avec son propre vocabulaire.

1. **Les clés d'enveloppe, les motifs de refus et le breakdown** sont comparés
   entre `/leads` et `search_liquidity_events` sur le même corpus. Les
   *populations*, elles, ne sont jamais comparées — elles diffèrent par
   construction et c'est documenté juste en dessous.
2. **La provenance ne peut pas sortir de la porte unique.** Le contrôle porte
   sur le **graphe d'appel** et non sur la réponse : une assertion sur la sortie
   ne distingue pas un lead sérialisé d'un lead monté à la main qui lui
   ressemble — c'est précisément le défaut de la Phase 3 bis. Un test lit l'AST
   de `api.py` et vérifie qu'il n'importe pas `provenance` et n'appelle ni
   `serialiser` ni `assembler`. L'analyse est syntaxique parce qu'une recherche
   textuelle du mot interdirait d'en parler dans les commentaires.
3. **`/hypotheses` et `score_lead` rendent la MÊME valeur**, pas la même forme.
   La mise en forme a été extraite dans `models.presenter_evaluation` — elle
   existait déjà en double entre `provenance.serialiser` et l'outil MCP, et une
   troisième copie allait naître.

**Sur cette surface, `provenance incomplete` est impossible par construction**,
et c'est le schéma qui le garantit, pas la route : le `CHECK` du palier 1 refuse
une URL non absolue à l'écriture. Prouvé plutôt que déduit — « devrait valoir
zéro » est la formule qui a produit tous les défauts de ce projet.

#### Un faux ami en test : substituer la dépendance de connexion

La première version des tests substituait `api.connexion` par une connexion de
fixture. Échec immédiat, et **pour la bonne raison** : `TestClient` exécute les
routes dans un thread de travail, la connexion venait du thread du test, SQLite
refuse. C'est exactement le bug que la dépendance évite en production.

Le réflexe aurait été de contourner — et la dépendance, seule chose qui gère le
cycle de vie des connexions, n'aurait jamais été exercée. Les tests passent donc
par `FUNDORA_DB` et laissent tourner le vrai code.

Les deux défauts trouvés en écrivant cette surface ont donné deux leçons
générales, écrites plus bas : **le nombre de décisions plutôt que le nombre de
lignes**, et **le défaut dont le symptôme est plausible**.

#### L'enveloppe reste montée deux fois, et c'est délibéré

`/leads` et `search_liquidity_events` construisent chacun leur dict de sept
clés. Partager le constructeur exigerait de faire porter `departements`,
`debut` et `fin` par `ResultatLecture` — trois champs traversant le cœur pour
de la seule mise en forme, c'est-à-dire **l'inverse du mouvement de l'étape 1**,
qui a fait descendre la logique du transport vers le cœur.

Ce qui garde les deux enveloppes égales est le test de comparaison. Si une
troisième surface arrive, **c'est le test qu'on étend, pas le modèle qu'on
alourdit.**

À ne pas confondre avec `presenter_evaluation`, extrait au même moment : là il
s'agissait d'une *logique* de mise en forme dupliquée à l'identique, pas d'un
contexte que chaque surface connaît déjà.

#### `symboles_morts` gagne une quatrième justification

L'audit signalait `Hypothese` — jamais construite par nous, seulement annotée.
C'est FastAPI qui la construit à chaque requête, la même situation que
`@serveur.tool` un cran plus loin : le framework construit non pas la fonction
mais **son argument**.

L'exemption est étroite et ne contredit pas la règle « une annotation n'est pas
un usage » : ce qui justifie n'est pas l'annotation, c'est d'annoter le
paramètre d'une fonction **enregistrée par un décorateur**. Sans enregistrement,
l'annotation ne vaut toujours rien — et un décorateur *inerte* (`@cache`,
`@dataclass`) ne compte pas davantage ici qu'ailleurs. Les deux moitiés sont
testées, parce qu'une exemption dont on ne teste que le côté permissif finit par
tout justifier.

Coût assumé : une voie de plus vers le silence. L'alternative — inscrire
`Hypothese` dans une liste blanche — fait grossir une liste que personne ne
relit.

#### Treize mutations, zéro survivante

Écrites **pendant** les tests et non après, conformément à la leçon des paliers
4-5. Huit sur les routes (clé d'enveloppe renommée, `montant_min` ignoré,
compteurs de collecte non passés, `limite` ignorée, fenêtre ignorée,
`/hypotheses` remontant sa propre mise en forme, 404 transformé en 200, `sorties`
rendant toutes les bascules), une sur la porte de provenance (`classer` montant
son dict à la main — neuf tests rougissent, dont ceux des deux surfaces), une
sur le garde `siren`, deux sur la nouvelle règle de l'audit, une sur `api.py`
important `provenance`.

### Leçon générale : ce qui décide, c'est le nombre de décisions — pas le nombre de lignes

**Règle de ce projet, en vigueur : dans une surface (`api.py`, `mcp_server.py`),
une route ou un outil peut être long ; il ne peut pas décider.** On compte les
branches, pas les lignes. La longueur reste utile — elle déclenche une
relecture — mais elle ne rend plus de verdict.

Le garde-fou précédent disait « si le corps d'une route dépasse une dizaine de
lignes, c'est de la logique qui a quitté le cœur ». Il a été mesuré et retiré.

Le cas qui l'a produit : **`GET /leads` fait 17 lignes et prend zéro décision.**

| Route | Lignes | Décisions | Lignes de littéral dict |
|---|---|---|---|
| `leads` | 17 | **0** | 9 |
| `evenement` | 14 | 5 | 8 |
| `collecte` | 7 | 1 | 5 |
| `sorties` | 6 | 2 | 5 |
| `hypothese` | 1 | 0 | 0 |

Trois affectations, un appel au cœur, une enveloppe de neuf lignes. Le seuil
mesurait la **taille de la réponse**, ce qui n'a aucun rapport avec la question
posée. Une route qui assemble un gros dict reste une route ; une route qui teste
trois conditions commence à juger.

**Ce que le seuil a quand même produit de bon** : il a forcé à regarder
`evenement`, le seul à brancher — et c'est là qu'un vrai défaut attendait (voir
la leçon suivante). Un mauvais critère qui déclenche la bonne relecture vaut
mieux que pas de critère ; il ne vaut pas d'être conservé comme verdict.

La règle générale derrière : **un proxy facile à mesurer se substitue à la
propriété qu'on visait**, et il finit par être appliqué pour lui-même. C'est le
mécanisme des six visages — « ce qui est facile à vérifier se substitue à ce qui
compte » — appliqué cette fois non à une assertion mais à une règle de revue.

### Leçon générale : un défaut dont le symptôme est plausible

Trouvé en Phase 6 étape 2, sur une branche d'une seule ligne :

```python
"transitions": [_transition(t) for t in entrepot.transitions(base, siren=siren)]
if siren
else [],
```

Sans le `if siren`, `entrepot.transitions(base, siren=None)` **retire le
filtre** et rend le journal entier. La fiche d'un événement sans cédant
identifié afficherait donc les changements de statut de *toutes* les sociétés de
la base, présentés comme les siens.

**Ce n'est pas un des six visages.** Les six décrivent des tests aveugles — une
assertion qui passe pour une raison sans rapport avec ce qu'elle prétend garder.
Ici l'assertion manquait, simplement. Ce qui rend le cas intéressant est
ailleurs : **la sortie fautive est plus crédible que la sortie correcte.**

| | Ce que ça donne | Comment ça se lit |
|---|---|---|
| Comportement correct | `"transitions": []` | un champ vide — **se voit** |
| Comportement fautif | trois transitions datées | un fait — **se lit** |

Un champ vide interpelle : on se demande pourquoi. Un rattachement erroné ne
demande rien, il informe. **Dans une fiche d'audit, une attribution fausse est
pire qu'une absence**, parce que l'absence déclenche une vérification et que le
faux fait la remplace.

Deux conséquences de méthode :

1. **Une API dont un paramètre absent signifie « tout » est un piège au point
   d'appel.** `transitions(siren=None)` est légitime pour `/sorties`, qui veut
   effectivement tout ; il est dangereux partout où le siren est optionnel. Le
   garde appartient à l'appelant, et il doit être testé chez l'appelant.
2. **Le corpus du test doit contenir de quoi être mal attribué.** Une base
   sans aucune transition rendrait `[]` dans les deux cas — corpus dégénéré, une
   fois de plus. Le test fait donc basculer une société *et* interroge un
   événement sans siren : la version fautive rend une liste non vide, la
   correcte rend `[]`.

Le signal à surveiller, plus large que ce cas : **quand une valeur par défaut
veut dire « pas de filtre », le mode dégradé n'est pas l'absence, c'est
l'excès** — et l'excès ressemble à un résultat.

## Phase 7 — le front web

Contrainte structurante : **le front n'affiche que ce que l'API rend.** Il ne
recalcule ni score, ni compteur, ni motif. Se retrouver à réimplémenter de la
logique en JavaScript est le signal qu'une route ne rend pas assez — pas une
invitation à la coder deux fois.

### La frontière : le front connaît des CLÉS, jamais des VALEURS

Sans cette ligne, « aucune donnée en dur » devient inapplicable : afficher quoi
que ce soit exige de nommer quelque chose.

- **Autorisé** — `lead.score`, `statistiques.annonces_publiees`, le chemin
  `/leads`, `type_cedant === "pp"` pour choisir une classe CSS. Ce sont des
  liaisons *structurelles*, du même ordre que connaître l'URL d'une route.
- **Interdit** — `"apport"`, `"sous le montant minimum"`, `"personne
  physique"`, `"fraîcheur"`, tout seuil, tout poids. Ce sont des *valeurs* :
  elles viennent de l'API ou n'existent pas.

### Étape 1 ✅ — ce que le front a révélé de manquant dans le cœur

Trois manques et un défaut, trouvés **avant** d'écrire une ligne de front — en
lisant une vraie réponse plutôt qu'en imaginant l'écran.

#### Le défaut : un motif de config tronqué en plein milieu de phrase

`scoring.py` rendait `grille.departement.motif.splitlines()[0]` — la première
ligne **physique** du bloc TOML, c'est-à-dire un retour à la ligne de mise en
page. Le motif s'arrêtait sur « rien ne justifie de ».

C'est la contrainte 5 en défaut : un motif coupé n'explique rien, et c'est
précisément le « pourquoi zéro » qu'un breakdown doit donner. Le test en place
disait `assert contribution.motif` — présence seule, encore une fois, et c'est
par là que la troncature est passée.

**Règle : un motif est un texte, il sort entier.** Si un affichage a besoin
d'une version courte, c'est un second champ nommé, jamais un découpage
silencieux. Deux tests le gardent : le cas connu, et un **garde générique** —
citer le début d'un motif de config oblige à le citer en entier, pour tous les
critères présents et à venir. Trois mutations (`splitlines()[0]`, `[:80]`,
`split('.')[0]`), trois détectées.

#### Manque 1 : les écartés n'étaient pas listables

`/leads` ne rendait que des *comptes* par motif. `/evenements/{id}` montre un
écarté, mais aucune route ne donnait les ids des écartés — donc rien à cliquer.
L'auditabilité s'arrêtait au comptage : on savait qu'il y avait 23 sociétés
cédantes cessées, on ne pouvait pas dire lesquelles.

`GET /ecartes?departement=…&motif=…&limite=…`, et un changement de fond dans le
cœur : **`classer` collecte des paires `(événement, motif)` au lieu
d'incrémenter un dict, et les comptes en dérivent.** Une source au lieu de deux.
Avant, la liste et le décompte auraient pu se contredire ; maintenant ils ne le
peuvent pas, et un test le vérifie motif par motif.

**Un écarté n'est pas un lead, et sa forme l'interdit** : ni `score`, ni bloc
`provenance`, ni `breakdown`. Lui donner la forme d'un lead rouvrirait un second
chemin par lequel quelque chose ressemblant à un lead quitte le système sans
passer par `provenance.serialiser` — le défaut de la Phase 3 bis, réintroduit
par une route d'audit. `url_publication` y reste : c'est ce qui rend le refus
vérifiable par un tiers.

#### Manque 2 : la fraîcheur n'existait qu'en prose

Le nombre de jours vivait uniquement dans le texte du motif. Une surface voulant
l'afficher devait soit le recalculer — second calcul, donc divergence — soit
chercher le critère par son nom, donc recopier un mot du domaine.
`Evaluation.jours_ecoules` et `date_reference` sont désormais calculés **une
fois**, par `evaluer`, et recopiés par `serialiser`. Le test croise les deux
présentations : le nombre en donnée doit être celui que la prose annonce.

#### Manque 3 : `type_cedant` valait `"pm"` / `"pp"`

`TypeCedant.libelle` est la source unique du libellé, et `serialiser` rend
`type_cedant_libelle`. Le segment personne physique relève d'une base légale
distincte — cette distinction ne doit pas dépendre d'une table de
correspondance écrite dans une surface. Trois segments, trois textes, et un
test qui échoue si deux d'entre eux se confondent.

#### `/ecartes` est la troisième surface à nommer ces refus

Elle passe par le même `pipeline.lire` que `/leads`, donc les motifs y sont les
mêmes objets. Mais c'est vrai *aujourd'hui*, pas par construction : le jour où
quelqu'un lui donne son propre parcours « pour aller plus vite », seule une
comparaison le verra. Même test qu'entre MCP et API, appliqué une troisième
fois.

Onze mutations, zéro survivante. Une d'elles n'a pas pris — mauvaise ancre — et
son « tout vert » ne prouvait rien : **une mutation qui ne s'applique pas est
une mutation non jouée**, à distinguer d'une survivante. Rejouée avec la bonne
ancre, elle est détectée.

### Étape 2 ✅ — le socle web, et deux outils versionnés

`web/` : Vite + React + TypeScript, proxy `/api` vers `127.0.0.1:8000`, CSS
simple. **Écran vide qui compile** — les filtres, les compteurs et la liste
arrivent à l'étape 3.

#### `tools/muter.py` — l'outil de mutation cesse d'être un script jetable

La mutation est la méthode de vérification centrale de ce projet, et elle était
jouée par des scripts shell réécrits à chaque fois. L'un d'eux a produit
exactement le défaut que ce document décrit ailleurs : **une ancre mal indentée,
donc une mutation jamais appliquée, et un « 595 passed » qui ressemblait à une
survivante.**

Trois issues désormais, et il en faut trois :

| Issue | Ce qui s'est passé | Verdict |
|---|---|---|
| `NON APPLIQUEE` | ancre absente, ambiguë, ou remplacement identique | **erreur d'outil** |
| `SURVIVANTE` | le code a changé, la suite reste verte | **trou de test** |
| `DETECTEE` | le code a changé, la suite rougit | attendu |

Les deux premières font échouer le lot pour des raisons **opposées** : l'une dit
que la mesure n'a pas eu lieu, l'autre qu'elle a eu lieu et qu'elle est
mauvaise. Les confondre, c'est croire mesurer quand on ne mesure rien. C'est la
limite anticipée pour `symboles_morts.py` et pas vue pour l'outil de mutation
lui-même.

**Un second défaut, trouvé en s'en servant : l'outil était muet.** Il
n'imprimait qu'à la fin, après cinq lancements de la suite complète. Plusieurs
minutes sans une ligne — indistinguable d'un blocage, et tué avant d'avoir fini.
Chaque verdict est maintenant publié au fil de l'eau avec son temps écoulé.
*Un outil silencieux pendant qu'il travaille finit par ne plus être lancé*,
exactement comme un audit qui crie au loup finit désactivé.

#### `tools/exporter_types.py` — les types du front, générés

Trois façons de typer les réponses côté front, deux mauvaises :

- **à la main** — une copie du modèle Python qui dérivera ;
- **depuis l'OpenAPI** — inutilisable : les routes rendent `dict[str, Any]`,
  donc le schéma dit `{"type": "object"}`. Y remédier demanderait des modèles
  Pydantic de réponse, c'est-à-dire recopier la forme de `serialiser` ailleurs ;
- **depuis des réponses réelles**, retenu. `tests/test_types_web.py` régénère et
  échoue si le fichier est périmé — même mécanique que l'exemple de `SKILL.md`.

**Le contrôle du corpus dégénéré, et ce qu'il a trouvé sur lui-même.** Un type
déduit d'un corpus qui n'exerce pas un champ est faux exactement comme une
assertion l'était. À sa première exécution, le contrôle a signalé **sept
champs** : le second balayage du corpus faisait cesser *toutes* les sociétés, et
le seul lead restant était celui sans SIREN — donc `siren`, `code_ape`,
`section_ape` et `lead` sortaient typés `null`.

Deux formes de dégénérescence, et il faut les deux : un champ toujours `null`,
et un tableau toujours vide — dans les deux cas le corpus n'a rien appris.

**La limite, écrite parce qu'elle est réelle :** le contrôle voit les champs
*toujours* nuls, pas les champs *jamais* nuls. Un champ nullable dans la réalité
mais renseigné partout dans le corpus sortira non-nullable, et rien ne le dira.
C'est au corpus d'exercer la nullabilité là où elle existe — d'où l'annonce
`PETIT`, écartée *et* sans acte datable *et* sans SIREN.

**`statistiques.ecartes` sort en `Record<string, number>`.** En déduire un champ
par motif écrirait les libellés de refus dans le fichier généré, donc dans
`web/src` — la duplication que le front s'interdit. Le verrou de vocabulaire
sert de filet, puisqu'il balaye aussi le fichier généré.

#### Le verrou de vocabulaire, et sa friction immédiate

`tests/test_front_sans_vocabulaire.py` balaye **tout `web/src`** — composants,
constantes, styles, types générés — et le vocabulaire interdit est **dérivé du
cœur en le faisant tourner**, jamais recopié : chaque qualification via
`motif_ecart_faits`, les refus de statut via `classer`, les libellés via
`TypeCedant`. Un motif ajouté demain est couvert le jour même.

Les frontières de mots comptent : sans elles « apport » serait trouvé dans
« rapport ». Avec elles, « apport en nature » est bien signalé — il *contient*
le mot.

**Il a mordu deux fois en deux minutes, sur du français ordinaire.** D'abord
`main.tsx`, qui disait « element #racine **absent** de index.html » — un message
d'erreur banal, mais « absent » est un motif du cœur (`Qualification.ABSENT`).
Puis, après reformulation, **sur le commentaire qui expliquait pourquoi éviter
ce mot**, lequel contenait le mot.

Choix retenu : **reformuler le front, pas affaiblir le verrou.** Restreindre le
balayage aux chaînes affichables n'aurait d'ailleurs pas aidé — le message était
dans une chaîne.

C'est un compromis, pas une évidence, et sa limite est connue : *un audit qui
crie au loup est désactivé dans la semaine*. Le signal à surveiller est le
nombre de reformulations subies pour lui plaire. S'il grandit, la bonne réponse
ne sera pas de tolérer des exceptions une à une, mais de retirer du vocabulaire
les motifs d'un seul mot courant — en assumant qu'ils ne sont plus gardés.

#### Un paramètre plutôt qu'une globale substituée

Les tests de dents remplaçaient le répertoire balayé par `monkeypatch` sur une
globale. Ça ne marchait pas — pytest importe le module sous un nom, le patch en
visait un autre — et **les tests de dents échouaient en silence sur un
répertoire vide**. Le répertoire est devenu un paramètre : même raison que
`rechercher` et `enrichir` dans le cœur, et un paramètre ne peut pas rater sa
cible.

Cinq mutations, cinq détectées, dont le cas demandé — `apport en nature` inséré
dans le JSX fait rougir le verrou.

### Étape 3 ✅ — l'écran : filtres, compteurs, liste, dépliage

`GET /leads` et rien d'autre. Un formulaire, une bande de compteurs, une liste
de fiches dépliables portant le détail du calcul et la provenance.

Lancement, deux commandes :

```sh
PYTHONPATH="$PWD/src" .venv/bin/python -m fundora_prospect.api   # 127.0.0.1:8000
cd web && npm run dev                                            # proxy /api
```

#### Le front ne connaît AUCUN défaut, et c'est ce qui l'empêche de dériver

Les quatre champs de filtre partent **vides**, et un champ vide n'est pas
envoyé. La première requête ne porte donc aucun paramètre : c'est le cœur qui
décide de la région, de la fenêtre et de la limite, et l'écran affiche ce qu'il
a décidé — `departements`, `periode`, `montant_min_eur` viennent de la
**réponse**, jamais des filtres saisis.

Même chose pour les bornes : pas de `min`/`max` sur les `<input>`. `MOIS_MAX` et
`LIMITE_MAX` vivent dans le cœur ; les recopier en attributs HTML serait écrire
des seuils dans le front. Le front envoie ce qu'on saisit et **affiche le refus**
de l'API tel qu'il vient — un 422 et son `detail`, qui dit déjà la forme
attendue. Une borne refusée par le serveur ne peut pas diverger de lui.

#### Tout libellé affiché est une CLEF, prettifiée

`libelle(cle)` remplace les tirets bas par des espaces, et c'est tout. Aucune
table `annonces_publiees -> "Annonces publiées au BODACC"` : elle serait une
valeur écrite dans le front, donc une copie du vocabulaire du cœur, donc une
divergence à venir.

Conséquence assumée : les colonnes portent le nom du champ de l'API qui les
alimente. C'est un peu brut, et c'est exactement ce qu'on veut sur un outil
d'audit — le lecteur voit quel champ il regarde.

Le composant des compteurs **n'énumère rien** : il parcourt `statistiques` et
rend ce qu'il y trouve. Un compteur ajouté au cœur apparaît sans qu'une ligne de
front change, et surtout il **ne peut pas manquer** faute d'avoir été prévu.
Les deux réserves (`collecte_partielle`, `plafond_atteint`) ne sont montrées que
vraies — une mise en garde permanente cesse d'être lue.

#### Le second verrou : `tests/test_front_ne_recalcule_rien.py`

Le verrou de vocabulaire garde ce que le front **dit**. Celui-ci garde ce qu'il
**fait**. Deux règles :

1. **Aucune arithmétique sur un champ numérique de l'API.** La liste de ces
   champs est lue dans `web/src/api/schema.d.ts` — donc dérivée d'un fichier
   lui-même généré depuis des réponses réelles. Un champ numérique ajouté demain
   est couvert le jour où le schéma est régénéré.
2. **Aucun `.length`.** Compter est un calcul. Toute grandeur affichable doit
   venir d'un compteur rendu par l'API ; si elle n'existe pas, c'est une route
   qui ne rend pas assez. La règle est volontairement brutale : un `.length`
   légitime est indiscernable à la lecture d'un `.length` qui remplace un
   compteur — et c'est le défaut « le compteur décrit un budget, pas une
   population », réintroduit dans une autre langue.

Les commentaires sont **retirés avant le balayage**, contrairement au verrou de
vocabulaire qui les inclut délibérément. Les deux propriétés diffèrent : un
libellé recopié dans un commentaire finira recopié dans une chaîne, mais **un
commentaire ne calcule pas**. Le laisser coûterait des faux positifs immédiats
— `// montant_eur ...` est déjà un `/` suivi d'un nom de champ.

**Le verrou a mordu deux fois, et les deux fois le front a cédé.**

| Ce qu'il a refusé | Ce qu'on a fait |
|---|---|
| `colSpan={COLONNES.length}` dans un `<table>` | liste de fiches en grille CSS, sans `colSpan` |
| `.cellule-montant_eur` — un `-` devant un nom de champ | convention BEM `.cellule__montant_eur` |

Le second cas est un faux positif au sens strict : `-montant_eur` dans un
sélecteur CSS n'est pas une soustraction. Mais les distinguer demanderait de
savoir lire le CSS et le JS, pas de chercher un motif — c'est la même limite que
`symboles_morts.py`, qui lit des noms et ne résout pas les types. Deux
reformulations, dont une convention de nommage courante : le compteur de
frictions reste bas, et c'est **lui** le signal à surveiller.

**La limite, écrite parce qu'elle est réelle.** Le verrou voit les accès
**nommés** : `lead.montant_eur / 1000` est attrapé, `lead[cle] / 1000` ne l'est
pas. Or les composants accèdent aux champs par clef dynamique. Ce qui rattrape
ce trou n'est pas le balayage, c'est que toute la mise en forme passe par un
module unique — et que ce module, lui, s'exécute sous test.

#### Les premiers tests du front qui EXÉCUTENT du code

Les deux verrous sont des balayages : ils lisent, ils n'exécutent pas. Une date
permutée, un arrondi qui mange un chiffre, une unité collée au mauvais champ
passeraient tous les contrôles — le code serait conforme à toutes les règles et
mentirait à l'écran.

Le front n'a pas de lanceur de tests, et en installer un demanderait un aller
sur le réseau. **Node exécute du TypeScript en retirant les types**, et les deux
modules porteurs de logique — `format.ts` et `api/client.ts` — sont purs : pas
de DOM, pas de React, et `fetch` est une globale donc remplaçable. Ils
s'exécutent tels quels, sans dépendance.

C'est la raison d'avoir tenu la logique **hors** des composants. Un composant se
vérifie avec un navigateur ; une fonction pure se vérifie avec `node`. Ce qui
reste non couvert est le rendu JSX, et c'est dit franchement : c'est le coût
assumé de ne pas installer de navigateur d'essai, et la raison de garder les
composants sans décision.

Le harnais lui-même est éprouvé : `tests/test_front_execute.py` recopie un
module, y applique une altération **plausible** — une date bien formée mais
fausse, une requête valide mais surchargée — et exige l'échec. Un lanceur qui
rendrait toujours zéro passerait pour un test vert.

#### `web/node_modules` a fait passer la suite de 6 s à plus de 15 minutes

`tests/test_plugin.py` copie le dépôt pour simuler une installation tierce.
`copytree` ne connaît que les motifs qu'on lui donne : `node_modules` — 66 Mo,
des milliers de fichiers — y est entré avec le front, cinq fois par exécution.

Le symptôme ressemblait à un blocage : aucune sortie, un processus à 0,02 s de
CPU, et la suite qui n'arrivait jamais au bout. Il a fallu bisecter fichier par
fichier pour le nommer.

**Ce n'est pas seulement un désagrément : une suite lente rend impraticable la
mutation**, qui est la méthode de vérification centrale de ce projet — une passe
de dix mutations coûte dix exécutions complètes. Le ralentissement n'aurait pas
cassé un test, il aurait cassé la méthode. C'est le même mécanisme que « un outil
silencieux pendant qu'il travaille finit par ne plus être lancé », appliqué cette
fois à la suite elle-même.

La correction n'est pas seulement d'allonger la liste des motifs ignorés — elle
dériverait au prochain artefact. Un **plafond de fichiers** fait désormais
échouer la copie en nommant le répertoire coupable. Ce qui ne se déclare pas se
lit comme un résultat ; ici, ce qui ne se déclarait pas se lisait comme un
blocage.

#### Un test de dents dont le corpus se déduit du paramètre gardé ne garde rien

Le plafond est arrivé avec son test de dents : fabriquer une arborescence trop
fournie et exiger l'échec. Il fabriquait `PLAFOND_DE_FICHIERS + 1` fichiers.

**La mutation « plafond porté à 500 000 » a survécu** — le test fabriquait alors
500 001 fichiers et dépassait encore. Il ne pouvait prendre en défaut **aucune**
valeur de la constante qu'il prétendait garder.

C'est le corpus dégénéré du projet, appliqué à un paramètre : *un corpus qui se
recalcule depuis la chose gardée s'adapte à toutes ses valeurs.* Le nombre est
désormais écrit en clair (`FICHIERS_FABRIQUES = 600`), ce qui a un effet
volontaire : relever le plafond au-delà casse le test, donc devient une décision
argumentée et non le réflexe de quelqu'un que la garde dérange.

Détail qui mérite d'être noté : **la durée était le symptôme**. Cette mutation a
mis 158 secondes là où les dix autres en prenaient 7 — parce que le plafond
relevé laissait `node_modules` revenir dans les copies. Le verdict disait
« survivante » ; le chronomètre disait pourquoi.

#### Douze mutations, une survivante au premier passage

| Mutation | Premier passage |
|---|---|
| un motif de refus recopié dans le front | détectée |
| un compteur de l'API remplacé par un `.length` | détectée |
| une division sur un montant rendu par l'API | détectée |
| le verrou ne connaît plus que l'addition | détectée |
| le retrait des commentaires rase tout le fichier | détectée |
| une date permutée | détectée |
| l'unité collée au mauvais champ | détectée |
| le score arrondi à l'entier | détectée |
| les filtres vides sont envoyés quand même | détectée |
| le refus de l'API est reformulé par le front | détectée |
| les artefacts d'outillage rentrent dans la copie du plugin | détectée |
| **le plafond de fichiers est désactivé** | **survivante** |

La survivante est fermée et rejouée : détectée. Elle est arrivée exactement là où
la leçon des paliers 4-5 le prédit — sur le seul garde écrit **après** coup, en
passant, pendant qu'on réparait autre chose.

### Étape 4 — le site complet, route par route

Trois routes à brancher, dans cet ordre : `/ecartes`, `/evenements/{id}`,
`/sorties`. Arrêt après chacune pour la regarder à l'écran.

#### Route 1 ✅ — `/ecartes` : les pastilles de motif deviennent des filtres

Cliquer un motif charge les cas qui le portent. **Le front propose donc un
filtre sur un vocabulaire qu'il ne connaît pas** : la clef vient de
`statistiques.ecartes`, elle repart telle quelle en paramètre. Il fait le
facteur, pas l'auteur.

Ce que ça débloque : l'auditabilité s'arrêtait au comptage. On lisait qu'un
motif avait refusé 129 dossiers, on ne pouvait pas dire lesquels. Mesuré sur la
base réelle (06, 12 mois) : `129 correspondants`, `25 rendus`.

**Un écarté n'a pas la forme d'un lead, et ce n'est pas l'affichage qui le
garantit — c'est l'API.** Elle ne rend ni `score`, ni `provenance`, ni
`breakdown`, donc le rendu générique ne peut pas les inventer. Le composant
enfonce le clou avec une mise en forme différente : une fiche de faits, sans
rang ni dépliage, là où un lead est une ligne classée. Lui donner l'allure d'un
lead rouvrirait le chemin par lequel quelque chose ressemblant à un lead sort
sans passer par `provenance.serialiser` — le défaut de la Phase 3 bis, revenu
par une route d'audit.

**Les deux nombres sont déclarés côte à côte** — `correspondants` et `rendus`,
tous deux rendus par l'API. Les recalculer depuis la liste donnerait le second
et jamais le premier : une coupe qui ne se déclare pas se lit comme un résultat.

**Deux chargements séparés, deux erreurs séparées.** Compter les refus et les
lister sont deux questions, et la seconde ne se pose qu'au clic. Un échec sur la
liste ne doit pas vider l'écran de son résumé et de ses compteurs — c'est-à-dire
de ce qui permettait de comprendre ce qui se passe.

#### Le segment `pp` visible, et une fonction pure pour qu'il soit testable

La distinction de base légale se voit désormais sur un lead comme sur un refus.
La classe est composée à partir du **code** rendu par l'API ; le libellé, lui,
continue d'arriver par `type_cedant_libelle` et de s'afficher tel quel.

L'expression aurait pu vivre dans le JSX. Elle est dans `format.ts` parce que
**là elle s'exécute sous test** : `classeSegment("pp") !== classeSegment("pm")`
est une assertion, une classe montée en ligne dans un composant n'aurait été
gardée par rien. La mutation « les deux segments reçoivent la même classe » est
détectée.

**La limite est écrite : le point d'appel reste non gardé.** Passer une
constante au lieu du champ du lead ferait disparaître la distinction sans
qu'aucun test ne rougisse. C'est le trou irréductible du JSX non testé, et le
remède partiel est de n'y laisser que des appels d'une ligne.

#### Le verrou de vocabulaire a mordu deux fois de plus — toujours dans de la prose

Six reformulations depuis l'étape 2, et le décompte est le signal à surveiller :

| Où | Ce qui contenait un motif du cœur |
|---|---|
| `main.tsx` | un message d'erreur ordinaire |
| le commentaire qui expliquait ce message | le mot qu'il disait d'éviter |
| `styles.css`, définition de couleur | le commentaire nommant le segment |
| `styles.css`, règle du segment | le commentaire l'expliquant |

**Aucune des six n'était un libellé affiché.** Toutes étaient de la prose *sur*
le code — commentaires et messages techniques. C'est une information sur le
verrou : il coûte des reformulations là où il ne protège rien de visible.

Il ne s'ensuit pas qu'il faille le restreindre au texte affichable. La mutation
« un motif de refus écrit dans la liste des écartés » — un vrai libellé, dans du
JSX rendu — est détectée par lui et par lui seul. Le coût est dans la prose, la
garantie est dans l'affichage, et on ne peut pas avoir la seconde sans le
premier tant que le balayage est textuel. Ce qui ferait basculer la décision est
un compteur qui s'emballe, pas son existence.

Six mutations, six détectées.

#### Route 2 ✅ — `/evenements/{id}` : la fiche d'un cas

Ouverte depuis un lead déplié ou depuis un refus. Elle montre le détail du
calcul **ou** les faits du refus, les révisions de l'annonce, et les transitions
de statut du cédant.

##### Le lead ne portait pas son identifiant, l'écarté oui

`presenter_ecarte` rendait `id` depuis toujours, `serialiser` non. Un refus était
donc consultable en détail, un lead retenu ne l'était pas — asymétrie que
personne n'avait vue parce qu'aucune surface n'avait encore eu besoin de faire
un lien. **Le front l'a révélée en cherchant quoi mettre dans un `href`.**

Un test compare désormais les deux vues : un lead et un écarté doivent désigner
le même événement sous le même nom. Deux mappeurs séparés finissent par diverger,
et seule leur comparaison le voit.

##### `motif_ecart` est devenu `ecarte`, et ce n'est pas un renommage

La fiche d'un refus ne rendait qu'une chaîne. Le lecteur y voyait « apport » et
n'avait **aucun moyen d'aller vérifier** : ni cédant, ni montant, ni
`url_publication`. Un motif seul n'est pas auditable — c'est une affirmation.

Elle rend maintenant la même vue que `/ecartes`, montée par la même
`presenter_ecarte`, et le test compare les deux : la fiche et la ligne de liste
doivent être identiques pour le même événement. Le motif y figure **une fois** —
deux champs le portant seraient deux sources.

L'invariant est verrouillé dans les deux sens, sur les deux cas : **exactement
un de `lead` et `ecarte` est renseigné.** Les deux nuls laisseraient une fiche
muette sans que rien ne le signale ; les deux renseignés feraient coexister à
l'écran un prospect et son refus.

##### La branche `if siren` rendue visible : le journal dit à qui il se rapporte

`transitions` arrive vide dans deux situations sans rapport — le cédant n'a
jamais changé de statut, ou **aucun cédant n'est identifié**. Le front ne peut
pas les distinguer, et n'a pas à le faire : il affiche le SIREN auquel le journal
se rapporte, juste sous le titre de la section, **y compris quand la section est
vide** — c'est là qu'il porte l'information. Un tiret cadratin à cette place dit
tout.

Vérifié sur la base réelle : `A20260112167`, un écarté sans SIREN, rend
`siren: null` et `transitions: []`. La mutation qui retire le `if siren` est
détectée.

##### Le générateur de types : deux objets séparés par un `null` ne fusionnaient jamais

Trouvé en enrichissant le corpus de `/evenements`. `lead` valait un objet, puis
`null`, puis `null`, puis un autre objet. Chaque fusion voyait des genres
différents, empilait un membre de plus, et **les deux objets ne se rencontraient
jamais** : le type devenait `null | {…} | {…}`, deux formes pour un même champ.

**Le symptôme accusait la mauvaise cause.** Le contrôle annonçait
« `lead.siren` : jamais renseigné », c'est-à-dire un reproche au *corpus* — alors
que le corpus l'exerçait, et que c'est l'agrégation qui perdait l'information. On
pouvait passer un moment à enrichir un corpus déjà suffisant.

C'est une famille à part de ce que ce projet a déjà nommé : les six visages
décrivent des tests **aveugles**, ici le test voit quelque chose de réel et le
**nomme mal**. Un message de diagnostic est une hypothèse sur la cause, et une
hypothèse non vérifiée envoie chercher au mauvais endroit.

`_unir` fusionne désormais les membres de même genre. Deux tests unitaires le
gardent, et ils sont écrits pour se séparer : l'un vérifie qu'il ne reste
**qu'une** forme d'objet, l'autre que le message n'accuse plus le corpus.

##### Un même événement change de catégorie selon la route

Le corpus a fait apparaître un point qu'aucun test ne disait : `/evenements/{id}`
**n'applique aucun seuil de montant**. L'annonce `PETIT`, écartée partout
ailleurs pour être sous le minimum, y ressort donc en **lead**.

Ce n'est pas un défaut — une fiche répond « voilà ce cas », pas « ce cas
entre-t-il dans votre recherche ? ». Mais ça rendait le corpus incapable
d'exercer `ecarte.siren` en nul, et le type sortait non-nullable. D'où
`APPORT-ANONYME` : un refus qui tient **quel que soit le montant**, sans SIREN.

Rappel de la limite qui l'a rendu nécessaire : le contrôle voit les champs
*toujours* nuls, jamais ceux qui ne le sont *jamais*. C'est au corpus d'exercer
la nullabilité là où elle existe.

Sept mutations, sept détectées.

#### Le défaut trouvé en usage réel : `detail` n'avait pas toujours la même forme

Une recherche « 06 / Avril / 300k / 500k » affichait **« /leads : reponse 422 »**
— le repli du front — alors que l'API savait parfaitement que trois champs
étaient en cause et lesquels.

**Deux chemins de refus, deux formes sous la même clef.** `_argument_invalide`
attrape les `ValueError` du vocabulaire du domaine et rend `detail` en
**chaîne**. La validation de FastAPI, elle, rendait nativement une **liste**
d'objets `{loc, msg, input}`. Même code HTTP, même clef, autre type — et un
consommateur qui attend une chaîne tombe sur son repli sans savoir pourquoi.

Le docstring de `client.ts` affirmait pourtant : « le front affiche le refus de
l'API tel qu'il vient (422 et son `detail`, qui dit déjà la forme attendue) ».
C'était vrai la moitié du temps.

##### C'est le sixième visage, et il s'est produit exactement comme annoncé

`client.test.ts` fabriquait `{detail: "…"}`. Il prouvait qu'un `detail` textuel
arrive intact à l'écran — ce qui est vrai — **et rien sur ce que l'API produit**.
Le contrat validé n'était honoré que par un des deux gestionnaires.

Le passage qui le décrit était déjà écrit dans ce fichier : *« un test dont
l'entrée est fabriquée ne prouve rien sur la production tant qu'un autre test
n'a pas branché le même chemin sur la vraie source »*, et *« aucune mutation du
code de production ne le révèle »*. Les treize mutations de la Phase 6 étape 2 et
les six de la route 1 n'avaient aucune chance : le défaut n'est pas dans le code
testé, il est dans l'écart entre l'entrée du test et l'entrée réelle.

**Le signal à surveiller était nommé lui aussi** — « un littéral dans un test qui
décrit la sortie d'un autre module ». `{detail: "departement illisible : 'xx'"}`
en était un, écrit de ma main, et je ne l'ai pas vu en le tapant.

##### La correction : la forme du refus fait partie du contrat

Un gestionnaire de `RequestValidationError` rédige les erreurs en une phrase.
`detail` est désormais une chaîne **sur les deux chemins**.

Trois choses y figurent, et il faut les trois :

| Élément | Sans lui |
|---|---|
| le **champ** | l'appelant en a saisi quatre, il devine lequel |
| le **motif** | il sait que c'est faux, pas pourquoi |
| la **valeur reçue** | le message se lit comme une règle générale |

Le motif reste celui de pydantic, **verbatim et en anglais**. Une table de
traduction vers des messages qu'on ne contrôle pas serait muette au premier type
d'erreur nouveau, et personne ne le verrait — c'est un paramètre recopié qui
dérive de sa source, appliqué à des libellés.

Le champ est nommé **tel que l'appelant l'a écrit** : `mois`, pas `query.mois`.
La mutation qui garde le préfixe du framework survivait à une assertion
`"mois" in detail` — « query.mois » la contient — d'où une assertion de plus.

##### Le pont : un test qui branche vraiment les deux modules

`web/tests/refus.test.ts` ne fabrique rien. `tests/test_front_execute.py`
interroge la **vraie API**, écrit sa réponse telle quelle dans un fichier, et la
donne au **vrai `client.ts`**. Le corpus couvre les deux gestionnaires — sans
quoi le pont ne garderait que la moitié du contrat, ce qui est exactement le
défaut qu'il doit empêcher.

Vérifié en le cassant : remettre `exc.errors()` fait rougir le pont sur les cas
de validation et **pas** sur le cas du vocabulaire du domaine. C'est la preuve
qu'il branche réellement, et qu'il distingue les deux chemins.

Cinq mutations sur la rédaction du refus, cinq détectées.

##### Ce qui reste, et que je n'ai pas corrigé

Le champ s'appelle `mois` et l'utilisateur y a écrit « Avril ». Le libellé est
une clef prettifiée — le front n'a pas le droit d'inventer « nombre de mois » —
et l'API porte bien une `description` par paramètre, mais **le front ne la lit
pas**. La rendre visible demanderait de l'exposer hors de l'OpenAPI. C'est une
piste, pas une dette cachée : le message d'erreur nomme maintenant le champ, le
motif et la valeur, ce qui débloque l'utilisateur en un aller-retour.

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

## Piège d'environnement : un `.pth` caché désactive l'installation éditable

Rencontré le 2026-08-18 en vérifiant les commandes de lancement. Symptôme :

```
$ .venv/bin/fundora-prospect-collecte
ModuleNotFoundError: No module named 'fundora_prospect'
```

alors que `pytest` passe et que le paquet est installé en éditable.

**Cause.** L'install éditable dépose
`site-packages/_editable_impl_fundora_prospect.pth`, qui contient le chemin de
`src/`. Sous `~/Desktop`, quelque chose lui applique le flag macOS
**`UF_HIDDEN`** — et `site.addpackage` **saute silencieusement les `.pth`
cachés**. Aucun message, aucun avertissement : le chemin n'est simplement jamais
ajouté à `sys.path`. Le flag revient après chaque réinstallation. Un venv créé
dans `/private/tmp` n'a pas le problème.

**Pourquoi ça n'a pas été vu plus tôt** — et c'est le vrai enseignement : les
deux façons de lancer le projet contournaient le défaut sans le signaler.
`pytest` a `pythonpath = ["src", "."]` dans `pyproject.toml`, et `demo.sh` force
`PYTHONPATH` avec le commentaire « la démo n'a pas le droit de tomber devant un
recruteur pour une histoire de sys.path ». **Deux contournements écrits par
prudence ont masqué un environnement cassé pendant des semaines** — y compris
pour `fundora-prospect-mcp`, le point d'entrée que `.mcp.json` référence.

Un contournement défensif rend le chemin nominal non testé. C'est la même forme
que le faux ami de la substitution de dépendance en Phase 6 : ce qui fait passer
le test cache ce que le test devait prouver.

**Réparation ponctuelle** — à refaire après chaque `pip install -e` :

```sh
chflags nohidden .venv/lib/python3.13/site-packages/*.pth
```

**Contournement fiable, et celui à donner** : `export PYTHONPATH="$PWD/src"`.
Il fonctionne quel que soit l'état de l'installation.

## Si le temps manque

Priorité de coupe, dans cet ordre : Phase 3 enrichissement → Phase 4 serveur
MCP (repli sur des skills appelant des scripts).

Ordre confirmé au gate Phase 0 : le lead existe sans l'enrichissement, puisque
BODACC porte déjà SIREN et raison sociale du cédant. Si la Phase 3 saute, on
perd la distinction société active / radiée — le scoring est moins fin, mais
le pipeline sort quand même des leads exploitables.
Ne coupe jamais : le parsing du prix, le scoring explicable, le hook de
whitelist. Ce sont les trois choses qui font la valeur du projet en entretien.