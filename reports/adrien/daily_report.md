# Rapport de Portefeuille v7.5 -- 05/11/2026 02:44 (Paris)

---

## Contexte Economique

**Tendance : Haussiere** | Score macro : 6.77/10
**EUR/USD :** 1 EUR = 1.1257 USD

| Indice | Variation | Cours |
|--------|-----------|-------|
| S&P 500 | ^ +1.58% | 7 688.62 |
| CAC 40 | ^ +1.96% | 8 177.89 |

**Taux souverains 10 ans :**

| Taux | Variation | Niveau | Sur 1 mois |
|------|-----------|--------|------------|
| UST 10 ans (US) | -- | 4.89% | -- |
| OAT 10 ans (FR) | -- | 4.82% | -- |
| Ecart OAT - UST | -- | -7 pb | -- |

**Manchettes macro :**

- Pranešimas apie Akcinės prekybos bendrovės „APRANGA“ šaukiamą eilinį visuotinį akcininkų susirinkimą
- Notice of the Annual General Meeting of Akcinė prekybos bendrovė “APRANGA” shareholders
- BIC discontinue les activités de Rocketbook et de Skin Creative
- BIC discontinues Rocketbook and its Skin Creative activities
- BIC annonce la nomination d’un nouveau Directeur Financier

---

## Stops et Alertes

**Stops actifs : 0** | **Franchis : 0** | **Sans stop : 5** | Nouvelles alertes du jour : 0

Règle de franchissement : la CLÔTURE du jour passe sous le niveau. Une seule alerte par franchissement ; le déclencheur se ré-arme quand le cours repasse au-dessus. Les stops suiveurs et VQ montent avec le cours et ne redescendent jamais.

| Valeur | Compte | Type | Configuration | Niveau | Cloture | Distance | Statut |
|--------|--------|------|---------------|--------|---------|----------|--------|
| SM | ord | Aucun | Aucun stop défini | -- | 27.58 | -- | Aucun |
| WPEA | pea | Aucun | Aucun stop défini | -- | 7.16 | -- | Aucun |
| Credit Agricole SA | ord | Aucun | Aucun stop défini | -- | 15.52 | -- | Aucun |
| CoreWeave | ord | Aucun | Aucun stop défini | -- | 42.99 | -- | Aucun |
| Abionyx Pharma | ord | Aucun | Aucun stop défini | -- | 1.57 | -- | Aucun |

### Dimensionnement des positions

Capital de référence : **735.19 EUR** (valeurs cotées + liquidités, hors actifs illiquides). Risque par idée : **1 %**, soit **7.35 EUR**. Plafond de poids par ligne : 15 %.

Formule : montant = (capital x risque) / distance au stop. Deux valeurs de volatilités différentes reçoivent ainsi le même risque, pas le même montant. Sans stop exploitable : montant = capital x budget de volatilité (2 %) / volatilité de la ligne.

| Valeur | Volatilite an. | Amplitude/jour | VQ | Distance stop | Taille suggeree | Detenu | Ecart |
|--------|----------------|----------------|-----|---------------|-----------------|--------|-------|
| SM | 53.4 % (Élevée, sur 1 an) | 3.08 % | 34.7 % | -- | 27.54 EUR (dimensionné par la volatilité) | 275.82 EUR | 248.28 EUR |
| WPEA | 10.8 % (Faible, sur 1 an) | 0.52 % | 8.0 % | -- | 110.28 EUR (dimensionné par la volatilité, plafonné à 15 % du capital) | 178.95 EUR | 68.67 EUR |
| Credit Agricole SA | 21.4 % (Modérée, sur 1 an) | 1.08 % | 13.9 % | -- | 68.55 EUR (dimensionné par la volatilité) | 155.20 EUR | 86.65 EUR |
| CoreWeave | 97.6 % (Extrême, sur 1 an) | 6.02 % | 40.0 % | -- | 15.07 EUR (dimensionné par la volatilité) | 85.97 EUR | 70.90 EUR |
| Abionyx Pharma | 53.3 % (Élevée, sur 1 an) | 1.90 % | 34.6 % | -- | 27.60 EUR (dimensionné par la volatilité) | 39.25 EUR | 11.65 EUR |

*« Amplitude/jour » : de combien la valeur bouge en moyenne d'une cloture a l'autre. C'est la lecture concrete de la volatilite.*

*« Volatilite an. » : ecart-type des variations journalieres sur 1 an d'historique (ou depuis la cotation pour un titre recent), annualise ; la profondeur reelle est indiquee dans la colonne. « VQ » = 0,65 x cette volatilite, borne entre 8 % et 40 %.*

*« Écart » = ce qui est détenu moins ce que le budget de risque justifierait. Positif : la ligne est plus grosse que le risque accepté. Ce n'est pas un ordre de vente, c'est un écart à expliquer.*


### Exposition corrélée

**Corrélation moyenne du portefeuille : -4.8 %** (Négative (les lignes s'amortissent entre elles)) -- calculée sur 10 paire(s) de lignes (5 ligne(s) cotée(s) avec un historique suffisant). Étendue observée : de -69.8 % à +79.9 %.

*Plus ce chiffre est proche de 0, plus les lignes bougent indépendamment les unes des autres -- une diversification qui se voit dans les mouvements réels, pas seulement dans les étiquettes de classe d'actif ou de secteur. Un chiffre élevé et négatif est aussi une forme de concentration, sur le pari inverse.*

Lignes dont les variations à 3 mois sont fortement corrélées entre elles (mesurées sur 1 an d'historique) -- prises ensemble, elles pèsent plus qu'un plafond de poids par ligne ne le laisse penser. Un signal d'attention, pas une prévision.

| Groupe | Poids cumulé | Alerte |
|--------|--------------|--------|
| SM, Abionyx Pharma | 42.86 % | Oui |

*Seuil de corrélation : 0.70. Seuil d'alerte sur le poids cumulé : 25 %.*


---

## Repartition

**Par classe d'actif**

| Poste | Montant | Part |
|-------|---------|------|
| Actions | 556.24 EUR | 75.7% |
| ETF / Fonds | 178.95 EUR | 24.3% |

**Par devise**

| Poste | Montant | Part |
|-------|---------|------|
| EUR | 373.40 EUR | 50.8% |
| USD | 361.79 EUR | 49.2% |

**Par compte**

| Poste | Montant | Part |
|-------|---------|------|
| ord | 556.24 EUR | 75.7% |
| pea | 178.95 EUR | 24.3% |

**Par étiquette**

| Poste | Montant | Part |
|-------|---------|------|
| Sans étiquette | 556.24 EUR | 75.7% |
| socle | 178.95 EUR | 24.3% |

*Un actif peut porter plusieurs étiquettes : la somme des parts par étiquette peut dépasser 100 %.*


---

## Fiabilite des Notes

*Cette section mesure la valeur PASSEE de la note ; elle ne la modifie pas et ne predit rien. Une esperance historique n'est pas une promesse.*

**Apprentissage mutualise** : calibre sur 235 titre(s) : ceux des profils participants et un univers de reference d'environ 220 actions (US et zone euro, 11 secteurs) note chaque semaine. Seuls le titre, la date, la note et le resultat sont partages -- jamais l'identite, les quantites ni les prix de revient.

**Snapshots : 1774** (dont 381 herites de history.csv) | **Reconstitues (amorcage) : 4662** | **Clotures : 804** | **Invalides : 0** | Version de la note : `v14-5fd53e`

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
| 20 | 55 | +0.28 | -2.4% | -13.0% | surperformance sectorielle |
| 60 | 1472 | -0.01 | +1.9% | +2.0% | surperformance sectorielle |
| 120 | 736 | +0.04 | +5.8% | +2.0% | surperformance sectorielle |
| 252 | 245 | +0.00 | +9.7% | +5.4% | surperformance sectorielle |

### Fiabilite par position (horizon 60 seances)

| Valeur | Note | Surperf. attendue | IC 95 % | P(surperf.) | Confiance | Echantillon | Cohorte |
|--------|------|-------------------|---------|-------------|-----------|-------------|---------|
| SM | 7.68/10 | +1.6% | [-0.2 ; +3.9] | 50% | elevee | 110 | global |
| WPEA | 6.35/10 | -0.3% | [-1.0 ; +0.4] | 46% | elevee | 879 | global |
| Credit Agricole SA | 5.79/10 | +2.9% | -- | 51% | moyenne | 35 | secteur Financials |
| CoreWeave | 3.96/10 | +2.3% | -- | 53% | faible | 19 | secteur Information Technology |
| Abionyx Pharma | 1.57/10 | +2.1% | [-1.8 ; +9.2] | -- | faible | 21 | global |

**Modele : non active** -- historique insuffisant : 0/250 observations closes avec sous-notes. La calibration statistique ci-dessus reste la seule prevision affichee.


---

## Analyse par Valeur

### SM `SM.US`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 27.58 EUR | v -15.30% | 275.82 EUR | - -64.59 EUR (-19.0%) | - -72.12 EUR (-21.2%) | **7.68/10** (100%) | NOTE ÉLEVÉE |

**Actualite recente :** *(source : RSS Yahoo Finance)*

> SM Energy Co (SM) Q3 2026 Earnings Call Highlights: $400 Million in Synergies, $1. ... | SM Energy (SM) Q3 2026 Earnings Call Transcript | SM Energy Company Q3 2026 Earnings Call Summary

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Valorisation | 9.0/10 | 24% |
| Sante financiere | 8.4/10 | 19% |
| Croissance | 10.0/10 | 16% |
| Momentum | 4.5/10 | 21% |
| Consensus | 7.1/10 | 15% |
| Risque | 5.9/10 | 5% |

**Fondamentaux :** PER 5.5 | PEG 0.5 | EV/EBITDA 4.8 | P/B 0.7 | Marge nette 20.2% | ROE 16.1% | Croiss. CA 176.1% | Beta 0.8 *(source : Yahoo Finance)*
**Consensus analystes :** SB:5 B:14 H:7 S:1 SS:0 *(source : Finnhub)*
**Perf. historique :** 1M -11.4% | 3M +8.9% | 6M +2.6% -- NEUTRE *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche >= 7,5 a valu +1.6% de surperformance sectorielle a 60 seances, IC 95 % [-0.2 ; +3.9], P(surperf.) 50% -- confiance elevee, 110 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 7.7/10 (confiance 100%). Points forts : croissance 10.0, valorisation 9.0. Points faibles : momentum 4.5. Momentum NEUTRE. Position : -72.12 EUR (-21.2%) apres frais.

---

### WPEA `WPEA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 7.16 EUR | ^ +1.26% | 178.95 EUR | - -2.55 EUR (-1.4%) | - -3.44 EUR (-1.9%) | **6.35/10** (100%) | NOTE INCOMPLÈTE (peu de critères) |

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Momentum | 5.6/10 | 81% |
| Risque | 9.5/10 | 19% |

*Sans objet pour un actif de type etf / fonds : Valorisation, Sante financiere, Croissance, Consensus. Ces criteres n'existent pas pour ce type d'actif : ils sont exclus du calcul et ne font PAS baisser l'indice de confiance.*

**Consensus analystes :** N/D *(source : sans objet)*
**Perf. historique :** 1M -0.4% | 3M +1.9% | 6M +8.9% -- NEUTRE *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche 6 - 7,5 a valu -0.3% de surperformance sectorielle a 60 seances, IC 95 % [-1.0 ; +0.4], P(surperf.) 46% -- confiance elevee, 879 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 6.3/10 (confiance 100%). Points forts : profil de risque 9.5. Momentum NEUTRE. Position : -3.44 EUR (-1.9%) apres frais. 4 critere(s) sans objet pour un actif de type etf / fonds (consensus analystes, croissance, sante financiere, valorisation) : ils sont exclus du calcul, pas comptes comme manquants.

---

### Credit Agricole SA `ACA.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 15.52 EUR | ^ +3.33% | 155.20 EUR | - -13.80 EUR (-8.2%) | - -15.79 EUR (-9.3%) | **5.79/10** (85%) | NOTE MOYENNE |

**Actualite recente :** *(source : RSS Yahoo Finance)*

> CREDIT AGRICOLE S.A. ANNOUNCES REDEMPTION OF GBP 750,000,000 Senior Non-Preferred Callable Fixed Rate Resettable Notes i… | Credit Agricole Q3 profit rises on investment banking strength | CREDIT AGRICOLE SA: Q3 and 9M Results : STRONG RESULTS, ACCELERATED GROWTH IN EUROPE

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Valorisation | 8.3/10 | 28% |
| Sante financiere | 7.5/10 | 22% |
| Croissance | 5.1/10 | 19% |
| Momentum | 1.6/10 | 25% |
| Risque | 7.2/10 | 6% |

*Attendu mais non obtenu : Consensus -- poids redistribues sur les composantes ci-dessus. C'est ce qui fait baisser l'indice de confiance.*

**Fondamentaux :** PER 7.9 | PEG 1.4 | P/B 0.6 | Marge nette 26.0% | ROE 9.3% | Croiss. CA 2.3% | Beta 0.8 *(source : Yahoo Finance)*
**Consensus analystes :** N/D *(source : indisponible (Finnhub:HTTP 403, EODHD:HTTP 403))*
**Perf. historique :** 1M -5.0% | 3M -17.4% | 6M +0.3% -- BAISSIER *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche 4,5 - 6 a valu +2.9% de surperformance sectorielle a 60 seances, P(surperf.) 51% -- confiance moyenne, 35 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 5.8/10 (confiance 85%). Points forts : valorisation 8.3, sante financiere 7.5. Points faibles : momentum 1.6. Momentum BAISSIER. Position : -15.79 EUR (-9.3%) apres frais. Critere(s) attendu(s) mais non obtenu(s) : consensus analystes.

---

### CoreWeave `CRWV.US`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 42.99 EUR | v -9.90% | 85.97 EUR | - -101.85 EUR (-54.2%) | - -108.98 EUR (-58.0%) | **3.96/10** (100%) | NOTE FAIBLE |

**Actualite recente :** *(source : RSS Yahoo Finance)*

> AI's Building Boom Meets A Blue Wave. 'Neocloud' Stocks Fall. | CoreWeave Stocks Decline 6.25% While Policy Fears Put November 10 Results in Focus | Sector Update: Tech Stocks Mixed Wednesday Afternoon

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Valorisation | 3.9/10 | 24% |
| Sante financiere | 1.1/10 | 19% |
| Croissance | 10.0/10 | 16% |
| Momentum | 0.0/10 | 21% |
| Consensus | 7.2/10 | 15% |
| Risque | 2.7/10 | 5% |

**Fondamentaux :** EV/EBITDA 19.2 | P/B 5.3 | Marge nette -25.4% | ROE -43.6% | Croiss. CA 112.5% *(source : Yahoo Finance)*
**Consensus analystes :** SB:11 B:26 H:13 S:1 SS:1 *(source : Finnhub)*
**Perf. historique :** 1M -44.6% | 3M -43.3% | 6M -57.8% -- BAISSIER *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche 3 - 4,5 a valu +2.3% de surperformance sectorielle a 60 seances, P(surperf.) 53% -- confiance faible, 19 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 4.0/10 (confiance 100%). Points forts : croissance 10.0, consensus analystes 7.2. Points faibles : sante financiere 1.1, momentum 0.0. Momentum BAISSIER. Position : -108.98 EUR (-58.0%) apres frais.

---

### Abionyx Pharma `ABNX.PA`

| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Niveau |
|-------|-----------|-----|----------|---------|------------------|---------|
| 1.57 EUR | ^ +0.13% | 39.25 EUR | - -27.95 EUR (-41.6%) | - -29.94 EUR (-44.5%) | **1.57/10** (85%) | NOTE TRÈS FAIBLE |

**Actualite recente :** *(source : RSS Yahoo Finance)*

> ABIONYX Pharma Signs a Strategic Partnership with Lille University Hospital—Burn Treatment Center and Intensive Care Uni… | ABIONYX Pharma Finalizes the Structuring of Its CER-001 Bioproduction Chain Through a Strategic Partnership with AXPLORA… | ABIONYX Pharma and OLON Enter Into Strategic Manufacturing Partnership to Prepare CER-001 Biologic for Regulatory Approv…

**Detail de la note :**

| Composante | Note | Poids |
|------------|------|-------|
| Valorisation | 1.8/10 | 28% |
| Sante financiere | 1.1/10 | 22% |
| Croissance | 1.0/10 | 19% |
| Momentum | 1.2/10 | 25% |
| Risque | 5.9/10 | 6% |

*Attendu mais non obtenu : Consensus -- poids redistribues sur les composantes ci-dessus. C'est ce qui fait baisser l'indice de confiance.*

**Fondamentaux :** EV/EBITDA -10.3 | P/B 12.3 | Marge nette -136.6% | ROE -92.3% | Croiss. CA -11.9% | Beta 0.9 *(source : Yahoo Finance)*
**Consensus analystes :** N/D *(source : indisponible (Finnhub:HTTP 403, EODHD:HTTP 403))*
**Perf. historique :** 1M -2.1% | 3M -16.8% | 6M -56.2% -- BAISSIER *(source : EODHD)*
**Fiabilite de la note :** une note de la tranche < 3 a valu +2.1% de surperformance sectorielle a 60 seances, IC 95 % [-1.8 ; +9.2] -- confiance faible, 21 observation(s) independante(s). *Mesure historique, pas une prevision.*

**Justification :** Note 1.6/10 (confiance 85%). Points faibles : sante financiere 1.1, croissance 1.0. Momentum BAISSIER. Position : -29.94 EUR (-44.5%) apres frais. Critere(s) attendu(s) mais non obtenu(s) : consensus analystes.

---


## Plus-values realisees

*Positions vendues. Ces lignes ne figurent plus dans le portefeuille et n'entrent pas dans la valorisation ci-dessus.*

| Valeur | Qte | Achat | Vente | Produit | Frais | +/- value nette |
|--------|-----|-------|-------|---------|-----------|-----------------|
| Palantir Technologies | 2 | 119.06 EUR | 172.70 USD @ 0.86337 | 298.21 EUR | 7.58 EUR | **+52.51 EUR (+22.1%)** |
| **TOTAL** | — | **238.12 EUR** | — | — | — | **+52.51 EUR (+22.1%)** |

- Palantir Technologies : vendu le 2026-08-17 15:34:15 — Vente integrale de la ligne

---
## Synthese Portefeuille

| Valeur | Cours EUR | VM EUR | P&L Brut | P&L Net | Note | Conf. | Niveau |
|--------|-----------|--------|----------|---------|------|-------|---------|
| SM | 27.58 | 275.82 | -64.59 (-19.0%) | -72.12 (-21.2%) | 7.68/10 | 100% | NOTE ÉLEVÉE |
| WPEA | 7.16 | 178.95 | -2.55 (-1.4%) | -3.44 (-1.9%) | 6.35/10 | 100% | NOTE INCOMPLÈTE (peu de critères) |
| Credit Agricole SA | 15.52 | 155.20 | -13.80 (-8.2%) | -15.79 (-9.3%) | 5.79/10 | 85% | NOTE MOYENNE |
| CoreWeave | 42.99 | 85.97 | -101.85 (-54.2%) | -108.98 (-58.0%) | 3.96/10 | 100% | NOTE FAIBLE |
| Abionyx Pharma | 1.57 | 39.25 | -27.95 (-41.6%) | -29.94 (-44.5%) | 1.57/10 | 85% | NOTE TRÈS FAIBLE |
| **TOTAL** | — | **735.19** | **-210.74 (-22.3%)** | **-230.27 (-24.3%)** | — | — | — |

---

## Watchlist

| Valeur | Secteur | Cours EUR | Variation | Actualite |
|--------|---------|-----------|-----------|-----------|
| SNAP | tech | 5.26 EUR | ^ +5.90% | Snapchat posts modest user increase in Q3 / Snap (SNAP) Q3 Earnings: Taking a Lo… |
| Apple | Tech | 310.48 EUR | ^ +5.31% | Dow Jones Futures Rise, But Techs Tumble; Apple, Microsoft, Amazon Flash Buy Sig… |

---

## Sources et Quotas

- **EUR/USD** : AlphaVantage
- **S&P 500** : EODHD
- **CAC 40** : EODHD
- **UST 10 ans (US)** : EODHD
- **OAT 10 ans (FR)** : EODHD
- **CRWV.US** : cours: TwelveData, consensus: Finnhub, historique: EODHD, synthese: RSS Yahoo Finance, fondamentaux: Yahoo Finance
- **ACA.PA** : cours: EODHD, consensus: indisponible (Finnhub:HTTP 403, EODHD:HTTP 403), historique: EODHD, synthese: RSS Yahoo Finance, fondamentaux: Yahoo Finance
- **ABNX.PA** : cours: EODHD, consensus: indisponible (Finnhub:HTTP 403, EODHD:HTTP 403), historique: EODHD, synthese: RSS Yahoo Finance, fondamentaux: Yahoo Finance
- **SM.US** : cours: TwelveData, consensus: Finnhub, historique: EODHD, synthese: RSS Yahoo Finance, fondamentaux: Yahoo Finance
- **WPEA.PA** : cours: EODHD, consensus: sans objet, historique: EODHD, synthese: RSS Yahoo vide, fondamentaux: non applicable (etf)

**Quotas API utilisés :** {'alphavantage': '1/20', 'twelvedata': '2/780', 'eodhd': '119/600', 'finnhub': '4/3000'}

**Profil :** adrien | **Courtier :** BoursoBank
