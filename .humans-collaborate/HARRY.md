# Harry's Domain Expertise & Notes

> This document captures Harry's econometrics and mathematics knowledge that informs ALETHEIA's design and validation approach.

## My Role

- Statistical methods for detecting structural breaks
- Evaluation design and metrics
- Econometric rigor in the Analyst agent
- Co-lead on Paper 2 (policy/applied evaluation)

## Domain Knowledge

### Statistical Break Detection Methods

**Methods implemented or under consideration for the Analyst agent:**

| Method | Best For | Sample Requirement | In Aletheia |
|--------|----------|-------------------|-------------|
| Chow F-test | Testing a known single break date | Moderate (n > 30 per subsample) | Yes |
| Bai-Perron | Multiple unknown break dates; endogenous detection | Large (n > 100) | No |
| CUSUM / CUSUM-of-squares | Sequential monitoring; gradual parameter instability | Moderate | No |
| Quandt Likelihood Ratio (sup-Wald) | Unknown single break date; supremum test over candidates | Moderate-large | No |
| Zivot-Andrews | Unit root testing allowing for a structural break | Large (n > 50) | No |

**Method selection by scenario:**

- **Known break date** (documented methodology change with exact date) → Chow test (already implemented)
- **Unknown break date, single break** → Quandt-Andrews sup-F test
- **Unknown number and location of breaks** → Bai-Perron sequential procedure
- **Monitoring for instability over time** → CUSUM
- **Unit root vs. structural break disambiguation** → Zivot-Andrews

**Small sample handling (n < 50):**

- Chow test loses power; bootstrap variants recommended
- Bai-Perron unreliable below ~100 observations
- CUSUM remains usable but with wider confidence bands
- For very short series (annual data, n < 20): nonparametric changepoint detection (PELT algorithm via `ruptures` library) is more appropriate than parametric tests

**Confidence thresholds:**

- Default: 5% significance level for structural break tests
- For policy-relevant claims: report both 5% and 10% to flag borderline cases
- Multiple testing correction (Bonferroni or Benjamini-Hochberg) when testing multiple series simultaneously

### High-Value Data APIs

| Source | Domain | Quality | Notes |
|--------|--------|---------|-------|
| FRED (St. Louis Fed) | Macro/monetary/labor/prices | High | 800K+ series; excellent API; the single best US macro source |
| BLS | US labor statistics | High | CPS, JOLTS, CPI microdata; official source of record |
| ECB Statistical Data Warehouse | Euro area monetary/financial | High | SDW API; good coverage of banking, rates, aggregates |
| Eurostat | EU-wide official statistics | High | Bulk download + API; covers LFS, HICP, national accounts |
| Census Bureau (ACS) | US demographics/income | High | 1-year and 5-year estimates; good API |
| IMF IFS/WEO | Cross-country macro | High | International Financial Statistics; World Economic Outlook |
| OECD.Stat | Cross-country comparative | High | Harmonized indicators; good for cross-country methodology comparison |
| World Bank WDI | Development indicators | Medium-High | Long time series; some interpolation in developing country data |
| Eurostat HICP | EU price statistics | High | Detailed item-level price indices |
| ELSTAT | Greek national statistics | Medium | Coverage gaps; limited API; but authoritative for GR-specific data |

### APIs to Avoid or Use With Caution

| Source | Issue |
|--------|-------|
| Trading Economics | Aggregator, not primary source; unclear methodology; paywalled |
| Quandl (now Nasdaq Data Link) | Mixed quality; many discontinued series; attribution unclear |
| DBNOMICS | Aggregator — useful for discovery but always verify against primary source |
| Random web scraping APIs | No provenance; no methodology documentation; unreproducible |
| Wikipedia tables | Secondary source; no version control on data; silent corrections |

## Thoughts & Directions

### Research Questions

1. **Can a multi-agent AI system reliably detect and characterize structural methodology breaks in official statistics?** This is the core RQ for Paper 1. We answer it with the benchmark evaluation (currently 98% on 40 cases). The key is demonstrating this on real, documented cases — not synthetic data.

2. **How does methodology-aware AI change the accuracy of policy-relevant data interpretation?** This is the applied question. If ALETHEIA flags a break that an analyst would have missed, does the resulting policy conclusion change? We need concrete examples where ignoring the break leads to a substantively different (and wrong) interpretation.

3. **What is the false positive rate, and is it acceptable for practical deployment?** A system that flags everything is useless. We need to show that ALETHEIA can distinguish genuine methodology breaks from normal data revisions, seasonal adjustments, and routine updates.

### Concerns

1. **Sample size of benchmark cases.** 40 cases (with 10 core + 30 adversarial) is reasonable for a proof-of-concept paper, but reviewers may push back on generalizability. We need to be explicit about what we claim and what we don't.

2. **Ground truth definition.** Our "ground truth" is based on documented methodology changes from official sources. But documentation quality varies. Some breaks are clearly documented (NHIS 2019 redesign); others are buried in footnotes or acknowledged only retrospectively. We need to be transparent about this limitation.

3. **Chow test limitations.** The Chow test assumes a known break date — which we have, because we're testing documented breaks. But for the system to be useful in practice, it also needs to detect breaks when the date is unknown. This is a limitation we should acknowledge and frame as future work (Bai-Perron integration).

4. **LLM dependence.** The system's verdict quality depends on the underlying LLM. Different models may produce different verdicts for the same evidence. We should document which model was used and ideally show robustness across 2-3 models.

5. **Reproducibility.** Every claim in the paper must be reproducible. This means: fixed model versions, fixed knowledge base state, deterministic routing where possible. The batch mode + JSON export is critical for this.

### Ideas

1. **Counterfactual framing for impact.** For each of the 10 core cases, construct the "naive interpretation" (what an analyst would conclude without methodology awareness) vs. the "informed interpretation" (what ALETHEIA produces). The delta between these two is the paper's value proposition.

2. **Severity taxonomy.** Not all breaks are equal. Propose a classification: (a) Major — series not comparable across break, (b) Moderate — comparable with documented adjustments, (c) Minor — negligible impact on most analyses. This adds practical value beyond binary detection.

3. **Cross-country methodology comparison.** When the same type of break occurs in different countries (e.g., COVID labor force measurement), compare how agencies handled it. This strengthens the EU-US comparative dimension of the paper.

4. **Negative controls matter.** The benchmark should include cases where there is NO methodology break but the data shows a sharp change (e.g., genuine economic shock). The system should correctly NOT flag these. This demonstrates specificity.

## Papers & References

1. Bai, J. & Perron, P. (1998). Estimating and testing linear models with multiple structural changes. *Econometrica*, 66(1), 47-78.
2. Bai, J. & Perron, P. (2003). Computation and analysis of multiple structural change models. *Journal of Applied Econometrics*, 18(1), 1-22.
3. Andrews, D.W.K. (1993). Tests for parameter instability and structural change with unknown change point. *Econometrica*, 61(4), 821-856.
4. Zivot, E. & Andrews, D.W.K. (1992). Further evidence on the great crash, the oil-price shock, and the unit-root hypothesis. *Journal of Business & Economic Statistics*, 10(3), 251-270.
5. Brown, R.L., Durbin, J. & Evans, J.M. (1975). Techniques for testing the constancy of regression relationships over time. *Journal of the Royal Statistical Society B*, 37(2), 149-192.
6. Killick, R., Fearnhead, P. & Eckley, I.A. (2012). Optimal detection of changepoints with a linear computational cost. *Journal of the American Statistical Association*, 107(500), 1590-1598.
7. Thaler, R.H. & Sunstein, C.R. (2008). *Nudge: Improving Decisions about Health, Wealth, and Happiness*. Yale University Press.
8. Groves, R.M. & Lyberg, L. (2010). Total survey error: Past, present, and future. *Public Opinion Quarterly*, 74(5), 849-879.

---

*Last updated: 2026-03-23*
