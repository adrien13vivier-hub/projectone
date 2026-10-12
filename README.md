# 📊 ProjectOne — Portfolio Analyzer

Un rapport par utilisateur, chaque soir de bourse à **22h37 (Paris)**, une fois
New York et Euronext fermés. Le serveur YunoHost donne le top départ, l'analyse
tourne sur GitHub Actions (où vivent les clés API), les rapports sont publiés
sur Cloudflare Pages. Plusieurs sources de données gratuites, croisées, avec
repli en cascade et cache.

> **Statut de la note sur 10 : expérimentale.** Le programme mesure lui-même ce
> que ses notes ont valu (section « Fiabilité des notes »). Sur 4 662 notes
> reconstituées sur trois ans (octobre 2026), le lien entre la note et la
> surperformance qui suit est **quasi nul**. ProjectOne est un outil de suivi
> et de discipline du risque ; la note est une aide à la lecture, pas un signal
> prouvé, et rien ici n'est un conseil en investissement.

## Ce que fait le programme

| Question | Section du rapport |
|----------|--------------------|
| Dans quel décor je navigue ? | **Contexte économique** — indices, taux 10 ans US et OAT, manchettes |
| Est-ce qu'une position est sortie de sa zone ? | **Stops & Alertes**, exposition corrélée |
| À quoi je suis exposé ? | **Répartition** — classe, devise, compte, étiquette |
| Que valent mes titres, un par un ? | **Analyse par valeur** + **Synthèse** |
| Comment évolue ma performance ? | **Tendances** — base 100 = prix de revient, depuis la date d'achat |
| La note a-t-elle eu raison par le passé ? | **Fiabilité des notes** (moteur d'apprentissage) |

---

## La note sur 10

Six critères, chacun noté sur 10, puis une moyenne pondérée
(`portfolio_analyzer.note_titre`, poids dans `POIDS_NOTE`) :

| Critère | Poids | Ce qui est mesuré (poids internes) |
|---------|-------|------------------------------------|
| Valorisation | 24 % | PEG (3), PER anticipé sinon PER (2,5), EV/EBITDA (2), cours/actif net (1), cours/ventes (1) — paliers absolus |
| Santé financière | 19 % | marge nette (2,5), marge opérationnelle (2), ROE (2,5 ; non récompensé au-delà de 40 %), ROA (1,5) |
| Croissance | 16 % | chiffre d'affaires sur un an (3), bénéfice sur un an (2) |
| Tendance | 21 % | performance à 1, 3 et 6 mois ; pénalité de surchauffe (+40 %, +60 %, +100 % en 6 mois) ; plancher après une chute de plus de 50 % |
| Avis des analystes | 15 % | recommandations Finnhub : achat fort 10, achat 7,5, conserver 5, vente 2,5, vente forte 0 |
| Risque | 5 % | bêta (2), position dans le canal 52 semaines (1,5), volatilité réalisée (2) |

**Absent n'est pas non applicable.** Un critère sans donnée sort du calcul et
les autres poids sont renormalisés ; la **confiance** est la part des poids
applicables réellement calculés. Pour un ETF ou une crypto, valorisation,
santé, croissance et avis des analystes sont *non applicables* : ils sortent
sans pénaliser la confiance.

| Note | Recommandation |
|------|----------------|
| ≥ 7,5 | RENFORCER |
| ≥ 6,0 | CONSERVER |
| ≥ 4,5 | SURVEILLER |
| ≥ 3,0 | ALLÉGER |
| < 3,0 | SORTIR |

Garde-fous : sous 40 % de confiance, ou avec moins de trois critères, la
recommandation devient « À EXAMINER ». Chaque note porte une **version**
(`SCORE_VERSION` = formule + empreinte des poids) : changer un poids ouvre une
nouvelle cohorte dans le moteur d'apprentissage.

---

## Fiabilité des notes (moteur d'apprentissage)

`learning_engine.py` traite chaque note comme une prévision datée, puis la
juge à 20, 60, 120 et 252 séances :

* **Surperformance** face à l'ETF sectoriel (et au marché), cours ajustés des
  dividendes et des splits, même devise des deux côtés.
* **Observations indépendantes** : un même titre n'est compté qu'une fois par
  fenêtre (`thin`), et le nombre de périodes de marché distinctes plafonne la
  confiance.
* **Journal commun anonyme** (`reports/@pool/learning`) alimenté par les
  profils qui l'acceptent et par un **univers de référence** de 220 actions
  (11 secteurs, États-Unis et zone euro, `data/univers_apprentissage.json`),
  noté chaque semaine par rotation.
* **Amorçage** (`amorcage_apprentissage.py`, workflow manuel) : ~4 700 notes
  passées des actions américaines rejouées sur trois ans, sans fuite du futur
  (cours TwelveData, comptes SEC pris à leur date de publication, biais de
  sélection retiré). Rangées à part, elles s'effacent d'elles-mêmes quand les
  vraies notes atteignent 60 observations indépendantes.
* **Modèle** : une régression Ridge sur les sous-notes, activée **seulement**
  si elle bat la moyenne hors échantillon (validation chronologique avec
  purge). Elle n'apprend que sur de vraies notes.
* **Étude des critères** (`python etude_note.py`, hors ligne) : pouvoir de
  classement (IC par date) de chaque critère, version relative au secteur,
  pondérations apprises sur la première moitié des dates et jugées sur la
  seconde.

## Gestion du risque

### Multi-actifs

Le portefeuille n'est plus limité aux actions. Neuf classes, réparties en deux familles :

| Famille | Classes | Cours |
|---------|---------|-------|
| **Cotées** | action, ETF, obligation, crypto, métal précieux | interrogé par API |
| **Non cotées** | liquidités, immobilier, collection, autre | valeur saisie à la main |

Une ligne non cotée ne consomme **aucun quota API** : elle n'a ni ticker ni
historique, seulement une valeur (`value`) et, si on le souhaite, un prix
d'acquisition (`buy_value`).

Toutes les lignes acceptent en plus un **compte** (`account`) et des
**étiquettes** libres (`tags`), qui deviennent deux axes de répartition.

### Les quatre types de stop

| Type | Paramètre | Niveau calculé | Monte avec le cours |
|------|-----------|----------------|---------------------|
| `percent` | un % | prix de revient − X % | non |
| `absolute` | un prix | ce prix, tel quel | non |
| `trailing` | un % | plus haut de clôture − X % | **oui** (cliquet) |
| `vq` | aucun | plus haut de clôture − VQ % | **oui** (cliquet) |

```json
"stop": {"type": "trailing", "value": 15}
"stop": {"type": "absolute", "value": 180, "devise": "USD"}
"stop": "vq"
```

**Règle de franchissement** : la *clôture* du jour passe sous le niveau — pas
le cours en séance, dont les à-coups produisent des sorties inutiles. **Une
seule alerte par franchissement** ; le déclencheur se ré-arme quand le cours
repasse au-dessus.

**Le VQ n'est pas celui de VectorVest.** Celui-ci est propriétaire et sa
formule n'est pas publique. Ce qui est implémenté ici est une transposition
transparente, entièrement écrite dans `risk_engine.py` :

```
VQ % = borne( 0,65 × volatilité annualisée , 8 % , 40 % )
```

La volatilité est mesurée sur **un an** de cotations journalières (depuis le
28/09/2026). Empiriquement, une grande capitalisation stable ressort autour de
12-15 %, une valeur très volatile autour de 30 %, le bitcoin autour de 38 %.

### Dimensionnement des positions

```
montant à engager = (capital × risque par idée) ÷ distance au stop
```

100 000 € de capital, 1 % de risque (1 000 €), stop à 20 % → 5 000 € de
position. Si le stop part, on perd exactement le budget de risque. C'est ce qui
rend une position volatile et une position calme **comparables** : on n'achète
pas le même montant, on achète le même risque.

Deux garde-fous : un plafond de poids par ligne (15 % par défaut) et le montant
de liquidités disponibles, quand il est renseigné. Une ligne **sans stop**
retombe sur un budget de volatilité (2 % par défaut) ; une ligne **déjà sous
son stop** ne reçoit aucune taille — proposer d'y remettre de l'argent le jour
où la règle dit d'en sortir n'aurait pas de sens.

**Quel capital ?** Les valeurs cotées **plus** les liquidités. L'immobilier et
les collections en sont exclus : risquer 1 % d'un patrimoine de 673 000 € dont
480 000 d'immobilier reviendrait à mettre 6 730 € par idée sur un portefeuille
boursier de 67 000 €. `settings.capital_reference` permet d'imposer une autre
valeur.

### Réglages du profil

| Réglage | Défaut | Rôle |
|---------|--------|------|
| `risque_pct` | 1,0 | % du capital risqué par idée |
| `poids_max_pct` | 15,0 | plafond de poids sur une ligne |
| `vol_cible_pct` | 2,0 | volatilité qu'une ligne sans stop peut apporter |
| `liquidites` | — | plafonne les tailles suggérées |
| `stop_defaut` | — | stop appliqué aux lignes qui n'en déclarent pas |
| `capital_reference` | — | force le capital de dimensionnement |

### État des stops

Les high-water marks et l'armement des alertes vivent dans
`reports/<utilisateur>/stops_state.json`, commité par le workflow au même titre
que le rapport. Sans ce fichier, un stop suiveur se recalculerait chaque jour
depuis l'historique disponible et perdrait son cliquet. Un fichier absent ou
corrompu n'est pas une erreur : les plus hauts repartent de l'historique connu,
et la première évaluation d'une ligne est signalée comme telle dans le rapport.

### Exposition corrélée (v8.2)

Le plafond de poids par ligne (`poids_max_pct`) protège contre **une** ligne
qui dérape. Il ne voit rien quand plusieurs lignes, chacune sous le plafond,
bougent **ensemble** : trois positions à 12 % chacune sur des valeurs tech
américaines très corrélées se comportent, un jour de panique, comme une seule
ligne à 36 %.

`risk_engine.exposition_correlee()` regroupe les lignes dont les rendements
quotidiens sont corrélés au-delà d'un seuil (0,70 par défaut), à partir des
historiques déjà récupérés pour la volatilité — **aucun appel API
supplémentaire**. Un groupe dont le poids cumulé dépasse `EXPOSITION_ALERTE_PCT`
(25 % par défaut) est signalé dans une nouvelle sous-section **Exposition
corrélée**, à l'intérieur de « Stops et Alertes » (rapport Markdown et page
HTML).

Limites assumées : une corrélation de Pearson sur l'historique disponible
n'est pas une classification sectorielle, et une corrélation passée ne
garantit rien sur la corrélation future — deux titres peuvent se décorréler
brutalement (l'un publie un résultat, pas l'autre). C'est un signal
d'attention, pas une prévision. En dessous de 21 clôtures communes, une paire
n'est pas évaluée plutôt que de publier un chiffre instable.

---

## Sources de données

| Donnée | Source principale | Repli |
|--------|-------------------|-------|
| Cours US | TwelveData (lots de 8) | EODHD, cache |
| Cours Europe, indices, taux 10 ans | EODHD | cache (AlphaVantage pour le taux US) |
| Historique (volatilité, tendance, échéances) | EODHD, 1 an | cache |
| EUR/USD | AlphaVantage | cache |
| Ratios d'entreprise | Yahoo Finance | EODHD (non inclus dans l'offre gratuite) |
| Avis des analystes | Finnhub (actions US) | EODHD (non inclus) |
| Actualités | flux RSS Yahoo Finance | — |
| Amorçage (passé) | TwelveData + SEC EDGAR | — |

Deux cours d'un même titre qui divergent de plus de **2 %** : la médiane est
retenue et la divergence est signalée dans le rapport.

## Secrets GitHub

| Nom | Rôle |
|-----|------|
| `EODHD_API_KEY` | Cours Europe, indices, taux, historique |
| `TWELVEDATA_API_KEY` | Cours US, amorçage |
| `FINNHUB_API_KEY` | Avis des analystes (US) |
| `ALPHAVANTAGE_API_KEY` | EUR/USD, repli du taux US |
| `SEC_USER_AGENT` | Amorçage : identification exigée par la SEC (« projet e-mail ») |

**Settings → Secrets and variables → Actions → New repository secret**

### Secrets SMTP optionnels — alerte de franchissement de stop

Sans ces secrets, **rien n'est envoyé** et ce n'est pas une erreur : l'alerte
reste visible dans la section « Stops & Alertes » du rapport. Avec eux, un
courriel part le jour où une position clôture sous son stop, et uniquement ce
jour-là. Port 465 (SMTPS) recommandé ; sur un autre port, STARTTLS est exigé
dès qu'un identifiant est fourni.

| Nom | Description |
|-----|-------------|
| `MAIL_SERVER` | Serveur SMTP (ex: smtp.gmail.com) |
| `MAIL_PORT` | Port SMTP (ex: 465) |
| `MAIL_USERNAME` | Adresse email expéditeur |
| `MAIL_PASSWORD` | Mot de passe / App password |
| `MAIL_FROM` | Adresse affichée en expéditeur |
| `MAIL_TO` | Adresse destinataire |

## Quotas (offres gratuites)

| API | Limite | Plafond du programme |
|-----|--------|----------------------|
| EODHD | 20 appels/jour + paquet d'appels acheté ; 1 an d'historique | `EODHD_PLAFOND_JOUR` (600 par défaut) |
| TwelveData | 800 crédits/jour, 8/minute, actions US | 780/jour |
| Finnhub | 60/minute | 3 000/jour |
| AlphaVantage | 25/jour | 20/jour |

Chaque fournisseur a aussi un limiteur par minute (fenêtre glissante) : le
programme attend plutôt que d'envoyer une requête qui serait refusée.

## Tests

```bash
pip install -r requirements-dev.txt
pytest                    # suite complète, sans réseau ni clé
python risk_engine.py     # autotest du moteur de risque
```

Le workflow **Tests** les lance à chaque modification poussée sur GitHub.

## Fichiers générés

| Fichier | Description |
|---------|-------------|
| `reports/<user>/daily_report.md` | Rapport Markdown du jour |
| `reports/<user>/history.csv` | Historique quotidien par ligne |
| `reports/<user>/stops_state.json` | Plus hauts atteints + armement des alertes |
| `reports/<user>/charts/portfolio_combined.png` | Graphique base 100 |
| `reports/<user>/learning/summary.json` | Synthèse « Fiabilité des notes » du profil |
| `reports/@pool/learning/` | Journal commun ; `amorcage/` = notes reconstituées |
| `docs/r/<jeton>/index.html` | Rapport HTML publié (Cloudflare Pages) |
| `cache/` | Derniers cours valides, secteurs |

## Outil historique : `backtest_score.py`

Premier contrôle de la note (v8.2) : il corrèle le score de `history.csv` au
rendement **brut** qui suit, sans référence de marché ni correction des
chevauchements. Il est **remplacé** par le moteur d'apprentissage et n'est
gardé que pour mémoire.

## Changelog

### Octobre 2026 — état actuel

- ✅ Note à six critères (le sentiment de presse a été retiré en v8.1), version
      gravée dans chaque note.
- ✅ Moteur d'apprentissage mutualisé, univers de référence de 220 actions,
      amorçage sur trois ans (actions US).
- ✅ Graphique base 100 = prix de revient, depuis la date d'achat (colonne
      « Date d'achat » dans l'interface).
- ✅ VQ et volatilité sur un an ; frais de courtage vérifiés par courtier.
- ✅ Tests lancés automatiquement sur GitHub ; 181 tests + 98 vérifications du
      moteur de risque.

### v8.2 — Exposition corrélée, backtest du score, tests automatisés

**Pourquoi.** La gestion du risque protégeait déjà chaque ligne prise
séparément (stops, plafond de poids, dimensionnement), mais rien ne
regardait les lignes ensemble, rien ne vérifiait que le score qui pilote
toutes ces décisions prédit quoi que ce soit, et une seule fonction
(`risk_engine.py`) avait des tests. Trois trous, trois correctifs :

- ✅ **Nouveau : exposition corrélée**
      (`risk_engine.correlation()` / `exposition_correlee()`). Regroupe les
      lignes dont les rendements quotidiens sont corrélés au-delà de 0,70,
      à partir des historiques déjà en mémoire — zéro appel API de plus.
      Un groupe dont le poids cumulé dépasse 25 % du portefeuille est signalé
      dans une nouvelle sous-section du rapport (Markdown et HTML). Voir
      « Gestion du risque » plus haut pour les limites assumées de la
      méthode.
- ✅ **Nouveau : `backtest_score.py`.** Corrèle le score publié un jour donné
      à la performance réellement observée ensuite. Premier résultat sur
      l'historique actuel (269 paires, horizon 30 jours) : corrélation quasi
      nulle (-0,04), et les lignes notées ACHAT FORT/MODÉRÉ ont même fait
      **moins bien** que GARDER/À ÉVITER sur la période mesurée. Ce n'est pas
      une condamnation de l'algorithme — l'échantillon reste petit et la
      période courte — mais c'est exactement le genre de signal qu'aucun
      outil ne remontait avant. À suivre dans le temps, pas à interpréter
      sur une seule mesure.
- ✅ **Nouveau : suite `pytest`** (`tests/test_risk_engine.py`,
      `tests/test_portfolio_analyzer.py`, 45 tests) couvrant volatilité,
      les quatre types de stop et leur cliquet, le dimensionnement, la
      nouvelle exposition corrélée, et les fonctions de notation
      (`note_titre`, `score_history`, paliers). `risk_engine.py` gardait déjà
      son autotest interne (`python risk_engine.py`, 79 vérifications) —
      inchangé, ces tests s'y ajoutent sans le remplacer.
- 🐛 **Doublon supprimé** : `_parse_serie()` était définie deux fois, à
      l'identique, dans `portfolio_analyzer.py`. Aucun changement de
      comportement (la seconde définition écrasait silencieusement la
      première) ; un test (`test_parse_serie_nest_plus_dupliquee...`) évite
      que ça revienne.

**Non traité dans cette passe, par choix explicite** : l'axe « alerte par un
canal plus rapide qu'un email » (Telegram/Discord) reste pour plus tard.

### v8.1 — Le site : horaire, comptes, mode d'emploi

**Pourquoi plus aucun rapport depuis le 31 août.** Les runs planifiés
apparaissaient tous **en vert** dans l'onglet Actions — et ne produisaient
rien, en 7 à 16 secondes au lieu d'une minute. Le garde-fou du workflow lisait
l'heure de Paris *au moment où le job démarre*. Or GitHub livre ses tâches
planifiées en retard : relevé sur ce dépôt, le cron de 20:37 UTC a démarré à
22:48 et 22:49 UTC, celui de 21:37 UTC à 23:31 et 23:32 UTC — plus de deux
heures, chaque jour. À 22:48 UTC il est 00h48 à Paris, le test « heure < 22 »
était vrai, et le job s'écartait lui-même en sortant en succès.

- ✅ Le garde-fou décide désormais à partir de `github.event.schedule` (quel
      cron a déclaré le tir), information exacte quel que soit le retard, et
      l'anti-doublon compare un **écart de temps** depuis le dernier rapport
      plutôt que des dates de calendrier — fragiles quand un tir arrive après
      minuit.
- ✅ **Le vrai top départ vient du serveur**, qui appelle GitHub à 22h37 pile
      (`api/github_sync.declencher_analyse`). L'analyse continue de tourner sur
      GitHub, où vivent les clés API ; seul le déclenchement change de camp.
      Les crons restent déclarés en filet de sécurité.
- ✅ Le keep-alive ne déclenche plus l'analyse. Il tournait le lundi à 07h00
      UTC, soit 9h du matin à Paris : il relevait des cours de **séance** et les
      écrivait dans un historique qui n'attend que des cours de clôture. Le
      rapport du 31 août à 16h30 venait de là.

**Connexion et comptes**

- 🐛 **On ne pouvait pas se reconnecter avec son propre identifiant.**
      L'inscription normalise le nom (« Pete33 » → `pete33`) ; la connexion
      interrogeait la base avec le texte brut. Taper son nom exactement comme à
      l'inscription renvoyait « Identifiants incorrects », sans explication. Un
      espace laissé par la saisie automatique d'un téléphone suffisait aussi.
- 🐛 La limitation de tentatives portait sur le nom brut : changer la casse à
      chaque essai repartait de zéro et permettait de tester des mots de passe
      en boucle. Elle porte désormais sur le nom normalisé.
- 🐛 **Les liens de rapport des nouveaux comptes ne menaient nulle part.** Les
      jetons sont fabriqués par le serveur ; sans être publiés dans le dépôt,
      GitHub Actions en générait d'autres au moment de publier. La table est
      maintenant poussée à chaque inscription **et** rattrapée au démarrage du
      service, pour les comptes déjà créés.

**Interface**

- ✅ Le bouton « Lancer maintenant » est retiré, et l'adresse `/api/analyze`
      répond 403 : retirer un bouton ne ferme pas une porte. Une analyse lancée
      depuis le serveur tourne sans les clés API, produit des cours faux et les
      écrit définitivement dans l'historique.
- ✅ Les créneaux étalés de 5 minutes (22h30, 22h35, 22h40…) ne sont plus
      affichés nulle part : l'analyse est groupée, tout le monde a le même
      horaire. L'heure affichée vient du serveur, donc elle ne peut plus mentir
      sur l'heure réelle du déclenchement.
- ✅ Nouvel onglet **Mode d'emploi** dans le site.
- ✅ Nouvelle adresse `/api/version` : elle dit quelle version tourne
      réellement sur la machine. Le doute avait coûté une semaine, deux
      correctifs présents dans le dépôt n'étant pas actifs sur le serveur.

### v8.0 — Multi-actifs, stops & alertes, dimensionnement
- ✅ **Nouveau fichier `risk_engine.py`** : volatilité, VQ, quatre types de
      stop avec cliquet, dimensionnement par le risque. Sans réseau, sans clé
      API, avec sa propre batterie de tests (`python risk_engine.py`).
- ✅ Modèle multi-actifs : 9 classes, dont 4 non cotées (liquidités,
      immobilier, collection, autre) qui ne consomment aucun quota.
- ✅ Crypto-actifs via EODHD (`BTC-USD.CC`), avec conversion USD → EUR.
- ✅ Comptes et étiquettes libres sur chaque ligne.
- ✅ Section **Stops & Alertes** et section **Répartition** dans le rapport
      Markdown et dans la page HTML.
- ✅ Alerte par courriel au franchissement, optionnelle et sans effet si les
      secrets SMTP ne sont pas posés.
- ✅ Interface de configuration : classe d'actif, compte, étiquettes, type de
      stop et réglages de risque.

**Corrections apportées au passage**
- 🐛 **Devises étrangères** : toute valeur hors États-Unis était comptée comme
      cotée en euro. Londres (GBP) et la Suisse (CHF) étaient donc surévaluées
      d'environ 15 %. Le taux est désormais récupéré pour chaque devise, et un
      taux introuvable est signalé au lieu d'être ignoré.
- 🐛 **`interface.html` inutilisable** : une apostrophe non échappée dans
      « Échec de l'analyse » fermait la chaîne JavaScript et provoquait une
      `SyntaxError` qui empêchait *tout* le script de s'exécuter, connexion
      comprise.
- 🐛 **Plus-values réalisées effacées** : enregistrer le portefeuille depuis
      l'interface réécrivait le fichier de profil sans le tableau `closed`.
- 🐛 **Thème clair imposé** : la page suivait `prefers-color-scheme` et
      s'affichait sur fond blanc depuis un appareil en mode clair. Le fond bleu
      nuit est désormais le défaut ; le bouton de bascule reste disponible.

### v7.4 (2026-08)
- ✅ Contexte obligataire : taux 10 ans US (UST) et français (OAT), niveau,
      variation du jour en points de base, tendance sur un mois, écart OAT-UST

### v5.1 (2026-05-13)
- ✅ Assignation stricte des clés API par spécialité (AlphaVantage → forex, TwelveData → US, EODHD → EU/indices, Finnhub → sentiment/consensus)
- ✅ Vérification quota journalier avant chaque appel API
- ✅ Cache GitHub comme fallback final si tous les quotas dépassés
- ✅ Suppression de l'affichage des sources dans les cellules du rapport
- ✅ Harmonisation version v5.1 sur tous les fichiers (YAML, HTML, mail)

### v5.0 (2026-05-13)
- ✅ Réaffectation complète des clés API par spécialité
- ✅ Fallback cache GitHub en cas d'échec toutes sources

### v4.1 (2026-05-13)
- ✅ Intégration AlphaVantage comme 4ème source (forex principal)
- ✅ ALPHAVANTAGE_API_KEY ajouté dans le workflow

### v3.2 (2026-05-12)
- ✅ Intégration TwelveData comme source principale cours US + EUR/USD
- ✅ Batch unique TwelveData (1 requête = portefeuille + watchlist US)
- ✅ Protocole validation croisée 3 sources avec détection divergence > 2%
- ✅ Médiane automatique en cas de divergence
- ✅ Rate limiting TwelveData géré automatiquement (8 crédits/min)
