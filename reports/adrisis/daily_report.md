# Rapport de Portefeuille v7.5 -- 03/10/2026 01:59 (Paris)

---

## Contexte Economique

**Tendance : Neutre** | Score macro : 5.76/10
**EUR/USD :** 1 EUR = 1.1257 USD

| Indice | Variation | Cours |
|--------|-----------|-------|
| S&P 500 | ^ +0.73% | 7 722.72 |
| CAC 40 | ^ +0.79% | 7 897.19 |

**Taux souverains 10 ans :**

| Taux | Variation | Niveau | Sur 1 mois |
|------|-----------|--------|------------|
| UST 10 ans (US) | -- | 5.28% | -- |
| OAT 10 ans (FR) | -- | 4.87% | -- |
| Ecart OAT - UST | -- | -42 pb | -- |

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
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.13 | -- | Aucun |
| S&P500 | PEA CA | Aucun | Aucun stop défini | -- | 60.26 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.13 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.13 | -- | Aucun |

### Dimensionnement des positions

Capital de référence : **776.30 EUR** (valeurs cotées + liquidités, hors actifs illiquides). Risque par idée : **1 %**, soit **7.76 EUR**. Plafond de poids par ligne : 15 %.

Formule : montant = (capital x risque) / distance au stop. Deux valeurs de volatilités différentes reçoivent ainsi le même risque, pas le même montant. Sans stop exploitable : montant = capital x budget de volatilité (2 %) / volatilité de la ligne.

| Valeur | Volatilite an. | Amplitude/jour | VQ | Distance stop | Taille suggeree | Detenu | Ecart |
|--------|----------------|----------------|-----|---------------|-----------------|--------|-------|
| MSCI WORLD | 10.9 % (Faible, sur 1 an) | 0.47 % | 8.0 % | -- | 116.44 EUR (dimensionné par la volatilité, plafonné à 15 % du capital) | 655.78 EUR (3 lignes) | 539.34 EUR |
| S&P500 | 11.3 % (Faible, sur 1 an) | 0.45 % | 8.0 % | -- | 116.44 EUR (dimensionné par la volatilité, plafonné à 15 % du capital) | 120.52 EUR | 4.08 EUR |

*« Amplitude/jour » : de combien la valeur bouge en moyenne d'une cloture a l'autre. C'est la lecture concrete de la volatilite.*

*« Volatilite an. » : ecart-type des variations journalieres sur 1 an d'historique (ou depuis la cotation pour un titre recent), annualise ; la profondeur reelle est indiquee dans la colonne. « VQ » = 0,65 x cette volatilite, borne entre 8 % et 40 %.*

*« Écart » = ce qui est détenu moins ce que le budget de risque justifierait. Positif : la ligne est plus grosse que le risque accepté. Ce n'est pas un ordre de vente, c'est un écart à expliquer.*


### Exposition corrélée

**Corrélation moyenne du portefeuille : +97.9 %** (Très élevée (le portefeuille bouge comme un bloc)) -- calculée sur 1 paire(s) de lignes (2 ligne(s) cotée(s) avec un historique suffisant). Étendue observée : de +97.9 % à +97.9 %.

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
| ETF / Fonds | 776.30 EUR | 100.0% |

*Un actif peut porter plusieurs étiquettes : la somme des parts par étiquette peut dépasser 100 %.*


---

## Fiabilite des Notes

*Cette section mesure la valeur PASSEE de la note ; elle ne la modifie pas et ne predit rien. Une esperance historique n'est pas une promesse.*

**Apprentissage mutualise** : calibre sur 13 titre(s) suivis par l'ensemble des profils participants. Seuls le titre, la date, la note et le resultat sont partages -- jamais l'identite, les quantites ni les prix de revient.

**Snapshots : 429** (dont 381 herites de history.csv) | **Clotures : 495** | **Invalides : 0** | Version de la note : `v14-5fd53e`

### Notes par tranche -- horizon 60 seances, cible : surperformance vs marche

*Echantillon inclut la cohorte HERITEE (formules anterieures, reconstituee depuis history.csv) : confiance plafonnee a "faible".*

| Tranche | N | N indep. | Surperf. moyenne | Mediane | % positifs | IC 95 % | Esperance calibree | Confiance |
|---------|---|----------|------------------|---------|------------|---------|--------------------|-----------|
| < 3 (VENDRE) | 30 | 1 | -18.0% | -19.2% | 0% | -- | -- | insuffisante |
| 3 - 4,5 (A EVITER) | 15 | 2 | +34.5% | +32.9% | 100% | -- | -- | insuffisante |
| 4,5 - 6 (GARDER) | 73 | 5 | +15.7% | +20.4% | 90% | -- | -- | insuffisante |
| 6 - 7,5 (ACHAT MODERE) | 46 | 3 | -0.8% | -3.6% | 46% | -- | -- | insuffisante |
| >= 7,5 (ACHAT FORT) | 10 | 1 | -27.1% | -27.4% | 0% | -- | -- | insuffisante |

**Lien note -> surperformance :** IC de rang -0.10 (echantillon independant : +0.14) | pente -4.16 pt par point de note | 6 titre(s) sur 35 seance(s).

| Secteur | N | N indep. | Surperf. moyenne | % positifs | IC de rang |
|---------|---|----------|------------------|------------|------------|
| Financials | 34 | 1 | +9.2% | 100% | -0.28 |
| Health Care | 34 | 1 | -21.8% | 0% | -0.89 |
| Information Technology | 31 | 1 | -17.0% | 10% | -0.67 |

*Ventilation par region, a titre indicatif (n'entre pas dans le calcul de l'esperance calibree) :*

| Region | N | N indep. | Surperf. moyenne | % positifs |
|--------|---|----------|------------------|------------|
| EUROPE | 102 | 3 | +5.1% | 67% |
| US | 72 | 3 | +4.1% | 47% |

### Quel horizon colle le mieux a la note ?

| Horizon (seances) | N indep. | IC de rang | Notes >= 7,5 | Notes < 4,5 | Cible |
|-------------------|----------|------------|--------------|-------------|-------|
| 20 | 14 | -0.18 | -5.5% | -5.2% | surperformance sectorielle |
| 60 | 6 | -0.10 | -27.1% | +8.3% | surperformance vs marche |

### Fiabilite par position (horizon 60 seances)

| Valeur | Note | Surperf. attendue | IC 95 % | P(surperf.) | Confiance | Echantillon | Cohorte |
|--------|------|-------------------|---------|-------------|-----------|-------------|---------|
| MSCI WORLD | 7.72/10 | n/d | -- | -- | insuffisante | 1 | global + heritee |
| S&P500 | 7.72/10 | n/d | -- | -- | insuffisante | 1 | global + heritee |
| MSCI WORLD | 7.72/10 | n/d | -- | -- | insuffisante | 1 | global + heritee |
| MSCI WORLD | 7.72/10 | n/d | -- | -- | insuffisante | 1 | global + heritee |

**Modele : non active** -- historique insuffisant : 0/250 observations closes avec sous-notes. La calibration statistique ci-dessus reste la seule prevision affichee.


---

## Analyse par Valeur

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.13 EUR | ^ +0.68% | 213.84 EUR | + +10.74 EUR (+5.3%) | + +8.65 EUR (+4.3%) | **7.72/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +2.6% | 3M +3.4% | 6M +18.5% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (1 observation(s) independante(s) dans la tranche >= 7,5) -- aucune esperance publiee.

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +8.65 EUR (+4.3%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### S&P500 `PSP5.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 60.26 EUR | ^ +0.92% | 120.52 EUR | + +4.78 EUR (+4.1%) | + +3.60 EUR (+3.1%) | **7.72/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +3.6% | 3M +4.7% | 6M +21.1% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (1 observation(s) independante(s) dans la tranche >= 7,5) -- aucune esperance publiee.

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +3.60 EUR (+3.1%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.13 EUR | ^ +0.68% | 427.68 EUR | + +32.28 EUR (+8.2%) | + +28.31 EUR (+7.2%) | **7.72/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +2.6% | 3M +3.4% | 6M +18.5% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (1 observation(s) independante(s) dans la tranche >= 7,5) -- aucune esperance publiee.

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +28.31 EUR (+7.2%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.13 EUR | ^ +0.68% | 14.26 EUR | + +1.30 EUR (+10.0%) | + +1.17 EUR (+9.0%) | **7.72/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 7.3/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +2.6% | 3M +3.4% | 6M +18.5% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (1 observation(s) independante(s) dans la tranche >= 7,5) -- aucune esperance publiee.

**Justification :** Note 7.7/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 7.3. Momentum HAUSSIER. Position : +1.17 EUR (+9.0%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

## Synthese Portefeuille

| Valeur | Cours EUR | VM EUR | P&L Brut | P&L Net | Note | Conf. | Recomm. |
|--------|-----------|--------|----------|---------|------|-------|---------|
| MSCI WORLD | 7.13 | 213.84 | +10.74 (+5.3%) | +8.65 (+4.3%) | 7.72/10 | 100% | A EXAMINER (peu de criteres) |
| S&P500 | 60.26 | 120.52 | +4.78 (+4.1%) | +3.60 (+3.1%) | 7.72/10 | 100% | A EXAMINER (peu de criteres) |
| MSCI WORLD | 7.13 | 427.68 | +32.28 (+8.2%) | +28.31 (+7.2%) | 7.72/10 | 100% | A EXAMINER (peu de criteres) |
| MSCI WORLD | 7.13 | 14.26 | +1.30 (+10.0%) | +1.17 (+9.0%) | 7.72/10 | 100% | A EXAMINER (peu de criteres) |
| **TOTAL** | — | **776.30** | **+49.10 (+6.8%)** | **+41.73 (+5.7%)** | — | — | — |

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

**Quotas API utilisés :** {'alphavantage': '1/20', 'twelvedata': '2/60', 'eodhd': '29/80', 'finnhub': '4/55'}

**Profil :** adrisis | **Courtier :** Autre / personnalisé
