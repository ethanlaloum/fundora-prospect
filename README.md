
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

Chiffre **mesuré**, pas estimé. Démonstration complète en une commande :

```bash
./demo.sh
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

Ce que le pipeline en tire, avec le détail du calcul — **sortie réelle, calculée
le 2026-08-16** :

```
LiquidityEvent  A20260153319
  cédant        LE FOURNIL D ORNELLA  (personne morale, SIREN 852872563)
  montant       185 000 EUR                    qualification : achat
  acte          2026-07-25   parution 2026-08-13   écart 19 jours
  statut        ACTIVE — société active, trésorerie de cession au bilan
  activité      APE 10.71C   section C

Score 73,04 / 100
  montant       31,70 pts   185 000 EUR, échelle log entre 10 000 et 1 580 000 EUR
  fraîcheur     41,34 pts   22 jours depuis la date d'acte ; décroissance demi-vie
                            dès le premier jour, demi-vie 180 jours
  secteur        0,00 pts   code APE 10.71C hors liste prioritaire ; poids 0
  département    0,00 pts   département 13 ; poids 0 — périmètre PACA homogène

Provenance
  source        BODACC — Bulletin officiel des annonces civiles et commerciales
                (DILA), consulté via l'API publique bodacc-datadila.opendatasoft.com
  base légale   Donnée issue d'une publication légale obligatoire au BODACC
                (DILA), concernant une personne morale, exploitée dans un
                contexte de prospection B2B.
  collecte      2026-08-16
  publication   https://www.bodacc.fr/...?q.id=id:A20260153319
```

La date de calcul est indiquée parce que **le score bouge avec elle** : la
fraîcheur décroît dès le premier jour, donc le même événement vaudra moins
demain. Un score affiché sans sa date est un chiffre détaché de son référent.

Le statut `ACTIVE` est ce qui autorise ce lead à être classé : une société
radiée sort du classement avec son motif, parce que son produit de cession est
déjà descendu aux associés.

Chaque point est justifié, y compris les critères qui ne rapportent rien. Aucun
score ne sort sans son détail, et `somme(contributions) == score` est vérifié
par un test.

**Le bloc `provenance` n'est pas décoratif.** Les quatre champs de la
contrainte 3 y sont obligatoires, et un lead qui n'arrive pas à les remplir
n'est pas exporté — voir [Traçabilité](#conformité) plus bas.

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
morale. En échange : une prospection B2B qui ne repose sur aucune inférence
concernant des personnes physiques — ni sur leur identité, que l'annonce ne
donne pas, ni sur ce qu'elles auraient perçu.

*Le raisonnement s'arrête là.* Dire que ce recentrage rend la base « solide »
serait une qualification juridique, et le projet n'en produit pas — voir
[Limites connues](#le-projet-documente-sa-source-il-ne-qualifie-pas-le-traitement).

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
`predict` ou `train`. Les poids vivent dans `src/fundora_prospect/config/ponderation.toml`, chargé
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
| Traçabilité de chaque lead | Porte de sortie unique : `provenance.serialiser`, qui n'accepte qu'un `Lead` complet | `tests/test_provenance.py` |
| Zéro donnée personnelle au dépôt | Liste blanche + substitution à la capture + hook `pre-commit` | `tests/test_anonymisation.py` |
| Base légale par segment | `type_personne` porté jusqu'au lead, jamais dans le score | `tests/test_bodacc.py` |
| Scoring explicable | `somme(contributions) == score`, motif obligatoire par critère | `tests/test_scoring.py` |
| Opposition INSEE respectée | `statut_diffusion ≠ O` ⇒ lead écarté avec motif | `tests/test_enrichment.py` |
| Pas de données hors périmètre | `dirigeants` supprimé à la capture, absent du modèle | `tests/test_enrichment.py` |
| Aucun modèle défini mais jamais construit | Audit du graphe d'appel : un symbole public sans appel ni justification échoue | `tests/test_symboles_morts.py` |

La whitelist est vérifiée au **transport HTTP** et non dans une fonction
utilitaire : à cet endroit, aucun chemin de code ne peut l'éviter — ni une
redirection 302 vers l'extérieur, ni un sous-domaine, ni une URL construite
dynamiquement.

Les entreprises non diffusibles au sens INSEE sont écartées à
l'enrichissement.

### La traçabilité est une porte, pas une convention

La contrainte 3 dit qu'un lead sans provenance complète « ne doit pas **pouvoir**
être sérialisé ». C'est plus fort que « ne devrait pas », et ça change
l'implémentation : il ne suffit pas que le chemin nominal remplisse les quatre
champs, il faut qu'aucun chemin ne les contourne.

Le pipeline a donc **une seule sortie**, `provenance.serialiser`, qui n'accepte
qu'un objet `Lead` — donc une `Provenance` validée. Les quatre champs y sont
obligatoires *et* non vides : un champ obligatoire rempli par `""` satisfait le
type et trahit la contrainte. L'URL de publication doit être absolue, sinon la
provenance n'est pas vérifiable par un tiers.

Un lead qui échoue à ce contrôle **sort du flux avec son motif**, exactement
comme un apport en nature ou une société radiée : `provenance incomplete`
apparaît dans le décompte des refus. Ni rendu sans provenance, ni perdu en
silence.

> **Comment ce défaut existait.** Les classes `Provenance` et `Lead` étaient
> écrites depuis la Phase 2, mais construites nulle part : le serveur MCP
> assemblait sa réponse à la main et n'y mettait qu'un des quatre champs. La
> contrainte était documentée, jamais exécutée. Un modèle défini n'est pas une
> garantie tant que rien n'oblige à passer par lui.

**Le champ `base_legale` est descriptif, pas une qualification juridique.** Il
dit d'où vient la donnée et quel segment elle concerne — deux choses
vérifiables. Il ne nomme aucune base de traitement et ne cite aucun article.

C'est délibéré. Qualifier un traitement relève du **DPO de l'exploitant**, qui
seul connaît la finalité réelle, les durées de conservation et l'information
des personnes. Une formulation juridique assurée, écrite par un outil de
détection, donnerait l'apparence d'une analyse qui n'a pas eu lieu : c'est un
risque pour l'exploitant, pas une garantie. Le projet documente sa source et ne
préjuge pas de sa qualification. Un test verrouille la décision — sans lui, la
première relecture qui trouve le champ « trop vague » y remettrait une citation.

La distinction des deux segments, en revanche, est structurante et portée par
le champ :

| Segment | `base_legale` |
|---|---|
| Cédant personne morale | publication légale obligatoire au BODACC, personne morale, contexte de prospection B2B |
| Cédant personne physique | même source, personne physique — **segment distinct du B2B, qualification à établir avant toute utilisation** |
| Type non renseigné | même source, **segment non qualifié** — repli prudent : ce qu'on ne sait pas nommer n'est pas du B2B établi |

Un export qui mélange les deux premiers sans ce champ est précisément ce que le
projet s'interdit.

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
  scoring.py       grille de pondération ← config/ponderation.toml (dans le paquet)
        │          → non retenu ou aberrant : hors classement, avec motif
        ▼
  provenance.py    PORTE DE SORTIE UNIQUE — n'accepte qu'un Lead complet
        │          source / base légale / date de collecte / URL, non vides
        │          → provenance incomplète : hors classement, avec motif
        ▼
  Lead + ScoreBreakdown
        │
        ▼
  mcp_server.py    serveur MCP en stdio — le point d'entree du plugin
                   search_liquidity_events / enrich_company / score_lead
```

Le découpage qui compte : **`prix.py` tranche la qualité de la donnée,
`scoring.py` tranche la pertinence commerciale.** D'où deux seuils distincts —
24 mois dans le parser, décroissance continue dans la grille. Élargir la
fenêtre commerciale ne doit jamais obliger à modifier le parser.

---

## Le serveur MCP

Le pipeline est expose comme serveur MCP en stdio, ce qui permet de l'interroger
en langage naturel depuis Claude Code :

> « trouve-moi les cessions de plus de 300 k€ dans le 06 sur 6 mois »

Trois outils :

| Outil | Role |
|---|---|
| `search_liquidity_events` | **le pipeline complet** — recherche, prix, cédant, statut, score, tri |
| `enrich_company` | statut et APE d'un SIREN, pour inspecter un cas isolé |
| `score_lead` | applique la grille à une cession décrite à la main |

**`search_liquidity_events` fait tout le pipeline, délibérément.** Trois outils
strictement granulaires obligeraient le modèle à appeler la recherche, puis
l'enrichissement pour chaque SIREN, puis le scoring pour chaque événement : des
dizaines d'allers-retours, lents et impossibles à démontrer en direct. Un appel
suffit ; les deux autres outils restent là pour inspecter un cas précis.

**La réponse porte les motifs de refus, pas seulement les leads.** Sortie réelle
sur le 06, six mois, plus de 300 k€, limite par défaut (25) — **mesurée le
2026-08-16** :

```
662 annonces publiees, 600 rapatriees seulement (plafond de rapatriement
atteint), 142 sans cedant ou illisibles, 458 exploitables, 49 classables,
333 sous le montant minimum, 6 apport, 2 absent, 2 acte trop ancien,
1 societe cedante cessee. 25 rendus sur 49 classables (limite atteinte) ;
65 candidats non enrichis donc non classes, faute de budget d'appels :
relancer avec une limite plus haute pour les voir.
```

C'est verbeux, et c'est le prix de l'exactitude. Ce résumé tenait auparavant en
une ligne — « 458 annonces examinées, 5 classables » — dont **les deux nombres
étaient faux au même titre** : chacun était compté après une coupe, sous un nom
qui promettait la population entière.

Cinq statuts, qu'un seul mot recouvrait :

| | Sens | Est-ce un refus ? |
|---|---|---|
| **publiée** | existe au BODACC sur la période | — |
| **non rapatriée** | le plafond de 600 s'est arrêté avant | non, budget |
| **sans cédant ou illisible** | écartée par le client BODACC — mise en activité, pas de cession | oui, filtre dur |
| **écartée** | le parser ou la grille a **jugé** — il y a un motif | oui |
| **tronquée** | classable, mais hors des `limite` premiers | non, budget |
| **non enrichie** | jamais examinée : le budget d'appels s'est arrêté avant | non, budget |

Trois de ces six lignes ne sont pas des refus. Les compter comme tels
attribuerait à la grille des décisions qu'elle n'a jamais prises — et, dans
l'autre sens, présenter 458 comme le total masquait que **69 % seulement de la
population avait été regardée**.

L'auditabilité construite dans le parser et la grille reste visible jusque dans
le transport MCP — sinon elle n'existerait que dans les tests.

**Chaque lead rendu porte son bloc `provenance`** : source, base légale du
segment, date de collecte, URL de l'annonce. Le serveur ne construit plus la
charge utile lui-même, il passe par la porte unique décrite en
[Conformité](#la-traçabilité-est-une-porte-pas-une-convention) ; un lead qui
n'arrive pas à la franchir est compté dans les refus sous le motif
`provenance incomplete`.

Sur la mesure ci-dessus, **`provenance incomplete` vaut 0 sur 458 annonces
examinées, et les 25 leads rendus portent les quatre champs**. C'est le
résultat attendu — `url_complete` est fourni nativement par BODACC — mais il
est *mesuré*, pas déduit. La différence n'est pas rhétorique : les trois
défauts les plus coûteux de ce projet (test à vide, pré-classement biaisé,
modèle jamais construit) ont tous survécu parce qu'un raisonnement plausible
avait tenu lieu de vérification.

**Un détail de conception qui compte.** L'enrichissement coûte un appel API par
lead, donc seul le haut du panier est enrichi. Ce pré-classement se fait sur le
**score provisoire**, pas sur le montant : trier sur le montant réintroduirait
exactement le biais que la grille a corrigé, et une cession fraîche mais modeste
ne serait jamais enrichie, donc jamais rendue. Un test le vérifie.

---

## Le plugin Claude Code

```
.claude-plugin/plugin.json          manifeste — SEUL fichier de ce dossier
.mcp.json                           declaration du serveur MCP
hooks/hooks.json                    hook PreToolUse
hooks/whitelist_domaines.py         le garde-fou
bin/fundora-prospect-mcp            lanceur, sans hypothese de venv
skills/scan-liquidity-events/       « trouve-moi les cessions… »
skills/score-lead/                  « pourquoi ce lead a-t-il ce score ? »
```

`skills/` et `hooks/` sont à la **racine**, jamais dans `.claude-plugin/` — l'y
placer est l'erreur la plus fréquente, et elle échoue silencieusement : le
plugin se charge, les compétences sont ignorées. Un test le vérifie plutôt
qu'une relecture.

### Installation

```
/plugin marketplace add ethanlaloum/fundora-prospect
/plugin install fundora-prospect@fundora
```

La source est le dépôt git, pas un chemin local : Claude Code le clone, donc
seuls les fichiers versionnés sont copiés. Un chemin local ferait une copie
brute du répertoire — `.venv` compris, soit 90 Mo d'environnement virtuel dont
les scripts pointeraient vers l'interpréteur de la machine d'origine.

Le serveur MCP est lancé par `bin/fundora-prospect-mcp`, un script versionné
qui **ne suppose aucun environnement virtuel**. Le plugin embarque son code
source : le paquet n'a pas besoin d'être installé, il suffit d'un Python 3.11+
disposant de `httpx`, `pydantic` et `mcp`. Le script les cherche dans cet
ordre — `$FUNDORA_PYTHON`, le venv du dépôt s'il existe, puis le `PATH` — et
s'il n'en trouve aucun, il sort en nommant la commande de réparation plutôt
que de mourir en silence sur un « Connection closed ».

Trois tests lancent la commande exacte de `.mcp.json` depuis une copie du
plugin, dans un répertoire arbitraire — un par branche de recherche de
l'interpréteur :

| Branche | Situation reconstituée | Ce qui est exigé |
|---|---|---|
| `$FUNDORA_PYTHON` | surcharge explicite | handshake MCP |
| `<racine>/.venv` | venv à l'emplacement conventionnel, **aucun Python sur le `PATH`** | handshake MCP |
| `PATH` | **aucun Python utilisable nulle part** | échec nommant les paquets et la réparation |

Les deux derniers tournent avec un `PATH` réduit à un répertoire qui ne
contient que `dirname` et `cat` — les seuls binaires externes dont le lanceur a
besoin. Sans cette réduction, ils passeraient sur une machine de développement
pour une raison sans rapport avec ce qu'ils prétendent vérifier : un `python3`
du `PATH` qui porte les dépendances.

**C'est une correction, pas une précaution.** Jusqu'au 2026-08-16, un seul test
couvrait le lanceur, et il se donnait `FUNDORA_PYTHON=sys.executable` — donc il
validait le lanceur *à condition qu'on lui tende un interpréteur utilisable*,
alors que la panne réelle est « aucun interpréteur trouvé ». Le serveur MCP du
plugin installé ne démarrait pas sur la machine de développement pendant que la
suite était verte. Un commentaire affirmait même que sans `FUNDORA_PYTHON` le
lanceur « chercherait sur le `PATH` — ce qui marche aussi » : garantie jamais
mesurée, et fausse. Même famille que la leçon sur les symboles jamais
construits, d'un cran plus subtile — ici le test appelait bien le code, mais
neutralisait la variable qu'il était censé éprouver.

#### Le mur d'installation : les Python récents refusent `pip install --user`

C'est ce que rencontrera quiconque installe le plugin, et ça mérite d'être
écrit tel que ça s'est présenté plutôt qu'en conseil général.

**Symptôme.** `claude mcp list` affiche :

```
plugin:fundora-prospect:fundora-prospect  ✘ Failed to connect — Connection closed
```

Les compétences se chargent quand même — elles sont du texte — puis elles
pointent vers un outil MCP qui n'existe pas. La capacité principale du plugin
est morte sans qu'aucun test ne l'indique.

**Diagnostic.** Claude Code ne montre que « Connection closed ». Le message du
lanceur, lui, est explicite : il faut l'exécuter à la main.

```
~/.claude/plugins/cache/fundora/fundora-prospect/<version>/bin/fundora-prospect-mcp
```

**Cause, mesurée le 2026-08-16.** Aucun interpréteur du `PATH` ne portait les
trois dépendances, et le dossier de cache n'a pas de `.venv` — les deux
premières branches de recherche échouaient, la troisième aussi.

**Le piège.** La réparation évidente, `python3 -m pip install --user`, échoue
sur un Python installé par Homebrew : il est marqué `EXTERNALLY-MANAGED`
(PEP 668) et refuse toute installation hors venv. Sur cette machine,
`python3` et `python3.13` étaient ce Python-là.

Vérifier avant d'essayer :

```
python3 -c 'import sysconfig, os; p = sysconfig.get_path("stdlib") + "/EXTERNALLY-MANAGED"; \
print("refuse --user" if os.path.exists(p) else "accepte --user")'
```

**Trois réparations, par ordre de durabilité :**

1. **Un interpréteur qui accepte `--user`.** Les builds python.org
   (`/Library/Frameworks/Python.framework/…`) ne sont pas marqués. C'est ce qui
   a été fait ici, sur `python3.11` :

   ```
   python3.11 -m pip install --user "httpx>=0.27" "pydantic>=2.7" "mcp>=2.0"
   ```

   Le lanceur trouve alors l'interpréteur seul, par sa troisième branche.
   Aucune variable d'environnement à poser, et ça survit aux mises à jour du
   plugin.

2. **Un venv dédié, désigné par `FUNDORA_PYTHON`.** Fonctionne avec n'importe
   quel Python, y compris Homebrew. Demande que la variable soit visible du
   processus qui lance Claude Code.

   ```
   python3 -m venv ~/.local/share/fundora-prospect
   ~/.local/share/fundora-prospect/bin/pip install "httpx>=0.27" "pydantic>=2.7" "mcp>=2.0"
   export FUNDORA_PYTHON=~/.local/share/fundora-prospect/bin/python
   ```

3. **Un venv dans le dossier du cache** — voir plus bas. Le plus direct, mais
   ce chemin contient le numéro de version : il est à refaire à chaque mise à
   jour du plugin.

`--break-system-packages` marche aussi sur un Python Homebrew. À éviter : le
gain est nul par rapport au venv dédié, et le coût est une installation
système que le gestionnaire de paquets ne connaît pas.

#### Mettre à jour : le cache est indexé par version

**Pousser du code ne suffit pas à mettre à jour un plugin installé.** Le plugin
est déposé dans `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`, et
ce chemin contient le **numéro de version**. Tant que `plugin.json` annonce la
même version, l'installateur réutilise l'arbre déjà en cache — même après un
`/plugin marketplace update` qui, lui, rafraîchit bien la source dans
`~/.claude/plugins/marketplaces/`.

Le symptôme est trompeur : le marketplace est à jour, le code sur GitHub est à
jour, et le plugin exécuté reste l'ancien. On le repère à ce qui ne devrait
plus être là — une description d'outil périmée, un fichier neuf absent.

Donc : **toute modification livrée s'accompagne d'un incrément de version**,
dans `plugin.json`, `marketplace.json`, `pyproject.toml` *et* `__version__`. Un
test vérifie que les quatre ne divergent pas.

Les deux manifestes ne suffisaient pas : `__version__` est ce que le serveur
annonce au client dans `serverInfo.version`, donc **la seule des quatre qu'un
tiers observe à l'exécution**. Le 2026-08-16, les manifestes portaient `0.2.0`
et les deux autres sources étaient restées à `0.1.0` — le serveur MCP annonçait
`0.1.0` pendant que le cache l'indexait sous `0.2.0`. Les tests d'égalité de
l'époque ne comparaient les manifestes qu'entre eux.

Deuxième piège, indépendant : `/plugin reload` ne tue pas le processus du
serveur MCP déjà lancé. Après une mise à jour, il faut **redémarrer Claude
Code** pour que le serveur reparte sur le nouveau code.

Enfin, si l'interpréteur du `PATH` ne porte pas les trois dépendances, le venv
doit être créé **dans le dossier du cache**, pas dans celui du marketplace :

```
V=~/.claude/plugins/cache/fundora/fundora-prospect/<version>
python3 -m venv $V/.venv && $V/.venv/bin/pip install -e $V
```

Ce chemin change à chaque version. Sur une machine où l'on démontre souvent,
mieux vaut exporter `FUNDORA_PYTHON` vers un interpréteur stable qui possède
`httpx`, `pydantic` et `mcp` : le lanceur le consulte en premier, et il survit
aux mises à jour.

### Deux verrous, deux périmètres

La contrainte de whitelist est appliquée **deux fois**, à deux endroits qui ne
se recouvrent pas :

| Verrou | Ce qu'il barre | Ce qu'il ne voit pas |
|---|---|---|
| **Hook `PreToolUse`** | l'**agent** — `WebFetch`, `WebSearch`, `Bash` | une URL cachée dans un fichier `.py` |
| **Transport HTTP** | le **code** — tout `httpx` du projet | un `curl` tapé par l'agent |

**Aucun des deux ne suffit seul, et le dire fait partie de la démonstration.**
Un hook n'intercepte pas un `httpx.get()` enfoui dans un script : prétendre le
contraire serait une démonstration de vendeur, et le trou se verrait. Les deux
limites sont verrouillées par des tests, y compris celle du hook.

Le refus est conçu pour être lisible en direct :

```
  APPEL RESEAU REFUSE — contrainte 2 du projet

    domaine demande  : www.linkedin.com
    domaines permis  : bodacc-datadila.opendatasoft.com
                       recherche-entreprises.api.gouv.fr

  fundora-prospect ne collecte que des publications legales
  obligatoires. Un CIF agree AMF ne peut pas exploiter une base
  constituee autrement.

  Aucune connexion n'a ete ouverte.
```

Il tient en une hauteur d'écran, cite la contrainte par son numéro — le refus
vient de la spécification, pas d'un garde-fou improvisé — et le domaine choisi
pour la démonstration est celui qu'un commercial pressé tenterait vraiment.

---

## Limites connues

Cette section est la plus importante du document. Un pipeline de prospection
qui ne connaît pas ses angles morts en produit sans le savoir.

### Le hook bloque `www.bodacc.fr`, et ce faux positif reste

Le hook `PreToolUse` refuse tout appel réseau hors des deux domaines de la
contrainte 2. Or les leads portent une URL de publication en
`www.bodacc.fr` — le site de consultation, qui n'est **pas** l'API
`bodacc-datadila.opendatasoft.com`. Coller un extrait contenant une de ces URL
dans une invite déclenche donc un refus, alors que rien n'allait être appelé.

**Ce faux positif est conservé délibérément.** Ajouter `www.bodacc.fr` à la
liste pour se débarrasser d'une gêne, c'est ouvrir la porte au raisonnement qui
suit — celui-ci est inoffensif, celui-là aussi, et la liste finit par ne plus
rien garantir. **Un verrou avec des faux positifs assumés est plus solide qu'un
verrou troué d'exceptions de confort**, parce que sa règle reste énonçable en
une phrase : deux domaines, tout le reste lève.

Le hook opère par ailleurs sur du texte, pas sur des intentions : il ne peut
pas distinguer une URL qu'on s'apprête à appeler d'une URL qu'on cite. Cette
imprécision est le prix de sa simplicité, et elle penche du bon côté.

Sans effet sur `./demo.sh`, dont l'invocation ne contient aucune URL.

### Le projet documente sa source, il ne qualifie pas le traitement

**La qualification de la base de traitement relève du DPO de l'exploitant.**
Ce projet établit et transporte la provenance de chaque lead — quelle
publication légale, quelle date de collecte, quelle URL, quel segment — et
n'en préjuge pas.

C'est une limite assumée, pas un oubli. Nommer une base de traitement suppose
de connaître la finalité poursuivie, les durées de conservation retenues et les
modalités d'information des personnes : trois choses qui appartiennent à
l'exploitant, pas à l'outil de détection. Le champ `base_legale` est donc
**descriptif** — il dit d'où vient la donnée et quel segment elle concerne.

Ce que ça implique concrètement pour qui reprend le projet :

- le segment **personne physique** est signalé comme distinct de la
  prospection B2B, et sa qualification est à établir **avant** toute
  exploitation ;
- un cédant dont le type n'est pas renseigné retombe sur le même traitement
  prudent ;
- rien dans la sortie ne doit être lu comme une validation de conformité.

Un outil qui affirmerait sa propre conformité serait moins fiable qu'un outil
qui rend sa provenance vérifiable. C'est le second qui est implémenté ici.

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

Les poids — 55 pour le montant, 45 pour la fraîcheur, 0 pour le secteur, 0
pour le département — sont des **hypothèses commerciales**. Aucune donnée de
conversion n'existe pour les valider.

Ils sont recalibrables sans toucher au code, et `src/fundora_prospect/config/ponderation.toml` porte
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
**aucune occurrence sur les 105 cédants enrichis ; un cas observé depuis, en
64.30Z.** Les 8,6 % que je pensais trouver en K sont en section L (immobilier),
pour laquelle l'argument « professionnel de la finance » ne tient pas. La règle
n'a pas été implémentée.

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
python3 -m venv .venv                   # Python 3.11 ou plus recent
.venv/bin/pip install -e ".[dev]"
git config core.hooksPath .githooks     # active le garde-fou RGPD
```

Deux variables d'environnement, toutes deux optionnelles :

| Variable | Effet |
|---|---|
| `FUNDORA_CACHE_DIR` | déplace le cache HTTP. `FUNDORA_CACHE_DIR=$(mktemp -d)` force une exécution **à froid**, sans réponse en cache |
| `FUNDORA_PONDERATION` | pointe une grille de pondération recalibrée, sans toucher au dépôt |

Le cache vit par défaut dans `~/.cache/fundora-prospect/`, **hors du dépôt** :
il contient des réponses d'API avec des données personnelles réelles, et le
`.gitignore` protège du commit, pas d'une archive du répertoire de travail.

| Commande | Ce qu'elle produit |
|---|---|
| `./demo.sh` | démonstration complète : pipeline, hook, transport, provenance |
| `.venv/bin/python -m pytest -q` | 429 tests unitaires, sur fixtures figées, sans réseau |
| `.venv/bin/python -m pytest -m network -q -s` | volume annuel, taux de parsing par segment, corrélation de rang |
| `.venv/bin/python explore/dump_bodacc.py` | structure de la donnée, taux de présence du prix |
| `.venv/bin/python explore/probe_origine_fonds.py` | les montants en francs, les annonces multi-établissements |
| `.venv/bin/python tools/record_fixtures.py` | recapture les fixtures, anonymisées à l'écriture |
| `.venv/bin/python tools/symboles_morts.py` | audit du code mort : symboles publics que rien ne construit |

Chaque chiffre de ce README sort d'une de ces commandes.

**Note sur la reproductibilité.** Vérifié depuis un clone vierge : installation,
suite hors ligne, suite réseau et scripts d'exploration passent, et le dépôt
reste propre — aucune donnée runtime n'y atterrit.

Trois réserves honnêtes :

- Les mesures réseau tirent un échantillon frais à chaque exécution. Les
  valeurs bougent de quelques unités — ~895 à ~898 pour le volume annuel. Les
  ordres de grandeur sont stables, les décimales ne le sont pas.
- À froid, la suite réseau prend ~5 s au lieu de ~0,2 s : la différence est le
  cache. Utiliser `FUNDORA_CACHE_DIR` pour mesurer sans cache.
- **`tools/record_fixtures.py` fera dériver les fixtures avec le temps.** Une
  de ses requêtes trie par date de parution décroissante : les annonces les
  plus récentes changent chaque jour, donc une recapture ultérieure produira
  d'autres cas et salira l'arbre de travail. C'est voulu — figer cette requête
  échangerait de la fraîcheur de donnée réelle contre une reproductibilité de
  façade. Ne relancer le recorder que pour rafraîchir volontairement les
  fixtures, et relire le diff.

---

## Suite possible

Signaux secondaires non exploités : dissolutions avec boni de liquidation,
radiations post-cession. Élargissement hors PACA — le critère départemental est
déjà en place, à poids nul faute de base pour hiérarchiser.

Et la seule chose qui rendrait la grille défendable autrement que « à dire
d'expert » : un retour de conversion, qui permettrait enfin de la calibrer.
