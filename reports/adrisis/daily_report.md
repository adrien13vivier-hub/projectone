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

**Stops actifs : 0** | **Franchis : 0** | **Sans stop : 4** | Nouvelles alertes du jour : 0

Règle de franchissement : la CLÔTURE du jour passe sous le niveau. Une seule alerte par franchissement ; le déclencheur se ré-arme quand le cours repasse au-dessus. Les stops suiveurs et VQ montent avec le cours et ne redescendent jamais.

| Valeur | Compte | Type | Configuration | Niveau | Cloture | Distance | Statut |
|--------|--------|------|---------------|--------|---------|----------|--------|
| S&P500 | PEA CA | Aucun | Aucun stop défini | -- | 60.62 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.16 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.16 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.16 | -- | Aucun |

### Dimensionnement des positions

Capital de référence : **780.33 EUR** (valeurs cotées + liquidités, hors actifs illiquides). Risque par idée : **1 %**, soit **7.80 EUR**. Plafond de poids par ligne : 15 %.

Formule : montant = (capital x risque) / distance au stop. Deux valeurs de volatilités différentes reçoivent ainsi le même risque, pas le même montant. Sans stop exploitable : montant = capital x budget de volatilité (2 %) / volatilité de la ligne.

| Valeur | Volatilite an. | Amplitude/jour | VQ | Distance stop | Taille suggeree | Detenu | Ecart |
|--------|----------------|----------------|-----|---------------|-----------------|--------|-------|
| S&P500 | 11.2 % (Faible, sur 1 an) | 0.42 % | 8.0 % | -- | 117.05 EUR (dimensionné par la volatilité, plafonné à 15 % du capital) | 121.24 EUR | 4.19 EUR |
| MSCI WORLD | 10.7 % (Faible, sur 1 an) | 0.44 % | 8.0 % | -- | 117.05 EUR (dimensionné par la volatilité, plafonné à 15 % du capital) | 659.09 EUR (3 lignes) | 542.04 EUR |

*« Amplitude/jour » : de combien la valeur bouge en moyenne d'une cloture a l'autre. C'est la lecture concrete de la volatilite.*

*« Volatilite an. » : ecart-type des variations journalieres sur 1 an d'historique (ou depuis la cotation pour un titre recent), annualise ; la profondeur reelle est indiquee dans la colonne. « VQ » = 0,65 x cette volatilite, borne entre 8 % et 40 %.*

*« Écart » = ce qui est détenu moins ce que le budget de risque justifierait. Positif : la ligne est plus grosse que le risque accepté. Ce n'est pas un ordre de vente, c'est un écart à expliquer.*


### Exposition corrélée

**Corrélation moyenne du portefeuille : +97.7 %** (Très élevée (le portefeuille bouge comme un bloc)) -- calculée sur 1 paire(s) de lignes (2 ligne(s) cotée(s) avec un historique suffisant). Étendue observée : de +97.7 % à +97.7 %.

*Plus ce chiffre est proche de 0, plus les lignes bougent indépendamment les unes des autres -- une diversification qui se voit dans les mouvements réels, pas seulement dans les étiquettes de classe d'actif ou de secteur. Un chiffre élevé et négatif est aussi une forme de concentration, sur le pari inverse.*

Lignes dont les variations à 3 mois sont fortement corrélées entre elles (mesurées sur 1 an d'historique) -- prises ensemble, elles pèsent plus qu'un plafond de poids par ligne ne le laisse penser. Un signal d'attention, pas une prévision.

| Groupe | Poids cumulé | Alerte |
|--------|--------------|--------|
| S&P500, MSCI WORLD | 100.00 % | Oui |

*Seuil de corrélation : 0.70. Seuil d'alerte sur le poids cumulé : 25 %.*


---

## Repartition

**Par classe d'actif**

| Poste | Montant | Part |
|-------|---------|------|
| ETF / Fonds | 780.33 EUR | 100.0% |

*Un actif peut porter plusieurs étiquettes : la somme des parts par étiquette peut dépasser 100 %.*


---

## Fiabilite des Notes

*Cette section mesure la valeur PASSEE de la note ; elle ne la modifie pas et ne predit rien. Une esperance historique n'est pas une promesse.*

**Apprentissage mutualise** : calibre sur 234 titre(s) : ceux des profils participants et un univers de reference d'environ 220 actions (US et zone euro, 11 secteurs) note chaque semaine. Seuls le titre, la date, la note et le resultat sont partages -- jamais l'identite, les quantites ni les prix de revient.

**Snapshots : 846** (dont 381 herites de history.csv) | **Reconstitues (amorcage) : 4662** | **Clotures : 568** | **Invalides : 0** | Version de la note : `v14-5fd53e`

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
| S&P500 | 8.13/10 | +1.6% | [-0.2 ; +3.9] | 50% | elevee | 110 | global |
| MSCI WORLD | 7.72/10 | +1.6% | [-0.2 ; +3.9] | 50% | elevee | 110 | global |
| MSCI WORLD | 7.72/10 | +1.6% | [-0.2 ; +3.9] | 50% | elevee | 110 | global |
| MSCI WORLD | 7.72/10 | +1.6% | [-0.2 ; +3.9] | 50% | elevee | 110 | global |

**Modele : non active** -- historique insuffisant : 0/250 observations closes avec sous-notes. La calibration statistique ci-dessus reste la seule prevision affichee.


---

## Analyse par Valeur

### S&P500 `PSP5.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 60.62 EUR | v -0.93% | 121.24 EUR | + +5.50 EUR (+4.8%) | + +4.31 EUR (+3.7%) | **8.13/10** (100%) | NOTE INCOMPLÈTE (peu de critères) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.8/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +5.0% | 3M +5.7% | 6M +14.8% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche >= 7,5 a valu +1.6% de surperformance sectorielle a 60 seances, IC 95 % [-0.2 ; +3.9], P(surperf.) 50% -- confiance elevee, 110 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 8.1/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.8. Momentum HAUSSIER. Position : +4.31 EUR (+3.7%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.16 EUR | v -0.73% | 214.92 EUR | + +11.82 EUR (+5.8%) | + +9.73 EUR (+4.8%) | **7.72/10** (100%) | NOTE INCOMPLÈTE (peu de critères) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +3.9% | 3M +4.6% | 6M +12.4% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche >= 7,5 a valu +1.6% de surperformance sectorielle a 60 seances, IC 95 % [-0.2 ; +3.9], P(surperf.) 50% -- confiance elevee, 110 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +9.73 EUR (+4.8%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.16 EUR | v -0.73% | 429.84 EUR | + +34.44 EUR (+8.7%) | + +30.47 EUR (+7.7%) | **7.72/10** (100%) | NOTE INCOMPLÈTE (peu de critères) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +3.9% | 3M +4.6% | 6M +12.4% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche >= 7,5 a valu +1.6% de surperformance sectorielle a 60 seances, IC 95 % [-0.2 ; +3.9], P(surperf.) 50% -- confiance elevee, 110 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +30.47 EUR (+7.7%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.16 EUR | v -0.73% | 14.33 EUR | + +1.37 EUR (+10.6%) | + +1.24 EUR (+9.6%) | **7.72/10** (100%) | NOTE INCOMPLÈTE (peu de critères) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +3.9% | 3M +4.6% | 6M +12.4% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche >= 7,5 a valu +1.6% de surperformance sectorielle a 60 seances, IC 95 % [-0.2 ; +3.9], P(surperf.) 50% -- confiance elevee, 110 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +1.24 EUR (+9.6%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

## Synthese Portefeuille

| Valeur | Cours EUR | VM EUR | P&L Brut | P&L Net | Note | Conf. | Niveau |
|--------|-----------|--------|----------|---------|------|-------|---------|
| S&P500 | 60.62 | 121.24 | +5.50 (+4.8%) | +4.31 (+3.7%) | 8.13/10 | 100% | NOTE INCOMPLÈTE (peu de critères) |
| MSCI WORLD | 7.16 | 214.92 | +11.82 (+5.8%) | +9.73 (+4.8%) | 7.72/10 | 100% | NOTE INCOMPLÈTE (peu de critères) |
| MSCI WORLD | 7.16 | 429.84 | +34.44 (+8.7%) | +30.47 (+7.7%) | 7.72/10 | 100% | NOTE INCOMPLÈTE (peu de critères) |
| MSCI WORLD | 7.16 | 14.33 | +1.37 (+10.6%) | +1.24 (+9.6%) | 7.72/10 | 100% | NOTE INCOMPLÈTE (peu de critères) |
| **TOTAL** | — | **780.33** | **+53.13 (+7.3%)** | **+45.75 (+6.3%)** | — | — | — |

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

**Quotas API utilisés :** {'alphavantage': '1/20', 'twelvedata': '2/780', 'eodhd': '54/600', 'finnhub': '5/3000'}

**Profil :** adrisis | **Courtier :** Autre / personnalisé
