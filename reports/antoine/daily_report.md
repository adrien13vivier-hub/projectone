# Rapport de Portefeuille v7.5 -- 16/10/2026 01:15 (Paris)

---

## Contexte Economique

**Tendance : Neutre** | Score macro : 5.55/10
**EUR/USD :** 1 EUR = 1.1217 USD

| Indice | Variation | Cours |
|--------|-----------|-------|
| S&P 500 | ^ +0.33% | 7 744.06 |
| CAC 40 | ^ +0.78% | 7 934.70 |

**Taux souverains 10 ans :**

| Taux | Variation | Niveau | Sur 1 mois |
|------|-----------|--------|------------|
| UST 10 ans (US) | -- | 5.07% | -- |
| OAT 10 ans (FR) | -- | 4.79% | -- |
| Ecart OAT - UST | -- | -28 pb | -- |

**Manchettes macro :**

- Yemen's Houthis hit palace in Aden, coalition details attacks on Saudi infrastructure - Reuters
- KFC to switch to Coca-Cola beverages in U.S. restaurants for the first time in decades
- Nvidia and Cisco confirm multimillion-dollar donations to Trump's White House ballroom
- Some 'classic' money advice is actually pretty new—and not all of it is worthwhile, says historian
- Hezbollah says it owned confiscated explosives, meant to attack Israel - Reuters

---

## Stops et Alertes

**Stops actifs : 0** | **Franchis : 0** | **Sans stop : 1** | Nouvelles alertes du jour : 0

Règle de franchissement : la CLÔTURE du jour passe sous le niveau. Une seule alerte par franchissement ; le déclencheur se ré-arme quand le cours repasse au-dessus. Les stops suiveurs et VQ montent avec le cours et ne redescendent jamais.

| Valeur | Compte | Type | Configuration | Niveau | Cloture | Distance | Statut |
|--------|--------|------|---------------|--------|---------|----------|--------|
| TotalEnergies | -- | Aucun | Aucun stop défini | -- | 78.89 | -- | Aucun |

### Dimensionnement des positions

Capital de référence : **6 311.34 EUR** (valeurs cotées + liquidités, hors actifs illiquides). Risque par idée : **1 %**, soit **63.11 EUR**. Plafond de poids par ligne : 15 %.

Formule : montant = (capital x risque) / distance au stop. Deux valeurs de volatilités différentes reçoivent ainsi le même risque, pas le même montant. Sans stop exploitable : montant = capital x budget de volatilité (2 %) / volatilité de la ligne.

| Valeur | Volatilite an. | Amplitude/jour | VQ | Distance stop | Taille suggeree | Detenu | Ecart |
|--------|----------------|----------------|-----|---------------|-----------------|--------|-------|
| TotalEnergies | 24.4 % (Modérée, sur 1 an) | 1.04 % | 15.9 % | -- | 516.48 EUR (dimensionné par la volatilité) | 6 311.34 EUR | 5 794.86 EUR |

*« Amplitude/jour » : de combien la valeur bouge en moyenne d'une cloture a l'autre. C'est la lecture concrete de la volatilite.*

*« Volatilite an. » : ecart-type des variations journalieres sur 1 an d'historique (ou depuis la cotation pour un titre recent), annualise ; la profondeur reelle est indiquee dans la colonne. « VQ » = 0,65 x cette volatilite, borne entre 8 % et 40 %.*

*« Écart » = ce qui est détenu moins ce que le budget de risque justifierait. Positif : la ligne est plus grosse que le risque accepté. Ce n'est pas un ordre de vente, c'est un écart à expliquer.*


### Exposition corrélée

Aucun regroupement de lignes fortement corrélées (seuil 0.70) détecté sur l'historique disponible. *Ceci ne garantit rien sur la corrélation future : seul le passé récent est mesuré.*


---

## Repartition

**Par classe d'actif**

| Poste | Montant | Part |
|-------|---------|------|
| Actions | 6 311.34 EUR | 100.0% |

*Un actif peut porter plusieurs étiquettes : la somme des parts par étiquette peut dépasser 100 %.*


---

## Fiabilite des Notes

*Cette section mesure la valeur PASSEE de la note ; elle ne la modifie pas et ne predit rien. Une esperance historique n'est pas une promesse.*

**Apprentissage mutualise** : calibre sur 234 titre(s) : ceux des profils participants et un univers de reference d'environ 220 actions (US et zone euro, 11 secteurs) note chaque semaine. Seuls le titre, la date, la note et le resultat sont partages -- jamais l'identite, les quantites ni les prix de revient.

**Snapshots : 847** (dont 381 herites de history.csv) | **Reconstitues (amorcage) : 4662** | **Clotures : 568** | **Invalides : 0** | Version de la note : `v14-5fd53e`

### Notes par tranche -- horizon 60 seances, cible : surperformance sectorielle

*Dont 1472 observation(s) independante(s) RECONSTITUEE(S) sur 1472 : notes recalculees sur le passe (actions US, comptes dates par publication, sans l'avis des analystes, biais de selection retire). Elles s'effacent d'elles-memes quand les vraies notes atteignent 60 observations independantes.*

| Tranche | N | N indep. | Surperf. moyenne | Mediane | % positifs | IC 95 % | Esperance calibree | Confiance |
|---------|---|----------|------------------|---------|------------|---------|--------------------|-----------|
| < 3 (NOTE TRÈS FAIBLE) | 34 | 21 | +3.7% | +1.1% | 53% | [-1.8 ; +9.2] | +2.1% | faible |
| 3 - 4,5 (NOTE FAIBLE) | 340 | 189 | +0.2% | -0.1% | 49% | [-2.0 ; +2.5] | +0.2% | elevee |
| 4,5 - 6 (NOTE MOYENNE) | 1827 | 844 | +0.0% | -0.6% | 47% | [-0.8 ; +0.8] | +0.0% | elevee |
| 6 - 7,5 (NOTE SOLIDE) | 2012 | 879 | -0.3% | -1.2% | 45% | [-1.0 ; +0.4] | -0.3% | elevee |
| >= 7,5 (NOTE ÉLEVÉE) | 201 | 110 | +1.9% | +0.5% | 52% | [-0.2 ; +3.9] | +1.6% | elevee |

**Lien note -> surperformance :** IC de rang -0.01 (echantillon independant : -0.04) | pente -0.34 pt par point de note | 123 titre(s) sur 36 seance(s).

| Secteur | N | N indep. | Surperf. moyenne | % positifs | IC de rang |
|---------|---|----------|------------------|------------|------------|
| Communication Services | 504 | 168 | -0.6% | 44% | -0.11 |
| Consumer Discretionary | 360 | 120 | -0.4% | 48% | -0.04 |
| Consumer Staples | 360 | 120 | +0.6% | 49% | +0.07 |
| Energy | 324 | 108 | -0.9% | 37% | -0.09 |
| Financials | 346 | 116 | +2.5% | 57% | +0.04 |
| Health Care | 360 | 120 | +0.6% | 51% | -0.04 |
| Industrials | 360 | 120 | +0.5% | 49% | -0.03 |
| Information Technology | 360 | 120 | -0.0% | 44% | +0.02 |
| Materials | 504 | 168 | +0.5% | 47% | +0.02 |
| Real Estate | 432 | 144 | -0.4% | 46% | +0.05 |
| Utilities | 504 | 168 | -1.6% | 41% | -0.04 |

### Quel horizon colle le mieux a la note ?

| Horizon (seances) | N indep. | IC de rang | Notes >= 7,5 | Notes < 4,5 | Cible |
|-------------------|----------|------------|--------------|-------------|-------|
| 20 | 4662 | -0.02 | +0.1% | +0.7% | surperformance sectorielle |
| 60 | 1472 | -0.01 | +1.9% | +2.0% | surperformance sectorielle |
| 120 | 736 | +0.04 | +5.8% | +2.0% | surperformance sectorielle |
| 252 | 245 | +0.00 | +9.7% | +5.4% | surperformance sectorielle |

### Fiabilite par position (horizon 60 seances)

| Valeur | Note | Surperf. attendue | IC 95 % | P(surperf.) | Confiance | Echantillon | Cohorte |
|--------|------|-------------------|---------|-------------|-----------|-------------|---------|
| TotalEnergies | 7.59/10 | +1.6% | [-0.2 ; +3.9] | 50% | elevee | 110 | global |

**Modele : non active** -- historique insuffisant : 0/250 observations closes avec sous-notes. La calibration statistique ci-dessus reste la seule prevision affichee.


---

## Analyse par Valeur

### TotalEnergies `TTE.US`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 78.89 EUR | v -1.28% | 6311.34 EUR | - -73688.66 EUR (-92.1%) | - -73792.23 EUR (-92.2%) | **7.59/10** (100%) | NOTE ÉLEVÉE |

**Actualite recente :** *(source : RSS Yahoo Finance)*

> TotalEnergies (ENXTPA:TTE) Flags Record Q3 Production And LNG Driven Profit Upswing | Exxon vs. TotalEnergies: Which Dividend Stock Pays You More in 10 Years? | Better Dividend Stock: Chevron vs. TotalEnergies

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Valorisation | 9.0/10 | 24% |
| Sante financiere | 6.4/10 | 19% |
| Croissance | 9.4/10 | 16% |
| Momentum | 6.3/10 | 21% |
| Consensus | 6.6/10 | 15% |
| Risque | 7.9/10 | 5% |

**Fondamentaux :** PER 11.0 | PEG 0.7 | EV/EBITDA 5.8 | P/B 1.5 | Marge nette 9.1% | ROE 14.5% | Croiss. CA 27.8% | Beta 0.1 *(source : Yahoo Finance)*
**Consensus analystes :** SB:6 B:13 H:10 S:4 SS:0 *(source : Finnhub)*
**Perf. historique :** 1M -3.9% | 3M +10.0% | 6M +6.3% -- NEUTRE *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche >= 7,5 a valu +1.6% de surperformance sectorielle a 60 seances, IC 95 % [-0.2 ; +3.9], P(surperf.) 50% -- confiance elevee, 110 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 7.6/10 (confiance 100%). Points forts : croissance 9.4, valorisation 9.0. Momentum NEUTRE. Position : -73792.23 EUR (-92.2%) apres frais.

---

## Synthese Portefeuille

| Valeur | Cours EUR | VM EUR | P&L Brut | P&L Net | Note | Conf. | Niveau |
|--------|-----------|--------|----------|---------|------|-------|---------|
| TotalEnergies | 78.89 | 6311.34 | -73688.66 (-92.1%) | -73792.23 (-92.2%) | 7.59/10 | 100% | NOTE ÉLEVÉE |
| **TOTAL** | — | **6311.34** | **-73688.66 (-92.1%)** | **-73792.23 (-92.2%)** | — | — | — |

---

## Watchlist

| Valeur | Secteur | Cours EUR | Variation | Actualite |
|--------|---------|-----------|-----------|-----------|
| TotalEnergies | énergie | 80.21 EUR | ^ +0.05% | TotalEnergies (ENXTPA:TTE) Flags Record Q3 Production And LNG Driven Profit Upsw… |

---

## Sources et Quotas

- **EUR/USD** : AlphaVantage
- **S&P 500** : EODHD
- **CAC 40** : EODHD
- **UST 10 ans (US)** : EODHD
- **OAT 10 ans (FR)** : EODHD
- **TTE.US** : cours: TwelveData, consensus: Finnhub, historique: EODHD, synthese: RSS Yahoo Finance, fondamentaux: Yahoo Finance

**Quotas API utilisés :** {'alphavantage': '1/20', 'twelvedata': '3/780', 'eodhd': '55/600', 'finnhub': '6/3000'}

**Profil :** antoine | **Courtier :** Autre / personnalisé
