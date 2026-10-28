# Rapport de Portefeuille v7.5 -- 28/10/2026 01:42 (Paris)

---

## Contexte Economique

**Tendance : Neutre** | Score macro : 5.55/10
**EUR/USD :** 1 EUR = 1.113 USD

| Indice | Variation | Cours |
|--------|-----------|-------|
| S&P 500 | ^ +0.60% | 7 722.60 |
| CAC 40 | ^ +0.51% | 7 887.14 |

**Taux souverains 10 ans :**

| Taux | Variation | Niveau | Sur 1 mois |
|------|-----------|--------|------------|
| UST 10 ans (US) | -- | 5.00% | -- |
| OAT 10 ans (FR) | -- | 4.92% | -- |
| Ecart OAT - UST | -- | -8 pb | -- |

**Manchettes macro :**

- Pranešimas apie Akcinės prekybos bendrovės „APRANGA“ šaukiamą eilinį visuotinį akcininkų susirinkimą
- Notice of the Annual General Meeting of Akcinė prekybos bendrovė “APRANGA” shareholders
- BIC discontinue les activités de Rocketbook et de Skin Creative
- BIC discontinues Rocketbook and its Skin Creative activities
- BIC annonce la nomination d’un nouveau Directeur Financier

---

## Stops et Alertes

**Stops actifs : 0** | **Franchis : 0** | **Sans stop : 4** | Nouvelles alertes du jour : 0

Règle de franchissement : la CLÔTURE du jour passe sous le niveau. Une seule alerte par franchissement ; le déclencheur se ré-arme quand le cours repasse au-dessus. Les stops suiveurs et VQ montent avec le cours et ne redescendent jamais.

| Valeur | Compte | Type | Configuration | Niveau | Cloture | Distance | Statut |
|--------|--------|------|---------------|--------|---------|----------|--------|
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.21 | -- | Aucun |
| S&P500 | PEA CA | Aucun | Aucun stop défini | -- | 60.98 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.21 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.21 | -- | Aucun |

### Dimensionnement des positions

Capital de référence : **785.28 EUR** (valeurs cotées + liquidités, hors actifs illiquides). Risque par idée : **1 %**, soit **7.85 EUR**. Plafond de poids par ligne : 15 %.

Formule : montant = (capital x risque) / distance au stop. Deux valeurs de volatilités différentes reçoivent ainsi le même risque, pas le même montant. Sans stop exploitable : montant = capital x budget de volatilité (2 %) / volatilité de la ligne.

| Valeur | Volatilite an. | Amplitude/jour | VQ | Distance stop | Taille suggeree | Detenu | Ecart |
|--------|----------------|----------------|-----|---------------|-----------------|--------|-------|
| MSCI WORLD | 10.6 % (Faible, sur 1 an) | 0.42 % | 8.0 % | -- | 117.79 EUR (dimensionné par la volatilité, plafonné à 15 % du capital) | 663.32 EUR (3 lignes) | 545.53 EUR |
| S&P500 | 11.0 % (Faible, sur 1 an) | 0.46 % | 8.0 % | -- | 117.79 EUR (dimensionné par la volatilité, plafonné à 15 % du capital) | 121.96 EUR | 4.17 EUR |

*« Amplitude/jour » : de combien la valeur bouge en moyenne d'une cloture a l'autre. C'est la lecture concrete de la volatilite.*

*« Volatilite an. » : ecart-type des variations journalieres sur 1 an d'historique (ou depuis la cotation pour un titre recent), annualise ; la profondeur reelle est indiquee dans la colonne. « VQ » = 0,65 x cette volatilite, borne entre 8 % et 40 %.*

*« Écart » = ce qui est détenu moins ce que le budget de risque justifierait. Positif : la ligne est plus grosse que le risque accepté. Ce n'est pas un ordre de vente, c'est un écart à expliquer.*


### Exposition corrélée

**Corrélation moyenne du portefeuille : +97.6 %** (Très élevée (le portefeuille bouge comme un bloc)) -- calculée sur 1 paire(s) de lignes (2 ligne(s) cotée(s) avec un historique suffisant). Étendue observée : de +97.6 % à +97.6 %.

*Plus ce chiffre est proche de 0, plus les lignes bougent indépendamment les unes des autres -- une diversification qui se voit dans les mouvements réels, pas seulement dans les étiquettes de classe d'actif ou de secteur. Un chiffre élevé et négatif est aussi une forme de concentration, sur le pari inverse.*

Lignes dont les variations à 3 mois sont fortement corrélées entre elles (mesurées sur 1 an d'historique) -- prises ensemble, elles pèsent plus qu'un plafond de poids par ligne ne le laisse penser. Un signal d'attention, pas une prévision.

| Groupe | Poids cumulé | Alerte |
|--------|--------------|--------|
| MSCI WORLD, S&P500 | 100.00 % | Oui |

*Seuil de corrélation : 0.70. Seuil d'alerte sur le poids cumulé : 25 %.*


---

## Repartition

**Par classe d'actif**

| Poste | Montant | Part |
|-------|---------|------|
| ETF / Fonds | 785.28 EUR | 100.0% |

*Un actif peut porter plusieurs étiquettes : la somme des parts par étiquette peut dépasser 100 %.*


---

## Fiabilite des Notes

*Cette section mesure la valeur PASSEE de la note ; elle ne la modifie pas et ne predit rien. Une esperance historique n'est pas une promesse.*

**Apprentissage mutualise** : calibre sur 235 titre(s) : ceux des profils participants et un univers de reference d'environ 220 actions (US et zone euro, 11 secteurs) note chaque semaine. Seuls le titre, la date, la note et le resultat sont partages -- jamais l'identite, les quantites ni les prix de revient.

**Snapshots : 1371** (dont 381 herites de history.csv) | **Reconstitues (amorcage) : 4662** | **Clotures : 648** | **Invalides : 0** | Version de la note : `v14-5fd53e`

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
| 20 | 4666 | -0.01 | +0.2% | -0.1% | surperformance sectorielle |
| 60 | 1472 | -0.01 | +1.9% | +2.0% | surperformance sectorielle |
| 120 | 736 | +0.04 | +5.8% | +2.0% | surperformance sectorielle |
| 252 | 245 | +0.00 | +9.7% | +5.4% | surperformance sectorielle |

### Fiabilite par position (horizon 60 seances)

| Valeur | Note | Surperf. attendue | IC 95 % | P(surperf.) | Confiance | Echantillon | Cohorte |
|--------|------|-------------------|---------|-------------|-----------|-------------|---------|
| MSCI WORLD | 7.72/10 | +1.6% | [-0.2 ; +3.9] | 50% | elevee | 110 | global |
| S&P500 | 7.72/10 | +1.6% | [-0.2 ; +3.9] | 50% | elevee | 110 | global |
| MSCI WORLD | 7.72/10 | +1.6% | [-0.2 ; +3.9] | 50% | elevee | 110 | global |
| MSCI WORLD | 7.72/10 | +1.6% | [-0.2 ; +3.9] | 50% | elevee | 110 | global |

**Modele : non active** -- historique insuffisant : 0/250 observations closes avec sous-notes. La calibration statistique ci-dessus reste la seule prevision affichee.


---

## Analyse par Valeur

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.21 EUR | ^ +0.81% | 216.30 EUR | + +13.20 EUR (+6.5%) | + +11.10 EUR (+5.5%) | **7.72/10** (100%) | NOTE INCOMPLÈTE (peu de critères) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +2.0% | 3M +5.7% | 6M +12.0% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche >= 7,5 a valu +1.6% de surperformance sectorielle a 60 seances, IC 95 % [-0.2 ; +3.9], P(surperf.) 50% -- confiance elevee, 110 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +11.10 EUR (+5.5%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### S&P500 `PSP5.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 60.98 EUR | ^ +0.93% | 121.96 EUR | + +6.22 EUR (+5.4%) | + +5.03 EUR (+4.3%) | **7.72/10** (100%) | NOTE INCOMPLÈTE (peu de critères) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +2.5% | 3M +7.2% | 6M +13.1% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche >= 7,5 a valu +1.6% de surperformance sectorielle a 60 seances, IC 95 % [-0.2 ; +3.9], P(surperf.) 50% -- confiance elevee, 110 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +5.03 EUR (+4.3%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.21 EUR | ^ +0.81% | 432.60 EUR | + +37.20 EUR (+9.4%) | + +33.23 EUR (+8.4%) | **7.72/10** (100%) | NOTE INCOMPLÈTE (peu de critères) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +2.0% | 3M +5.7% | 6M +12.0% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche >= 7,5 a valu +1.6% de surperformance sectorielle a 60 seances, IC 95 % [-0.2 ; +3.9], P(surperf.) 50% -- confiance elevee, 110 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +33.23 EUR (+8.4%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.21 EUR | ^ +0.81% | 14.42 EUR | + +1.46 EUR (+11.3%) | + +1.33 EUR (+10.3%) | **7.72/10** (100%) | NOTE INCOMPLÈTE (peu de critères) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +2.0% | 3M +5.7% | 6M +12.0% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche >= 7,5 a valu +1.6% de surperformance sectorielle a 60 seances, IC 95 % [-0.2 ; +3.9], P(surperf.) 50% -- confiance elevee, 110 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +1.33 EUR (+10.3%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

## Synthese Portefeuille

| Valeur | Cours EUR | VM EUR | P&L Brut | P&L Net | Note | Conf. | Niveau |
|--------|-----------|--------|----------|---------|------|-------|---------|
| MSCI WORLD | 7.21 | 216.30 | +13.20 (+6.5%) | +11.10 (+5.5%) | 7.72/10 | 100% | NOTE INCOMPLÈTE (peu de critères) |
| S&P500 | 60.98 | 121.96 | +6.22 (+5.4%) | +5.03 (+4.3%) | 7.72/10 | 100% | NOTE INCOMPLÈTE (peu de critères) |
| MSCI WORLD | 7.21 | 432.60 | +37.20 (+9.4%) | +33.23 (+8.4%) | 7.72/10 | 100% | NOTE INCOMPLÈTE (peu de critères) |
| MSCI WORLD | 7.21 | 14.42 | +1.46 (+11.3%) | +1.33 (+10.3%) | 7.72/10 | 100% | NOTE INCOMPLÈTE (peu de critères) |
| **TOTAL** | — | **785.28** | **+58.08 (+8.0%)** | **+50.69 (+7.0%)** | — | — | — |

---

## Watchlist

| Valeur | Secteur | Cours EUR | Variation | Actualite |
|--------|---------|-----------|-----------|-----------|

---

## Sources et Quotas

- **EUR/USD** : AlphaVantage
- **S&P 500** : EODHD
- **CAC 40** : EODHD
- **UST 10 ans (US)** : EODHD
- **OAT 10 ans (FR)** : EODHD
- **WPEA.PA** : cours: EODHD, consensus: sans objet, historique: EODHD, synthese: RSS Yahoo vide, fondamentaux: non applicable (etf)
- **PSP5.PA** : cours: EODHD, consensus: sans objet, historique: EODHD, synthese: RSS Yahoo vide, fondamentaux: non applicable (etf)

**Quotas API utilisés :** {'alphavantage': '1/20', 'twelvedata': '2/780', 'eodhd': '56/600', 'finnhub': '4/3000'}

**Profil :** adrisis | **Courtier :** Autre / personnalisé
