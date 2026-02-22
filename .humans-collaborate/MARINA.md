# Marina's Domain Expertise & Notes

> This document captures Marina's public policy knowledge that informs ALETHEIA's design and test case development.

## My Role

- Domain expertise in official statistics and policy data
- Test case curation (the 10 methodology break cases)
- Validation of system outputs from a policy analyst perspective

## Domain Knowledge

### High-Value Document Sources

*[Marina: List URLs and domains where methodology documentation lives]*

| Source | Type | Domain | Notes |
|--------|------|--------|-------|
| CDC/NCHS | Methodology notes | Health surveys | NHIS redesign docs, questionnaire changes |
| BLS | Technical notes | Labor statistics | CPS methodology, COVID adjustments |
| Census Bureau | Technical documentation | Demographic/economic surveys | ACS methodology, nonresponse adjustments |
| Eurostat | Methodology docs | EU statistics | EU LFS, HICP, EU SILC methodology changes 
| ECB | Statistical bulletins | Economic accounts | ESA 2010 implementation notes |
| OECD | Statistical working papers | Cross national comparisons | Methodology harmonization |
| National statistical offices | Country specific notes | Various domains | Ireland CSO, national implementations |





### Key Methodology Documentation

*[Marina: Important documents that should be in the knowledge base]*

1.NHIS 2019 Questionnaire Redesign - CDC/NCHS documentation on major survey restructuring affecting trend comparability
2.BLS COVID 19 Misclassification FAQ - Technical note on unemployment classification errors during pandemic
3.ACS 2020 Experimental Estimates - Census Bureau documentation on COVID 19 nonresponse bias adjustments
4.CPI Collection Suspension Documentation - BLS technical notes on pandemic related data collection gaps
5.Eurostat EU LFS 2021 Methodology Change - Updated definitions and classifications affecting unemployment statistics
6.HICP Imputation Methodology - Eurostat technical manual on price imputation during missing data periods
7.Eurostat Mortality Revision Policy - Documentation on revision schedules and preliminary vs. final estimates
8.ESA 2010 Implementation Guide - European Commission guidance on R&D capitalization in national accounts
9.EU SILC Quality Reports - Country specific documentation on series breaks and comparability issues
10.UNECE Statistical Standards - International guidelines on methodology documentation and break identification



### Papers for Validation Evidence

*[Marina: Academic papers that can support/contradict claims — target 100+]*

| Paper | Domain | Key Finding | URL/DOI |
|-------|--------|-------------|---------|
Parsons et al. (2019) - Health surveys - NHIS redesign impact on trend analysis - https://www.cdc.gov/nchs/nhis/about/2019-questionnaire-redesign.html

Cajner et al. (2020) - Labor statistics - COVID 19 misclassification in unemployment - https://www.federalreserve.gov/econres/feds/reconciling-unemployment-claims-with-job-losses-in-the-first-months-of-the-covid-19-crisis.htm

Rothbaum & Bee (2021) - Income statistics - ACS nonresponse bias during pandemic - https://www.census.gov/library/working-papers/2021/acs/2021_Rothbaum_01.html

Bolhuis et al. (2022) - Price statistics - CPI measurement challenges during COVID 19 - https://www.nber.org/papers/w27352

Eurostat (2021) - Labor force - EU LFS methodology harmonization effects - https://ec.europa.eu/eurostat/statistics-explained/index.php?title=EU_Labour_Force_Survey_-_new_methodology_from_2021_onwards

Eurostat (2020) - Mortality statistics - Timeliness vs. accuracy trade offs - https://ec.europa.eu/eurostat/cache/metadata/EN/demomwk_esms.htm

Groves & Lyberg (2010) - Survey methodology - Total survey error framework - https://academic.oup.com/poq/article/74/5/849/1817502


## Test Cases (The Original 10)

These are the seed cases for MethodBench:

| # | Dataset | Indicator | Break Type | Status |
|---|---------|-----------|------------|--------|
| 1 | NHIS | E-cigarette use | Questionnaire redesign | ✅ Seeded |
| 2 | NHIS | Medical affordability | Questionnaire redesign | ✅ Seeded |
| 3 | CPS | Unemployment | COVID misclassification | ✅ Seeded |
| 4 | ACS | Median income | COVID nonresponse | ✅ Seeded |
| 5 | CPI | Inflation | Collection suspension | ✅ Seeded |
| 6 | EU-LFS | Unemployment | Definition change | ✅ Seeded |
| 7 | HICP | Inflation | Price imputation | ✅ Seeded |
| 8 | Eurostat | Mortality | Revision delays | ✅ Seeded |
| 9 | ESA 2010 | GDP | R&D reclassification | ✅ Seeded |
| 10 | EU-SILC | Poverty rate | Ireland series break | ✅ Seeded |

### Additional Cases to Add

*[Marina: New test cases beyond the original 10]*

| Dataset | Indicator | Break Type | Priority |
|---------|-----------|------------|----------|
| HICP | Housing costs | Methodological enhancement | High |
| JOLTS | Job openings | Seasonal adjustment revision | Medium |
| NIPA | Personal income | Definitional change | Medium |
| EU SILC | Material deprivation | Indicator update | Medium |
| CPS | Labor force participation | Population controls update | Medium |
| ACS | Disability prevalence | Question redesign | Medium |





## Thoughts & Directions

*[Marina: Your ideas on where the project should go, what's most important]*

### What Would Make This Useful for Policy Analysts?

Automated flagging when comparing data across methodology changes. Policy analysts often work under time pressure and may not have the expertise to recognize when a statistical series has undergone a methodology change. A system that automatically alerts them would prevent costly analytical errors. To take it a step further, not all methodology breaks are equal. Some allow for bridging techniques, others require completely separate analyses. The system should provide actionable guidance: "Comparable with adjustments," "Not comparable—use alternative indicator".

Also, estimates of how much observed changes reflect methodology versus reality. When the CPS unemployment rate dropped in May 2020, was it economic recovery or the correction of the COVID-19 misclassification error? Analysts need to know whether a 3 percentage point change is real or artifactual. 

How similar breaks affected comparable statistics in other countries. When Ireland's EU-SILC survey was redesigned, how did other countries handle similar transitions? This context helps analysts understand whether their findings are unique or part of a broader pattern, and provides benchmarks for assessing the magnitude of methodology impacts.

### Concerns

The system might flag normal revisions as methodology breaks (false positives). Statistical agencies routinely revise data as more complete information becomes available—these are standard corrections, not methodology changes. 

Not all methodology changes are well documented by statistical agencies. ALETHEIA's effectiveness depends on the quality of source documentation, and gaps in official records will translate to gaps in the system's knowledge.

Exact break dates may be unclear, especially for gradual implementations. The ESA 2010 R&D capitalization wasn't implemented simultaneously across all European countries, some adopted it in 2014, others phased it in over several years.

How to handle cases with overlapping or sequential methodology changes. The 2020 period saw simultaneous breaks in many statistical series COVID-19 caused collection suspensions, nonresponse bias, and misclassification errors all at once. When multiple methodology problems compound, it becomes extremely difficult to quantify their individual and combined effects. The system needs to handle these complex scenarios.

The 10 test cases represent well-documented, widely acknowledged methodology breaks. But how do we validate the system's performance on less clear-cut cases? Some breaks are only recognized in retrospect, after researchers notice anomalies in the data. Building a robust validation dataset is a fundamental challenge.

### Ideas

A severity classification system would help analysts prioritize their attention. Major breaks (complete non-comparability) require immediate action and alternative approaches. Moderate breaks (comparability possible with adjustments) need careful documentation but allow continued analysis. Minor breaks (negligible impact on most analyses) can be noted but don't necessarily halt work. This triage system prevents alert fatigue while ensuring critical breaks receive appropriate attention.

Policy analysts often monitor specific indicators over time such as unemployment rates, poverty measures, inflation indices. Rather than requiring them to constantly check for methodology changes, ALETHEIA should proactively alert users when breaks affect their tracked series.

Show how different countries handled similar methodology challenges. The COVID-19 pandemic forced statistical agencies worldwide to adapt simultaneously, but they chose different approaches. Some suspended collection entirely, others shifted to phone interviews, still others used administrative data substitutes. Comparative analysis provides context for assessing whether observed changes are measurement artifacts or real phenomena, and offers alternative methodological approaches.



## Narrative for Paper

*[Marina: Draft thoughts on the policy/impact framing for JEBO]*

Methodology breaks in official statistics create systematic errors in policy evaluation, leading to misallocation of resources and flawed policy decisions. Unlike random measurement errors that average out over time, methodology breaks introduce structural discontinuities that systematically bias trend analysis. When policy analysts unknowingly compare data across these breaks, they mistake measurement artifacts for real world changes, fundamentally undermining evidence-based policymaking.

Policy analysts routinely compare statistics over time to assess intervention effectiveness, economic trends, and social outcomes. This temporal comparison is the foundation of policy evaluation. Did the new healthcare program reduce unmet medical needs? Is unemployment falling due to labor market recovery? Are poverty reduction initiatives working? These questions require valid time series comparisons. When methodology changes create discontinuities, analysts may incorrectly attribute measurement artifacts to real world changes, leading to misdiagnosis of policy problems, incorrect evaluation of intervention effectiveness, flawed forecasting and planning, and inappropriate policy responses. The consequences are concrete: budgets allocated to address phantom problems, effective programs terminated based on artifactual declines, policy debates conducted using incomparable statistics, and public trust eroded when official statistics appear contradictory.

An AI system that automatically detects methodology breaks and warns analysts before they make invalid comparisons. This prevents a class of systematic errors that currently plague policy analysis. Unlike existing approaches that rely on analysts manually checking technical documentation or statistical agencies proactively communicating changes, ALETHEIA embeds methodology awareness directly into the analytical workflow. The system identifies breaks across multiple statistical series, quantifies their impact on comparability, provides actionable guidance on whether and how to proceed with analysis, and links directly to official documentation explaining the changes. This transforms methodology break detection from a specialized expert task to an automated safeguard accessible to all policy analysts.

The 10 test cases demonstrate how common methodology breaks are in major statistical series. The cases span health surveys, labor statistics, income measures, price indices, and poverty indicators, showing that breaks affect virtually every domain of policy analysis. They include both US and European examples, demonstrating this is a universal challenge, not country specific. Analysts can easily miss these breaks in practice. Even well documented changes like the NHIS 2019 redesign or CPS COVID misclassification were initially overlooked by many researchers, leading to published analyses with invalid comparisons. The technical documentation exists but is scattered across agency websites, buried in methodological appendices, and written in specialized statistical language that policy analysts struggle to interpret. We will demonstrate how ALETHEIA successfully identifies breaks that humans miss. The system recognizes patterns in data discontinuities, cross references official documentation, and flags potential breaks even when agencies provide minimal notification. We cn quantify the potential policy consequences of undetected breaks. Using the test cases, estimate how many published policy analyses made invalid comparisons, how budget decisions might have been affected by artifactual trends, and what the cumulative cost of methodology induced errors might be across government and research institutions.



---

*Last updated: YYYY-MM-DD*
