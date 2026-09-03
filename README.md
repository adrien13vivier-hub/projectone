# 📊 Portfolio Analyzer v8.1

Rapport quotidien automatisé à **16h00 Paris (CEST)** via GitHub Actions — 4 sources de données avec validation croisée et fallback en cascade.

## Ce que fait le programme

Un rapport quotidien qui répond à quatre questions, dans cet ordre :

| Question | Section du rapport |
|----------|--------------------|
| Dans quel décor je navigue ? | **Contexte économique** — indices, taux 10 ans US/OAT, manchettes |
| Est-ce qu'une position est sortie de sa zone ? | **Stops & Alertes** |
| À quoi je suis exposé ? | **Répartition** — classe, devise, compte, étiquette |
| Que valent mes titres, un par un ? | **Analyse par valeur** + **Synthèse** |

---

## Gestion du risque (v8)

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

Empiriquement, une grande capitalisation stable ressort autour de 12-15 %, une
valeur très volatile autour de 30 %, le bitcoin autour de 38 %.

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

---

## Architecture des sources

```
EUR/USD (forex)  : AlphaVantage (principal) → cache session
COURS US         : TwelveData (batch par 6) → EODHD real-time → cache
COURS EU (.PA)   : EODHD (principal) → cache
INDICES MACRO    : EODHD → Finnhub → cache
SENTIMENT presse : Finnhub /news-sentiment → analyse lexicale EODHD
CONSENSUS        : Finnhub /recommendation → EODHD fundamentals
NEWS sociétés    : EODHD → Finnhub
```

## Protocole de validation croisée

Si deux sources retournent un écart > **2%** sur un même cours :
- ⚠️ Divergence signalée dans le rapport (section dédiée)
- La **médiane** des deux valeurs est utilisée automatiquement
- Un email d'alerte est envoyé immédiatement

## Secrets GitHub requis (4)

| Nom | Rôle |
|-----|------|
| `ALPHAVANTAGE_API_KEY` | Taux EUR/USD (forex principal) |
| `EODHD_API_KEY` | Cours Euronext, indices, news, fundamentals |
| `TWELVEDATA_API_KEY` | Cours US en temps réel (batch) |
| `FINNHUB_API_KEY` | Sentiment presse, consensus analystes |

**Settings → Secrets and variables → Actions → New repository secret**

### Secrets SMTP optionnels — alerte de franchissement de stop

Sans ces secrets, **rien n'est envoyé** et ce n'est pas une erreur : l'alerte
reste visible dans la section « Stops & Alertes » du rapport. Avec eux, un
courriel part le jour où une position clôture sous son stop, et uniquement ce
jour-là.

Le port 465 (SMTPS) est recommandé. Sur un autre port, STARTTLS est exigé dès
qu'un identifiant est fourni : le programme refuse d'envoyer un mot de passe en
clair, quitte à ne pas envoyer l'alerte.


| Nom | Description |
|-----|-------------|
| `MAIL_SERVER` | Serveur SMTP (ex: smtp.gmail.com) |
| `MAIL_PORT` | Port SMTP (ex: 465) |
| `MAIL_USERNAME` | Adresse email expéditeur |
| `MAIL_PASSWORD` | Mot de passe / App password |
| `MAIL_FROM` | Adresse affichée en expéditeur |
| `MAIL_TO` | Adresse destinataire |

## Limites des plans gratuits

| API | Quota gratuit | Usages dans le projet |
|-----|---------------|-----------------------|
| **AlphaVantage** | 25 req/jour | 1 req/run (EUR/USD) |
| **TwelveData** | 800 req/jour · 8 req/min | ~6 req/run (cours US batch) |
| **EODHD** | 100 000 req/jour | Cours EU + indices + news + fundamentals |
| **Finnhub** | 60 req/min | Sentiment + consensus |

> **Note** : TwelveData plan Free couvre uniquement les bourses US et crypto. Les actions Euronext (`.PA`, `.AS`, etc.) et les indices (CAC40, SPX) nécessitent le plan Grow (29$/mois).

## Algorithme de décision v5.1

| Composante | Poids |
|------------|-------|
| Prix vs. prix de revient (historique) | 30% |
| Tendance historique (performance mensuelle) | 30% |
| Sentiment presse + consensus analystes | 20% |
| Consensus analystes | 20% |

| Score | Recommandation |
|-------|----------------|
| ≥ 7.5 | 🟢 ACHAT FORT |
| ≥ 6.0 | 🔵 ACHAT MODÉRÉ |
| ≥ 4.5 | 🟡 GARDER |
| ≥ 3.0 | 🟠 À ÉVITER |
| < 3.0 | 🔴 VENDRE |

## Fichiers générés

| Fichier | Description |
|---------|-------------|
| `reports/<user>/daily_report.md` | Rapport Markdown complet du jour |
| `reports/<user>/stops_state.json` | Plus hauts atteints + armement des alertes |
| `reports/charts/*.png` | Graphiques de performance mensuels |
| `reports/history.csv` | Historique des PnL quotidiens |
| `docs/index.html` | Rapport HTML interactif (Cloudflare Pages) |
| `cache/session_cache.json` | Cache fallback des derniers cours valides |

## Changelog

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
