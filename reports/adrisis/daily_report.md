# Rapport de Portefeuille v7.5 -- 30/09/2026 01:56 (Paris)

---

## Contexte Economique

**Tendance : Neutre** | Score macro : 4.65/10
**EUR/USD :** 1 EUR = 1.1344 USD

| Indice | Variation | Cours |
|--------|-----------|-------|
| S&P 500 | v -0.17% | 7 670.84 |
| CAC 40 | v -0.53% | 8 035.87 |

**Taux souverains 10 ans :**

| Taux | Variation | Niveau | Sur 1 mois |
|------|-----------|--------|------------|
| UST 10 ans (US) | -- | 5.25% | -- |
| OAT 10 ans (FR) | -- | 4.81% | -- |
| Ecart OAT - UST | -- | -44 pb | -- |

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
| S&P500 | PEA CA | Aucun | Aucun stop défini | -- | 59.46 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.05 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.05 | -- | Aucun |
| MSCI WORLD | PEA CA | Aucun | Aucun stop défini | -- | 7.05 | -- | Aucun |

### Dimensionnement des positions

Capital de référence : **767.98 EUR** (valeurs cotées + liquidités, hors actifs illiquides). Risque par idée : **1 %**, soit **7.68 EUR**. Plafond de poids par ligne : 15 %.

Formule : montant = (capital x risque) / distance au stop. Deux valeurs de volatilités différentes reçoivent ainsi le même risque, pas le même montant. Sans stop exploitable : montant = capital x budget de volatilité (2 %) / volatilité de la ligne.

| Valeur | Volatilite an. | Amplitude/jour | VQ | Distance stop | Taille suggeree | Detenu | Ecart |
|--------|----------------|----------------|-----|---------------|-----------------|--------|-------|
| S&P500 | 11.3 % (Faible, sur 1 an) | 0.45 % | 8.0 % | -- | 115.20 EUR (dimensionné par la volatilité, plafonné à 15 % du capital) | 118.92 EUR | 3.72 EUR |
| MSCI WORLD | 10.9 % (Faible, sur 1 an) | 0.49 % | 8.0 % | -- | 115.20 EUR (dimensionné par la volatilité, plafonné à 15 % du capital) | 649.06 EUR (3 lignes) | 533.86 EUR |

*« Amplitude/jour » : de combien la valeur bouge en moyenne d'une cloture a l'autre. C'est la lecture concrete de la volatilite.*

*« Volatilite an. » : ecart-type des variations journalieres sur 1 an d'historique (ou depuis la cotation pour un titre recent), annualise ; la profondeur reelle est indiquee dans la colonne. « VQ » = 0,65 x cette volatilite, borne entre 8 % et 40 %.*

*« Écart » = ce qui est détenu moins ce que le budget de risque justifierait. Positif : la ligne est plus grosse que le risque accepté. Ce n'est pas un ordre de vente, c'est un écart à expliquer.*


### Exposition corrélée

**Corrélation moyenne du portefeuille : +97.9 %** (Très élevée (le portefeuille bouge comme un bloc)) -- calculée sur 1 paire(s) de lignes (2 ligne(s) cotée(s) avec un historique suffisant). Étendue observée : de +97.9 % à +97.9 %.

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
| ETF / Fonds | 767.98 EUR | 100.0% |

*Un actif peut porter plusieurs étiquettes : la somme des parts par étiquette peut dépasser 100 %.*


---

## Fiabilite des Notes

*Cette section mesure la valeur PASSEE de la note ; elle ne la modifie pas et ne predit rien. Une esperance historique n'est pas une promesse.*

**Apprentissage mutualise** : calibre sur 9 titre(s) suivis par l'ensemble des profils participants. Seuls le titre, la date, la note et le resultat sont partages -- jamais l'identite, les quantites ni les prix de revient.

**Snapshots : 399** (dont 381 herites de history.csv) | **Clotures : 478** | **Invalides : 0** | Version de la note : `v14-5fd53e`

### Notes par tranche -- horizon 60 seances, cible : surperformance vs marche

*Echantillon inclut la cohorte HERITEE (formules anterieures, reconstituee depuis history.csv) : confiance plafonnee a "faible".*

| Tranche | N | N indep. | Surperf. moyenne | Mediane | % positifs | IC 95 % | Esperance calibree | Confiance |
|---------|---|----------|------------------|---------|------------|---------|--------------------|-----------|
| < 3 (VENDRE) | 27 | 1 | -19.5% | -21.8% | 0% | -- | -- | insuffisante |
| 3 - 4,5 (A EVITER) | 15 | 2 | +34.5% | +32.9% | 100% | -- | -- | insuffisante |
| 4,5 - 6 (GARDER) | 65 | 5 | +15.6% | +21.9% | 91% | -- | -- | insuffisante |
| 6 - 7,5 (ACHAT MODERE) | 42 | 3 | -2.4% | -10.5% | 43% | -- | -- | insuffisante |
| >= 7,5 (ACHAT FORT) | 10 | 1 | -27.1% | -27.4% | 0% | -- | -- | insuffisante |

**Lien note -> surperformance :** IC de rang -0.12 (echantillon independant : +0.14) | pente -4.16 pt par point de note | 6 titre(s) sur 32 seance(s).

| Secteur | N | N indep. | Surperf. moyenne | % positifs | IC de rang |
|---------|---|----------|------------------|------------|------------|
| Financials | 31 | 1 | +9.7% | 100% | -0.41 |
| Health Care | 31 | 1 | -23.4% | 0% | -0.87 |
| Information Technology | 28 | 1 | -18.6% | 7% | -0.60 |

*Ventilation par region, a titre indicatif (n'entre pas dans le calcul de l'esperance calibree) :*

| Region | N | N indep. | Surperf. moyenne | % positifs |
|--------|---|----------|------------------|------------|
| EUROPE | 93 | 3 | +4.9% | 67% |
| US | 66 | 3 | +2.7% | 45% |

### Quel horizon colle le mieux a la note ?

| Horizon (seances) | N indep. | IC de rang | Notes >= 7,5 | Notes < 4,5 | Cible |
|-------------------|----------|------------|--------------|-------------|-------|
| 20 | 12 | -0.18 | -5.5% | -5.1% | surperformance sectorielle |
| 60 | 6 | -0.12 | -27.1% | +7.5% | surperformance vs marche |

### Fiabilite par position (horizon 60 seances)

| Valeur | Note | Surperf. attendue | IC 95 % | P(surperf.) | Confiance | Echantillon | Cohorte |
|--------|------|-------------------|---------|-------------|-----------|-------------|---------|
| S&P500 | 7.16/10 | n/d | -- | -- | insuffisante | 3 | global + heritee |
| MSCI WORLD | 6.75/10 | n/d | -- | -- | insuffisante | 3 | global + heritee |
| MSCI WORLD | 6.75/10 | n/d | -- | -- | insuffisante | 3 | global + heritee |
| MSCI WORLD | 6.75/10 | n/d | -- | -- | insuffisante | 3 | global + heritee |

**Modele : non active** -- historique insuffisant : 0/250 observations closes avec sous-notes. La calibration statistique ci-dessus reste la seule prevision affichee.


---

## Analyse par Valeur

### S&P500 `PSP5.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 59.46 EUR | v -0.08% | 118.92 EUR | + +3.18 EUR (+2.8%) | - -0.80 EUR (-0.7%) | **7.16/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 6.6/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +1.2% | 3M +2.6% | 6M +19.2% -- HAUSSIER *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (3 observation(s) independante(s) dans la tranche 6 - 7,5) -- aucune esperance publiee.

**Justification :** Note 7.2/10 (confiance 100%). Points forts : profil de risque 9.5, momentum 6.6. Momentum HAUSSIER. Position : -0.80 EUR (-0.7%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.05 EUR | v -0.18% | 211.65 EUR | + +8.55 EUR (+4.2%) | + +4.57 EUR (+2.2%) | **6.75/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 6.1/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +0.4% | 3M +2.2% | 6M +16.6% -- NEUTRE *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (3 observation(s) independante(s) dans la tranche 6 - 7,5) -- aucune esperance publiee.

**Justification :** Note 6.8/10 (confiance 100%). Points forts : profil de risque 9.5. Momentum NEUTRE. Position : +4.57 EUR (+2.2%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.05 EUR | v -0.18% | 423.30 EUR | + +27.90 EUR (+7.1%) | + +23.92 EUR (+6.0%) | **6.75/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 6.1/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +0.4% | 3M +2.2% | 6M +16.6% -- NEUTRE *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (3 observation(s) independante(s) dans la tranche 6 - 7,5) -- aucune esperance publiee.

**Justification :** Note 6.8/10 (confiance 100%). Points forts : profil de risque 9.5. Momentum NEUTRE. Position : +23.92 EUR (+6.0%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### MSCI WORLD `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.05 EUR | v -0.18% | 14.11 EUR | + +1.15 EUR (+8.9%) | - -2.83 EUR (-21.8%) | **6.75/10** (100%) | A EXAMINER (peu de criteres) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 6.1/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M +0.4% | 3M +2.2% | 6M +16.6% -- NEUTRE *(source : EODHD)*
**Fiabilite de la note :** historique insuffisant a 60 seances (3 observation(s) independante(s) dans la tranche 6 - 7,5) -- aucune esperance publiee.

**Justification :** Note 6.8/10 (confiance 100%). Points forts : profil de risque 9.5. Momentum NEUTRE. Position : -2.83 EUR (-21.8%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

## Synthese Portefeuille

| Valeur | Cours EUR | VM EUR | P&L Brut | P&L Net | Note | Conf. | Recomm. |
|--------|-----------|--------|----------|---------|------|-------|---------|
| S&P500 | 59.46 | 118.92 | +3.18 (+2.8%) | -0.80 (-0.7%) | 7.16/10 | 100% | A EXAMINER (peu de criteres) |
| MSCI WORLD | 7.05 | 211.65 | +8.55 (+4.2%) | +4.57 (+2.2%) | 6.75/10 | 100% | A EXAMINER (peu de criteres) |
| MSCI WORLD | 7.05 | 423.30 | +27.90 (+7.1%) | +23.92 (+6.0%) | 6.75/10 | 100% | A EXAMINER (peu de criteres) |
| MSCI WORLD | 7.05 | 14.11 | +1.15 (+8.9%) | -2.83 (-21.8%) | 6.75/10 | 100% | A EXAMINER (peu de criteres) |
| **TOTAL** | — | **767.98** | **+40.78 (+5.6%)** | **+24.86 (+3.4%)** | — | — | — |

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
