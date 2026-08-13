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
  B2B, intérêt légitime solide, ~1 046 cas/an en PACA (mesuré Phase 0).
  Société active = trésorerie encore au bilan, à placer.
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
| Personne morale | 805 (67 %) | 803 | 240 | ~1 046 |
| Personne physique | 236 (20 %) | 223 | 36 | ~135 |
| Absent | 159 (13 %) | 6 | — | exclu |

`url_complete` fournit l'URL de publication par annonce : la contrainte de
traçabilité est satisfiable nativement, sans reconstruction d'URL.

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
   de champs. Elle est **vérifiée par un test**, pas par une relecture : un
   test parcourt `tests/fixtures/` et échoue si un motif nom-propre ou adresse
   y subsiste.
5. **Scoring explicable.** Chaque score sort avec le détail de son calcul.
   Pas de boîte noire.

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
et département, avec whitelist de domaines appliquée au transport HTTP et
cache disque.
Le vrai travail est le **parsing du prix de cession**, en texte semi-structuré
dans `listeetablissements.etablissement.origineFonds`. Traite les cas : prix
absent, devise (euros / EUR / francs), formats variés, "apport partiel",
montants aberrants.
Extraction du cédant depuis `listeprecedentproprietaire`, avec son
`typePersonne`, et exclusion des annonces sans cédant.
Gate : tests unitaires sur fixtures + 1 test réseau. Taux de parsing du prix
mesuré et affiché sur un échantillon réel — référence à battre : 86 %.

### Phase 2 — Modèle et scoring (J2 matin)
`models.py` : `LiquidityEvent`, `Lead`, `ScoreBreakdown` (pydantic).
`scoring.py` : fonction pure et déterministe. Critères :
- montant de cession (pondération forte, plafonnée)
- fraîcheur : fenêtre 0–18 mois, décroissance au-delà
- secteur d'activité
- département
Sortie : score 0–100 + détail par critère.
Gate : tests paramétrés sur les cas limites (prix nul, date future, secteur
inconnu, montant extrême).

### Phase 3 — Enrichissement + provenance (J2 après-midi)
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