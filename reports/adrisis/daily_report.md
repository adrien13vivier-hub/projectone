# Rapport de Portefeuille v7.5 -- 07/10/2026 02:05 (Paris)

---

## Contexte Economique

**Tendance : Neutre** | Score macro : 5.49/10
**EUR/USD :** 1 EUR = 1.1256 USD

| Indice | Variation | Cours |
|--------|-----------|-------|
| S&P 500 | ^ +0.58% | 7 818.93 |
| CAC 40 | ^ +0.40% | 7 865.07 |

**Taux souverains 10 ans :**

| Taux | Variation | Niveau | Sur 1 mois |
|------|-----------|--------|------------|
| UST 10 ans (US) | -- | 5.29% | -- |
| OAT 10 ans (FR) | -- | 4.75% | -- |
| Ecart OAT - UST | -- | -53 pb | -- |

**Manchettes macro :**

- Notice of the Annual General Meeting of Akcinė prekybos bendrovė “APRANGA” shareholders
- Pranešimas apie Akcinės prekybos bendrovės „APRANGA“ šaukiamą eilinį visuotinį akcininkų susirinkimą
- BIC discontinues Rocketbook and its Skin Creative activities
- BIC discontinue les activités de Rocketbook et de Skin Creative
- BIC annonce la nomination d’un nouveau Directeur Financier

---

## Stops et Alertes

**Stops actifs : 0** | **Franchis : 0** | **Sans stop : 4** | Nouvelles alertes du jour : 0

Règle de franchissement : la CLÔTURE du jour passe sous le niveau. Une seule alerte par franchissement ; le déclencheur se ré-arme quand le cours repasse au-dessus. Les stops suiveurs et VQ montent avec le cours et ne redescendent jamais.

| Valeur | Compte | Type | Configuration | Niveau | Cloture | Distance | Statut |
|--------|--------|------|---------------|--------|---------|----------|--------|
| S&P500 | PEA CA | Aucun | Aucun stop défini | -- | 61.18 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.23 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.23 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.23 | -- | Aucun |

### Dimensionnement des positions

Capital de référence : **787.24 EUR** (valeurs cotées + liquidités, hors actifs illiquides). Risque par idée : **1 %**, soit **7.87 EUR**. Plafond de poids par ligne : 15 %.

Formule : montant = (capital x risque) / distance au stop. Deux valeurs de volatilités différentes reçoivent ainsi le même risque, pas le même montant. Sans stop exploitable : montant = capital x budget de volatilité (2 %) / volatilité de la ligne.

| Valeur | Volatilite an. | Amplitude/jour | VQ | Distance stop | Taille suggeree | Detenu | Ecart |
|--------|----------------|----------------|-----|---------------|-----------------|--------|-------|
| S&P500 | 11.4 % (Faible, sur 1 an) | 0.50 % | 8.0 % | -- | 118.09 EUR (dimensionné par la volatilité, plafonné à 15 % du capital) | 122.36 EUR | 4.27 EUR |
| MSCI WORLD | 11.0 % (Faible, sur 1 an) | 0.53 % | 8.0 % | -- | 118.09 EUR (dimensionné par la volatilité, plafonné à 15 % du capital) | 664.88 EUR (3 lignes) | 546.79 EUR |

*« Amplitude/jour » : de combien la valeur bouge en moyenne d'une cloture a l'autre. C'est la lecture concrete de la volatilite.*

*« Volatilite an. » : ecart-type des variations journalieres sur 1 an d'historique (ou depuis la cotation pour un titre recent), annualise ; la profondeur reelle est indiquee dans la colonne. « VQ » = 0,65 x cette volatilite, borne entre 8 % et 40 %.*

*« Écart » = ce qui est détenu moins ce que le budget de risque justifierait. Positif : la ligne est plus grosse que le risque accepté. Ce n'est pas un ordre de vente, c'est un écart à expliquer.*


### Exposition corrélée

**Corrélation moyenne du portefeuille : +97.8 %** (Très élevée (le portefeuille bouge comme un bloc)) -- calculée sur 1 paire(s) de lignes (2 ligne(s) cotée(s) avec un historique suffisant). Étendue observée : de +97.8 % à +97.8 %.

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
| ETF / Fonds | 787.24 EUR | 100.0% |

*Un actif peut porter plusieurs étiquettes : la somme des parts par étiquette peut dépasser 100 %.*


---

## Fiabilite des Notes

*Cette section mesure la valeur PASSEE de la note ; elle ne la modifie pas et ne predit rien. Une esperance historique n'est pas une promesse.*

**Apprentissage mutualise** : calibre sur 21 titre(s) suivis par l'ensemble des profils participants. Seuls le titre, la date, la note et le resultat sont partages -- jamais l'identite, les quantites ni les prix de revient.

**Snapshots : 457** (dont 381 herites de history.csv) | **Clotures : 509** | **Invalides : 0** | Version de la note : `v14-5fd53e`

### Notes par tranche -- horizon 60 seances, cible : surperformance vs marche

*Echantillon inclut la cohorte HERITEE (formules anterieures, reconstituee depuis history.csv) : confiance plafonnee a "faible".*

| Tranche | N | N indep. | Surperf. moyenne | Mediane | % positifs | IC 95 % | Esperance calibree | Confiance |
|---------|---|----------|------------------|---------|------------|---------|--------------------|-----------|
| < 3 (VENDRE) | 32 | 1 | -17.5% | -16.3% | 0% | -- | -- | insuffisante |
| 3 - 4,5 (A EVITER) | 16 | 2 | +35.3% | +38.7% | 100% | -- | -- | insuffisante |
| 4,5 - 6 (GARDER) | 77 | 5 | +15.6% | +13.3% | 91% | -- | -- | insuffisante |
| 6 - 7,5 (ACHAT MODERE) | 49 | 3 | +0.1% | -2.7% | 47% | -- | -- | insuffisante |
| >= 7,5 (ACHAT FORT) | 10 | 1 | -27.1% | -27.4% | 0% | -- | -- | insuffisante |

**Lien note -> surperformance :** IC de rang -0.10 (echantillon independant : +0.14) | pente -4.16 pt par point de note | 6 titre(s) sur 37 seance(s).

| Secteur | N | N indep. | Surperf. moyenne | % positifs | IC de rang |
|---------|---|----------|------------------|------------|------------|
| Financials | 36 | 1 | +8.8% | 100% | -0.35 |
| Health Care | 36 | 1 | -21.1% | 0% | -0.87 |
| Information Technology | 33 | 1 | -15.9% | 12% | -0.69 |

*Ventilation par region, a titre indicatif (n'entre pas dans le calcul de l'esperance calibree) :*

| Region | N | N indep. | Surperf. moyenne | % positifs |
|--------|---|----------|------------------|------------|
| EUROPE | 108 | 3 | +5.1% | 67% |
| US | 76 | 3 | +5.1% | 49% |

### Quel horizon colle le mieux a la note ?

| Horizon (seances) | N indep. | IC de rang | Notes >= 7,5 | Notes < 4,5 | Cible |
|-------------------|----------|------------|--------------|-------------|-------|
| 20 | 15 | -0.17 | -5.5% | -5.6% | surperformance sectorielle |
| 60 | 6 | -0.10 | -27.1% | +8.9% | surperformance vs marche |

### Fiabilite par position (horizon 60 seances)

| Valeur | Note | Surperf. attendue | IC 95 % | P(surperf.) | Confiance | Echantillon | Cohorte |
|--------|------|-------------------|---------|-------------|-----------|-------------|---------|
| S&P500 | 8.13/10 | n/d | -- | -- | insuffisante | 1 | global + heritee |
| MSCI WORLD | 7.72/10 | n/d | -- | -- | insuffisante | 1 | global + heritee |
| MSCI WORLD | 7.72/10 | n/d | -- | -- | insuffisante | 1 | global + heritee |
| MSCI WORLD | 7.72/10 | n/d | -- | -- | insuffisante | 1 | global + heritee |

**Modele : non active** -- historique insuffisant : 0/250 observations closes avec sous-notes. La calibration statistique ci-dessus reste la seule prevision affichee.


---

## Analyse par Valeur

### S&P500 `PSP5.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 61.18 EUR | ^ +1.53% | 122.36 EUR | + +6.62 EUR (+5.7%) | + +5.43 EUR (+4.7%) | **8.13/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.8/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +5.0% | 3M +6.9% | 6M +19.9% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (1 observation(s) independante(s) dans la tranche >= 7,5) -- aucune esperance publiee.

**Justification :** Note 8.1/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.8. Momentum HAUSSIER. Position : +5.43 EUR (+4.7%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.23 EUR | ^ +1.39% | 216.81 EUR | + +13.71 EUR (+6.8%) | + +11.61 EUR (+5.7%) | **7.72/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +3.5% | 3M +5.9% | 6M +16.7% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (1 observation(s) independante(s) dans la tranche >= 7,5) -- aucune esperance publiee.

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +11.61 EUR (+5.7%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.23 EUR | ^ +1.39% | 433.62 EUR | + +38.22 EUR (+9.7%) | + +34.25 EUR (+8.7%) | **7.72/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +3.5% | 3M +5.9% | 6M +16.7% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (1 observation(s) independante(s) dans la tranche >= 7,5) -- aucune esperance publiee.

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +34.25 EUR (+8.7%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.23 EUR | ^ +1.39% | 14.45 EUR | + +1.49 EUR (+11.5%) | + +1.36 EUR (+10.5%) | **7.72/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +3.5% | 3M +5.9% | 6M +16.7% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (1 observation(s) independante(s) dans la tranche >= 7,5) -- aucune esperance publiee.

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +1.36 EUR (+10.5%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

## Synthese Portefeuille

| Valeur | Cours EUR | VM EUR | P&L Brut | P&L Net | Note | Conf. | Recomm. |
|--------|-----------|--------|----------|---------|------|-------|---------|
| S&P500 | 61.18 | 122.36 | +6.62 (+5.7%) | +5.43 (+4.7%) | 8.13/10 | 100% | A EXAMINER (peu de criteres) |
| MSCI WORLD | 7.23 | 216.81 | +13.71 (+6.8%) | +11.61 (+5.7%) | 7.72/10 | 100% | A EXAMINER (peu de criteres) |
| MSCI WORLD | 7.23 | 433.62 | +38.22 (+9.7%) | +34.25 (+8.7%) | 7.72/10 | 100% | A EXAMINER (peu de criteres) |
| MSCI WORLD | 7.23 | 14.45 | +1.49 (+11.5%) | +1.36 (+10.5%) | 7.72/10 | 100% | A EXAMINER (peu de criteres) |
| **TOTAL** | — | **787.24** | **+60.04 (+8.3%)** | **+52.65 (+7.2%)** | — | — | — |

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

**Quotas API utilisés :** {'alphavantage': '1/20', 'twelvedata': '2/780', 'eodhd': '51/300', 'finnhub': '4/3000'}

**Profil :** adrisis | **Courtier :** Autre / personnalisé
