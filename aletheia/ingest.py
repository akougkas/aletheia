"""Ingest methodology and validation documents into the knowledge base."""

from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import psycopg
from psycopg import sql

from aletheia.db import get_db_url


KNOWN_METHOD_DOC_URLS = {
    "NHIS 2019 Questionnaire Redesign": "https://www.cdc.gov/nchs/nhis/2019_quest_redesign.htm",
    "BLS COVID 19 Misclassification FAQ": "https://www.bls.gov/cps/employment-situation-covid19-faq-april-2020.pdf",
    "ACS 2020 Experimental Estimates": "https://www.census.gov/programs-surveys/acs/technical-documentation/user-notes/2020.html",
    "CPI Collection Suspension Documentation": "https://www.bls.gov/cpi/covid-19-impact.htm",
    "Eurostat EU LFS 2021 Methodology Change": "https://ec.europa.eu/eurostat/web/lfs/methodology",
    "HICP Imputation Methodology": "https://ec.europa.eu/eurostat/documents/10186/10693286/Guidance-on-the-compilation-of-HICP.pdf",
    "Eurostat Mortality Revision Policy": "https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Excess_mortality_-_statistics",
    "ESA 2010 Implementation Guide": "https://ec.europa.eu/eurostat/web/esa-2010",
    "EU SILC Quality Reports": "https://www.cso.ie/en/releasesandpublications/er/silc/surveyonincomeandlivingconditionssilc2016/",
    "UNECE Statistical Standards": "https://unece.org/statistics/publications",
}


EXTRA_REFERENCE_DOCS = [
    {
        "title": "Eurostat LFS New Methodology (2021)",
        "doc_type": "methodology_note",
        "summary": "Eurostat explanation of the 2021 EU-LFS methodological transition and comparability guidance.",
        "url": "https://ec.europa.eu/eurostat/statistics-explained/index.php?title=EU_Labour_Force_Survey_-_new_methodology_from_2021_onwards",
    },
    {
        "title": "Eurostat Weekly Mortality Metadata",
        "doc_type": "methodology_note",
        "summary": "Metadata and revision practices for weekly mortality and excess mortality estimates.",
        "url": "https://ec.europa.eu/eurostat/cache/metadata/EN/demomwk_esms.htm",
    },
    {
        "title": "CDC NHIS 2019 Questionnaire Redesign",
        "doc_type": "validation_paper",
        "summary": "Primary redesign reference for NHIS comparability caveats.",
        "url": "https://www.cdc.gov/nchs/nhis/about/2019-questionnaire-redesign.html",
    },
    {
        "title": "Federal Reserve: Reconciling Unemployment Claims (COVID)",
        "doc_type": "validation_paper",
        "summary": "Methodology discussion for pandemic-era labor market measurement artifacts.",
        "url": "https://www.federalreserve.gov/econres/feds/reconciling-unemployment-claims-with-job-losses-in-the-first-months-of-the-covid-19-crisis.htm",
    },
    {
        "title": "Census Working Paper: ACS Nonresponse Bias",
        "doc_type": "validation_paper",
        "summary": "Analysis of ACS 2020 pandemic nonresponse distortions.",
        "url": "https://www.census.gov/library/working-papers/2021/acs/2021_Rothbaum_01.html",
    },
    {
        "title": "NBER: CPI Measurement Challenges During COVID",
        "doc_type": "validation_paper",
        "summary": "Research on price-statistics collection constraints and imputation during pandemic shutdowns.",
        "url": "https://www.nber.org/papers/w27352",
    },
    {
        "title": "OUP POQ: Total Survey Error Framework",
        "doc_type": "validation_paper",
        "summary": "Survey error framework used for assessing comparability and redesign impacts.",
        "url": "https://academic.oup.com/poq/article/74/5/849/1817502",
    },
]


DOMAIN_TO_AGENCY_CODE = {
    "cdc.gov": "CDC",
    "bls.gov": "BLS",
    "census.gov": "CENSUS",
    "ec.europa.eu": "EUROSTAT",
    "ecb.europa.eu": "ECB",
    "cso.ie": "CSO",
    "federalreserve.gov": "FED",
    "nber.org": "NBER",
    "unece.org": "UNECE",
}


@dataclass
class CorpusDocument:
    title: str
    doc_type: str
    summary: str
    url: str | None = None
    publication_date: str | None = None
    agency_code: str | None = None


@dataclass(frozen=True)
class Phase3Break:
    benchmark_case_id: str
    dataset_code: str
    indicator_code: str
    change_type: str
    effective_date: str
    description: str
    impact_estimate: str
    severity: str
    comparability: str
    source_url: str
    impact_direction: str = "unknown"
    impact_magnitude: str | None = None


PHASE3_BREAKS: list[Phase3Break] = [
    # CPS/BLS expansion
    Phase3Break(
        benchmark_case_id="PH3-001",
        dataset_code="CPS",
        indicator_code="UNEMPLOYMENT_RATE",
        change_type="questionnaire_redesign",
        effective_date="1994-01-01",
        description="CPS survey redesign in 1994 introduced computer-assisted interviewing and revised labor force items.",
        impact_estimate="Introduced a documented historical series break in several labor-force measures.",
        severity="major",
        comparability="not_comparable",
        source_url="https://www.bls.gov/cps/documentation.htm",
        impact_direction="unknown",
        impact_magnitude="Historical break; bridge tables required",
    ),
    Phase3Break(
        benchmark_case_id="PH3-002",
        dataset_code="CPS",
        indicator_code="UNEMPLOYMENT_RATE",
        change_type="sample_redesign",
        effective_date="2003-01-01",
        description="Annual CPS population control updates introduced level shifts in labor-force estimates.",
        impact_estimate="Month-over-month discontinuities can reflect control updates rather than real labor changes.",
        severity="moderate",
        comparability="comparable_with_adjustments",
        source_url="https://www.bls.gov/cps/documentation.htm",
        impact_direction="unknown",
        impact_magnitude="Small annual control-induced level shifts",
    ),
    Phase3Break(
        benchmark_case_id="PH3-003",
        dataset_code="CPS",
        indicator_code="UNEMPLOYMENT_RATE",
        change_type="classification_change",
        effective_date="2020-04-01",
        description="COVID response conditions increased the probability of temporary-absence misclassification in CPS labor status.",
        impact_estimate="Official unemployment in spring 2020 understated labor distress relative to adjusted coding.",
        severity="major",
        comparability="comparable_with_adjustments",
        source_url="https://www.bls.gov/cps/employment-situation-covid19-faq-april-2020.pdf",
        impact_direction="decrease",
        impact_magnitude="About 1 percentage point undercount in April 2020",
    ),
    Phase3Break(
        benchmark_case_id="PH3-004",
        dataset_code="CPS",
        indicator_code="UNEMPLOYMENT_RATE",
        change_type="weighting_update",
        effective_date="2021-01-01",
        description="Updated population controls after the 2020 Census introduced standard January CPS level shifts.",
        impact_estimate="Year-to-year comparisons spanning January 2021 require control-adjusted interpretation.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://www.bls.gov/cps/documentation.htm",
        impact_direction="unknown",
        impact_magnitude="Routine annual control revision",
    ),
    Phase3Break(
        benchmark_case_id="PH3-005",
        dataset_code="CPS",
        indicator_code="UNEMPLOYMENT_RATE",
        change_type="collection_mode",
        effective_date="2020-03-01",
        description="Pandemic field constraints altered interview operations and nonresponse composition in CPS collection.",
        impact_estimate="Potentially elevated nonresponse-related volatility in labor indicators during early pandemic months.",
        severity="moderate",
        comparability="uncertain",
        source_url="https://www.bls.gov/cps/documentation.htm",
        impact_direction="unknown",
        impact_magnitude="Higher short-term variance",
    ),
    Phase3Break(
        benchmark_case_id="PH3-006",
        dataset_code="CPS",
        indicator_code="UNEMPLOYMENT_RATE",
        change_type="definition_change",
        effective_date="2010-01-01",
        description="Expanded labor-force guidance around temporary layoffs and attachment categories affected interpretation of headline unemployment.",
        impact_estimate="Some labor slack moved across adjacent status categories without equivalent real-economy shifts.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://www.bls.gov/cps/documentation.htm",
        impact_direction="unknown",
        impact_magnitude="Category-shift sensitivity",
    ),
    # ACS expansion
    Phase3Break(
        benchmark_case_id="PH3-007",
        dataset_code="ACS",
        indicator_code="MEDIAN_HH_INCOME",
        change_type="collection_mode",
        effective_date="2020-03-01",
        description="ACS suspended in-person interviewing during COVID and shifted to mail/internet-only operations.",
        impact_estimate="Response composition shift raised risk of upward bias in median household income estimates.",
        severity="major",
        comparability="not_comparable",
        source_url="https://www.census.gov/programs-surveys/acs/technical-documentation/user-notes/2020.html",
        impact_direction="increase",
        impact_magnitude="Pandemic nonresponse bias risk",
    ),
    Phase3Break(
        benchmark_case_id="PH3-008",
        dataset_code="ACS",
        indicator_code="MEDIAN_HH_INCOME",
        change_type="weighting_update",
        effective_date="2021-01-01",
        description="ACS weighting and imputation adjustments were revised after abnormal 2020 response patterns.",
        impact_estimate="2020-2021 comparisons require caution because weighting corrections can alter level estimates.",
        severity="moderate",
        comparability="comparable_with_adjustments",
        source_url="https://www.census.gov/programs-surveys/acs/technical-documentation/user-notes.html",
        impact_direction="unknown",
        impact_magnitude="Model-based reweighting changes",
    ),
    Phase3Break(
        benchmark_case_id="PH3-009",
        dataset_code="ACS",
        indicator_code="MEDIAN_HH_INCOME",
        change_type="imputation_method",
        effective_date="2020-01-01",
        description="Higher item nonresponse increased reliance on allocation/imputation for key income variables.",
        impact_estimate="Imputation dependence may dampen or distort true distributional changes.",
        severity="moderate",
        comparability="uncertain",
        source_url="https://www.census.gov/programs-surveys/acs/technical-documentation/user-notes/2020.html",
        impact_direction="unknown",
        impact_magnitude="Higher imputation share",
    ),
    Phase3Break(
        benchmark_case_id="PH3-010",
        dataset_code="ACS",
        indicator_code="MEDIAN_HH_INCOME",
        change_type="sample_redesign",
        effective_date="2019-01-01",
        description="Operational sample balancing updates changed response follow-up emphasis before the pandemic period.",
        impact_estimate="Small composition shifts can influence subgroup and income trend estimates.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://www.census.gov/programs-surveys/acs/technical-documentation/user-notes.html",
        impact_direction="unknown",
        impact_magnitude="Low but non-zero composition shift",
    ),
    Phase3Break(
        benchmark_case_id="PH3-011",
        dataset_code="ACS",
        indicator_code="MEDIAN_HH_INCOME",
        change_type="collection_mode",
        effective_date="2021-01-01",
        description="Post-2020 ACS collection recovery changed response-rate regimes relative to pandemic trough conditions.",
        impact_estimate="Observed rebound partly reflects collection normalization rather than only income growth.",
        severity="moderate",
        comparability="comparable_with_adjustments",
        source_url="https://www.census.gov/programs-surveys/acs/technical-documentation/user-notes.html",
        impact_direction="increase",
        impact_magnitude="Recovery-period comparability caveat",
    ),
    # NHIS expansion
    Phase3Break(
        benchmark_case_id="PH3-012",
        dataset_code="NHIS",
        indicator_code="ECIGARETTE_ADULT",
        change_type="questionnaire_redesign",
        effective_date="2019-01-01",
        description="NHIS questionnaire architecture changed substantially in 2019, affecting several health trend series.",
        impact_estimate="Direct pre/post trend comparisons require redesign-aware adjustments.",
        severity="major",
        comparability="not_comparable",
        source_url="https://www.cdc.gov/nchs/nhis/2019_quest_redesign.htm",
        impact_direction="unknown",
        impact_magnitude="Potential 0.5-1.0pp effect in e-cigarette prevalence",
    ),
    Phase3Break(
        benchmark_case_id="PH3-013",
        dataset_code="NHIS",
        indicator_code="AFFORD_MEDICAL",
        change_type="questionnaire_redesign",
        effective_date="2019-01-01",
        description="Health care access and affordability items were restructured in NHIS 2019 redesign.",
        impact_estimate="Question wording and skip logic changes altered response distributions.",
        severity="major",
        comparability="not_comparable",
        source_url="https://www.cdc.gov/nchs/nhis/2019_quest_redesign.htm",
        impact_direction="unknown",
        impact_magnitude="Break in continuity",
    ),
    Phase3Break(
        benchmark_case_id="PH3-014",
        dataset_code="NHIS",
        indicator_code="ECIGARETTE_ADULT",
        change_type="collection_mode",
        effective_date="2020-03-01",
        description="COVID-era NHIS operational changes modified interview conditions and response patterns.",
        impact_estimate="Pandemic mode shifts may confound short-run prevalence changes.",
        severity="moderate",
        comparability="uncertain",
        source_url="https://www.cdc.gov/nchs/nhis/2019_quest_redesign.htm",
        impact_direction="unknown",
        impact_magnitude="Short-run volatility increase",
    ),
    Phase3Break(
        benchmark_case_id="PH3-015",
        dataset_code="NHIS",
        indicator_code="AFFORD_MEDICAL",
        change_type="sample_redesign",
        effective_date="2019-01-01",
        description="Sample-adult redesign altered domain estimates for insurance and cost barriers.",
        impact_estimate="Cross-year levels should be interpreted with redesign notes.",
        severity="moderate",
        comparability="comparable_with_adjustments",
        source_url="https://www.cdc.gov/nchs/nhis/2019_quest_redesign.htm",
        impact_direction="unknown",
        impact_magnitude="Domain-level level shift",
    ),
    # EU-LFS expansion
    Phase3Break(
        benchmark_case_id="PH3-016",
        dataset_code="EU-LFS",
        indicator_code="EU_UNEMPLOYMENT",
        change_type="definition_change",
        effective_date="2021-01-01",
        description="EU-LFS implemented updated ICLS labor-force definitions from 2021 onward.",
        impact_estimate="Headline unemployment rate moved lower due to definition and reference changes.",
        severity="major",
        comparability="not_comparable",
        source_url="https://ec.europa.eu/eurostat/web/lfs/methodology",
        impact_direction="decrease",
        impact_magnitude="Around 0.3-0.4pp lower unemployment rate",
    ),
    Phase3Break(
        benchmark_case_id="PH3-017",
        dataset_code="EU-LFS",
        indicator_code="EU_UNEMPLOYMENT",
        change_type="collection_mode",
        effective_date="2020-03-01",
        description="Pandemic disruptions shifted labor-force interview modes across member states.",
        impact_estimate="Cross-country measurement comparability weakened during pandemic collection disruptions.",
        severity="moderate",
        comparability="uncertain",
        source_url="https://ec.europa.eu/eurostat/web/lfs/methodology",
        impact_direction="unknown",
        impact_magnitude="Country-specific mode effects",
    ),
    Phase3Break(
        benchmark_case_id="PH3-018",
        dataset_code="EU-LFS",
        indicator_code="EU_UNEMPLOYMENT",
        change_type="classification_change",
        effective_date="2021-01-01",
        description="Temporary layoff and job-search treatment updates changed category mapping in LFS outputs.",
        impact_estimate="Part of post-2021 trend movement reflects recoding rather than labor-demand shocks.",
        severity="moderate",
        comparability="comparable_with_adjustments",
        source_url="https://ec.europa.eu/eurostat/statistics-explained/index.php?title=EU_Labour_Force_Survey_-_new_methodology_from_2021_onwards",
        impact_direction="decrease",
        impact_magnitude="Reclassification contribution to level change",
    ),
    Phase3Break(
        benchmark_case_id="PH3-019",
        dataset_code="EU-LFS",
        indicator_code="EU_UNEMPLOYMENT",
        change_type="weighting_update",
        effective_date="2022-01-01",
        description="Post-method-change calibration updates were applied to improve harmonized labor estimates.",
        impact_estimate="Calibration revisions can generate minor annual discontinuities.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://ec.europa.eu/eurostat/web/lfs/methodology",
        impact_direction="unknown",
        impact_magnitude="Minor annual level shifts",
    ),
    # CPI/HICP expansion
    Phase3Break(
        benchmark_case_id="PH3-020",
        dataset_code="CPI",
        indicator_code="CPI_ALL",
        change_type="collection_mode",
        effective_date="2020-03-01",
        description="COVID restrictions reduced in-person price collection and forced broader imputation in CPI.",
        impact_estimate="Category-level inflation rates became more model-dependent during shutdown periods.",
        severity="major",
        comparability="not_comparable",
        source_url="https://www.bls.gov/cpi/covid-19-impact.htm",
        impact_direction="unknown",
        impact_magnitude="Large temporary imputation share",
    ),
    Phase3Break(
        benchmark_case_id="PH3-021",
        dataset_code="CPI",
        indicator_code="CPI_ALL",
        change_type="weighting_update",
        effective_date="2023-01-01",
        description="BLS moved to annual CPI weights from two-year weight updates.",
        impact_estimate="Short-term inflation comparisons around annual reweighting points need caution.",
        severity="moderate",
        comparability="comparable_with_adjustments",
        source_url="https://www.bls.gov/cpi/notices/2022/methodology-changes.htm",
        impact_direction="unknown",
        impact_magnitude="Composition-driven annual shift",
    ),
    Phase3Break(
        benchmark_case_id="PH3-022",
        dataset_code="CPI",
        indicator_code="CPI_ALL",
        change_type="imputation_method",
        effective_date="2020-04-01",
        description="Expanded carry-forward and class-mean imputation for missing CPI observations during closures.",
        impact_estimate="Methodological smoothing may understate true short-run volatility.",
        severity="moderate",
        comparability="uncertain",
        source_url="https://www.bls.gov/cpi/covid-19-impact.htm",
        impact_direction="decrease",
        impact_magnitude="Potential volatility dampening",
    ),
    Phase3Break(
        benchmark_case_id="PH3-023",
        dataset_code="HICP",
        indicator_code="HICP_ALL",
        change_type="imputation_method",
        effective_date="2020-03-01",
        description="Eurostat pandemic guidance expanded imputation usage where prices were temporarily unavailable.",
        impact_estimate="Cross-country category comparability weakened due to differing imputation paths.",
        severity="moderate",
        comparability="uncertain",
        source_url="https://ec.europa.eu/eurostat/documents/10186/10693286/Guidance-on-the-compilation-of-HICP.pdf",
        impact_direction="unknown",
        impact_magnitude="Heterogeneous imputation effects",
    ),
    Phase3Break(
        benchmark_case_id="PH3-024",
        dataset_code="HICP",
        indicator_code="HICP_ALL",
        change_type="weighting_update",
        effective_date="2021-01-01",
        description="Consumption basket weights were unusually reallocated after pandemic demand shocks.",
        impact_estimate="Measured inflation partly reflects abrupt basket updates rather than pure price shifts.",
        severity="moderate",
        comparability="comparable_with_adjustments",
        source_url="https://ec.europa.eu/eurostat/web/hicp/methodology",
        impact_direction="unknown",
        impact_magnitude="Noticeable basket reweighting impact",
    ),
    Phase3Break(
        benchmark_case_id="PH3-025",
        dataset_code="HICP",
        indicator_code="HICP_ALL",
        change_type="collection_mode",
        effective_date="2020-03-01",
        description="HICP collection mode changed under lockdown with temporary outlet closures and substitution effects.",
        impact_estimate="Country-level series continuity degraded in constrained collection windows.",
        severity="moderate",
        comparability="uncertain",
        source_url="https://ec.europa.eu/eurostat/web/hicp/methodology",
        impact_direction="unknown",
        impact_magnitude="Country-specific measurement artifacts",
    ),
    # Mortality and accounts
    Phase3Break(
        benchmark_case_id="PH3-026",
        dataset_code="EU-MORTALITY",
        indicator_code="EXCESS_MORTALITY",
        change_type="other",
        effective_date="2020-01-01",
        description="Delayed death registration and revision cycles changed early-release excess mortality levels.",
        impact_estimate="Initial excess mortality values were revised as late reports arrived.",
        severity="moderate",
        comparability="uncertain",
        source_url="https://ec.europa.eu/eurostat/cache/metadata/EN/demomwk_esms.htm",
        impact_direction="increase",
        impact_magnitude="Upward revisions in some waves",
    ),
    Phase3Break(
        benchmark_case_id="PH3-027",
        dataset_code="EU-MORTALITY",
        indicator_code="EXCESS_MORTALITY",
        change_type="definition_change",
        effective_date="2021-01-01",
        description="Baseline-window and reference-population adjustments changed interpretation of excess mortality percentages.",
        impact_estimate="Cross-period excess mortality comparisons can be sensitive to baseline recalibration.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Excess_mortality_-_statistics",
        impact_direction="unknown",
        impact_magnitude="Baseline-sensitive percentage changes",
    ),
    Phase3Break(
        benchmark_case_id="PH3-028",
        dataset_code="ESA2010",
        indicator_code="GDP_LEVEL",
        change_type="classification_change",
        effective_date="2014-09-01",
        description="ESA 2010 introduced major national-accounts reclassification including R&D capitalization.",
        impact_estimate="GDP levels increased structurally due to accounting treatment updates.",
        severity="major",
        comparability="not_comparable",
        source_url="https://ec.europa.eu/eurostat/web/esa-2010",
        impact_direction="increase",
        impact_magnitude="2-4% GDP level shift in many countries",
    ),
    Phase3Break(
        benchmark_case_id="PH3-029",
        dataset_code="ESA2010",
        indicator_code="GDP_LEVEL",
        change_type="definition_change",
        effective_date="2019-01-01",
        description="Supplemental benchmark revisions and balancing updates in national accounts altered GDP level comparability.",
        impact_estimate="Some period-to-period GDP differences reflect accounting refinements.",
        severity="moderate",
        comparability="comparable_with_adjustments",
        source_url="https://ec.europa.eu/eurostat/web/esa-2010",
        impact_direction="unknown",
        impact_magnitude="Benchmark revision level effects",
    ),
    # EU-SILC expansion
    Phase3Break(
        benchmark_case_id="PH3-030",
        dataset_code="EU-SILC",
        indicator_code="AROP_RATE",
        change_type="sample_redesign",
        effective_date="2016-01-01",
        description="Ireland EU-SILC adopted administrative income data and introduced an explicit series break.",
        impact_estimate="Part of at-risk-of-poverty movement is methodological rather than socioeconomic.",
        severity="major",
        comparability="not_comparable",
        source_url="https://www.cso.ie/en/releasesandpublications/er/silc/surveyonincomeandlivingconditionssilc2016/",
        impact_direction="decrease",
        impact_magnitude="Documented break in national series",
    ),
    Phase3Break(
        benchmark_case_id="PH3-031",
        dataset_code="EU-SILC",
        indicator_code="AROP_RATE",
        change_type="collection_mode",
        effective_date="2020-03-01",
        description="Pandemic effects disrupted interview operations and response quality in EU-SILC panels.",
        impact_estimate="Cross-year poverty comparisons around 2020-2021 carry nonresponse comparability risk.",
        severity="moderate",
        comparability="uncertain",
        source_url="https://ec.europa.eu/eurostat/web/income-and-living-conditions/methodology",
        impact_direction="unknown",
        impact_magnitude="Panel attrition and response bias risk",
    ),
    Phase3Break(
        benchmark_case_id="PH3-032",
        dataset_code="EU-SILC",
        indicator_code="AROP_RATE",
        change_type="weighting_update",
        effective_date="2021-01-01",
        description="Post-pandemic calibration adjustments altered SILC weighting structures in several member states.",
        impact_estimate="Reweighting may shift reported poverty rates without equivalent welfare changes.",
        severity="moderate",
        comparability="comparable_with_adjustments",
        source_url="https://ec.europa.eu/eurostat/web/income-and-living-conditions/methodology",
        impact_direction="unknown",
        impact_magnitude="Calibration-driven level adjustment",
    ),
    Phase3Break(
        benchmark_case_id="PH3-033",
        dataset_code="EU-SILC",
        indicator_code="AROP_RATE",
        change_type="definition_change",
        effective_date="2022-01-01",
        description="Indicator framework refinements for deprivation/poverty domains affected historical comparability flags.",
        impact_estimate="Trend interpretation requires alignment on old/new indicator definitions.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://ec.europa.eu/eurostat/web/income-and-living-conditions/methodology",
        impact_direction="unknown",
        impact_magnitude="Indicator-definition sensitivity",
    ),
    # Extra CPS/CPI/EU-LFS events for 40+ total
    Phase3Break(
        benchmark_case_id="PH3-034",
        dataset_code="CPS",
        indicator_code="UNEMPLOYMENT_RATE",
        change_type="weighting_update",
        effective_date="2017-01-01",
        description="Annual CPS population control update generated routine level revisions.",
        impact_estimate="January year-over-year comparisons should account for control effects.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://www.bls.gov/cps/documentation.htm",
        impact_direction="unknown",
        impact_magnitude="Minor January discontinuity",
    ),
    Phase3Break(
        benchmark_case_id="PH3-035",
        dataset_code="CPS",
        indicator_code="UNEMPLOYMENT_RATE",
        change_type="weighting_update",
        effective_date="2018-01-01",
        description="Annual CPS controls updated labor-force benchmark levels.",
        impact_estimate="Month-to-month continuity around January includes benchmark revision effects.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://www.bls.gov/cps/documentation.htm",
        impact_direction="unknown",
        impact_magnitude="Minor benchmark shift",
    ),
    Phase3Break(
        benchmark_case_id="PH3-036",
        dataset_code="CPS",
        indicator_code="UNEMPLOYMENT_RATE",
        change_type="weighting_update",
        effective_date="2019-01-01",
        description="CPS annual population controls revised employment/unemployment levels.",
        impact_estimate="Comparable trend analysis should reference annual control notes.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://www.bls.gov/cps/documentation.htm",
        impact_direction="unknown",
        impact_magnitude="Minor annual level shift",
    ),
    Phase3Break(
        benchmark_case_id="PH3-037",
        dataset_code="CPI",
        indicator_code="CPI_ALL",
        change_type="weighting_update",
        effective_date="2024-01-01",
        description="Annual CPI weight update changed expenditure composition entering 2024.",
        impact_estimate="Inflation components can shift at reweighting boundaries independently of pure price change.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://www.bls.gov/cpi/notices/2022/methodology-changes.htm",
        impact_direction="unknown",
        impact_magnitude="Annual basket reset effect",
    ),
    Phase3Break(
        benchmark_case_id="PH3-038",
        dataset_code="EU-LFS",
        indicator_code="EU_UNEMPLOYMENT",
        change_type="collection_mode",
        effective_date="2022-01-01",
        description="Post-transition operational harmonization in EU-LFS changed implementation details across member states.",
        impact_estimate="Some cross-country differences reflect implementation timing rather than labor fundamentals.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://ec.europa.eu/eurostat/web/lfs/methodology",
        impact_direction="unknown",
        impact_magnitude="Harmonization lag effects",
    ),
    Phase3Break(
        benchmark_case_id="PH3-039",
        dataset_code="HICP",
        indicator_code="HICP_ALL",
        change_type="weighting_update",
        effective_date="2022-01-01",
        description="HICP weights were revised with pandemic-era consumption rebalancing still influencing category shares.",
        impact_estimate="Post-pandemic inflation comparisons remain sensitive to basket normalization speed.",
        severity="minor",
        comparability="comparable_with_adjustments",
        source_url="https://ec.europa.eu/eurostat/web/hicp/methodology",
        impact_direction="unknown",
        impact_magnitude="Category-share normalization",
    ),
    Phase3Break(
        benchmark_case_id="PH3-040",
        dataset_code="EU-MORTALITY",
        indicator_code="EXCESS_MORTALITY",
        change_type="other",
        effective_date="2022-01-01",
        description="Ongoing backfill and release cadence adjustments affected the timing profile of excess mortality indicators.",
        impact_estimate="Short-horizon trend turns can be revised as delayed registrations are incorporated.",
        severity="minor",
        comparability="uncertain",
        source_url="https://ec.europa.eu/eurostat/cache/metadata/EN/demomwk_esms.htm",
        impact_direction="unknown",
        impact_magnitude="Publication-lag revision risk",
    ),
]


AGENCY_UPSERT_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("CDC", "Centers for Disease Control and Prevention", "USA", "https://www.cdc.gov"),
    ("BLS", "Bureau of Labor Statistics", "USA", "https://www.bls.gov"),
    ("CENSUS", "U.S. Census Bureau", "USA", "https://www.census.gov"),
    ("EUROSTAT", "European Statistical Office", "EU", "https://ec.europa.eu/eurostat"),
    ("ECB", "European Central Bank", "EU", "https://www.ecb.europa.eu"),
    ("CSO", "Central Statistics Office", "Ireland", "https://www.cso.ie"),
    ("FED", "Board of Governors of the Federal Reserve System", "USA", "https://www.federalreserve.gov"),
    ("NBER", "National Bureau of Economic Research", "USA", "https://www.nber.org"),
    ("UNECE", "United Nations Economic Commission for Europe", "INTL", "https://unece.org"),
)


def _ensure_agencies(cur: psycopg.Cursor) -> None:
    for code, name, country, url in AGENCY_UPSERT_ROWS:
        cur.execute(
            """
            INSERT INTO agencies (code, name, country, url)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                country = EXCLUDED.country,
                url = EXCLUDED.url
            """,
            (code, name, country, url),
        )


def _section(text: str, start: str, end: str) -> list[str]:
    start_idx = text.find(start)
    if start_idx == -1:
        return []
    end_idx = text.find(end, start_idx)
    if end_idx == -1:
        end_idx = len(text)
    return text[start_idx:end_idx].splitlines()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _domain(url: str) -> str:
    value = re.sub(r"^https?://", "", url)
    return value.split("/", 1)[0].lower()


def _guess_agency_code(url: str | None, title: str) -> str | None:
    if url:
        domain = _domain(url)
        for known_domain, code in DOMAIN_TO_AGENCY_CODE.items():
            if domain.endswith(known_domain):
                return code
    title_lower = title.lower()
    if "eurostat" in title_lower:
        return "EUROSTAT"
    if "census" in title_lower:
        return "CENSUS"
    if "bls" in title_lower:
        return "BLS"
    if "nhis" in title_lower or "cdc" in title_lower:
        return "CDC"
    return None


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    cleaned = _normalize(text)
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunks.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def parse_marina_file(path: Path) -> list[CorpusDocument]:
    text = path.read_text(encoding="utf-8")
    docs: list[CorpusDocument] = []

    key_docs_lines = _section(
        text,
        "### Key Methodology Documentation",
        "### Papers for Validation Evidence",
    )
    for line in key_docs_lines:
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^\d+\.\s*(.+)$", line)
        if not match:
            continue
        content = match.group(1)
        parts = [part.strip() for part in content.split(" - ") if part.strip()]
        title = parts[0]
        summary = " - ".join(parts[1:]) if len(parts) > 1 else title
        url = KNOWN_METHOD_DOC_URLS.get(title)
        docs.append(
            CorpusDocument(
                title=title,
                doc_type="methodology_note",
                summary=summary,
                url=url,
                agency_code=_guess_agency_code(url, title),
            )
        )

    paper_lines = _section(text, "### Papers for Validation Evidence", "## Test Cases")
    for line in paper_lines:
        line = line.strip()
        if not line or line.startswith("|"):
            continue
        match = re.match(r"^(.*?)\s*-\s*(https?://\S+)\s*$", line)
        if not match:
            continue
        title = _normalize(match.group(1))
        url = match.group(2).strip()
        docs.append(
            CorpusDocument(
                title=title,
                doc_type="validation_paper",
                summary=title,
                url=url,
                agency_code=_guess_agency_code(url, title),
            )
        )

    # De-duplicate by URL first, then title/type pair.
    deduped: dict[str, CorpusDocument] = {}
    for doc in docs:
        key = doc.url or f"{doc.doc_type}:{doc.title.lower()}"
        deduped[key] = doc
    return list(deduped.values())


def _reference_docs(marina_path: Path) -> list[CorpusDocument]:
    docs = parse_marina_file(marina_path)
    for row in EXTRA_REFERENCE_DOCS:
        docs.append(
            CorpusDocument(
                title=row["title"],
                doc_type=row["doc_type"],
                summary=row["summary"],
                url=row["url"],
                agency_code=_guess_agency_code(row["url"], row["title"]),
            )
        )

    deduped: dict[str, CorpusDocument] = {}
    for doc in docs:
        key = doc.url or f"{doc.doc_type}:{doc.title.lower()}"
        deduped[key] = doc
    return list(deduped.values())


def _upsert_document(cur: psycopg.Cursor, doc: CorpusDocument) -> int:
    if doc.url:
        cur.execute("SELECT id FROM documents WHERE url = %s", (doc.url,))
        row = cur.fetchone()
        if row:
            doc_id = row[0]
            cur.execute(
                """
                UPDATE documents
                SET title = %s,
                    doc_type = %s,
                    agency_id = (SELECT id FROM agencies WHERE code = %s),
                    publication_date = %s
                WHERE id = %s
                """,
                (
                    doc.title,
                    doc.doc_type,
                    doc.agency_code,
                    doc.publication_date,
                    doc_id,
                ),
            )
            return int(doc_id)

    cur.execute(
        """
        SELECT id
        FROM documents
        WHERE title = %s AND doc_type = %s
        ORDER BY id
        LIMIT 1
        """,
        (doc.title, doc.doc_type),
    )
    row = cur.fetchone()
    if row:
        return int(row[0])

    cur.execute(
        """
        INSERT INTO documents (title, doc_type, agency_id, url, publication_date)
        VALUES (%s, %s, (SELECT id FROM agencies WHERE code = %s), %s, %s)
        RETURNING id
        """,
        (doc.title, doc.doc_type, doc.agency_code, doc.url, doc.publication_date),
    )
    return int(cur.fetchone()[0])


def _upsert_chunks(
    cur: psycopg.Cursor,
    doc_id: int,
    chunks: list[str],
    metadata: dict[str, Any],
) -> None:
    metadata_json = json.dumps(metadata)
    for idx, chunk in enumerate(chunks):
        cur.execute(
            """
            INSERT INTO document_chunks (document_id, chunk_index, content, metadata)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (document_id, chunk_index) DO UPDATE
            SET content = EXCLUDED.content,
                metadata = EXCLUDED.metadata
            """,
            (doc_id, idx, chunk, metadata_json),
        )

    # Remove stale chunks when source text gets shorter.
    cur.execute(
        """
        DELETE FROM document_chunks
        WHERE document_id = %s AND chunk_index >= %s
        """,
        (doc_id, len(chunks)),
    )


def ingest_marina_corpus(
    marina_path: Path,
    *,
    chunk_size: int = 1000,
    overlap: int = 150,
    dry_run: bool = False,
) -> dict[str, int]:
    """Compatibility ingest: parse knowledge lists and index short summaries."""
    docs = parse_marina_file(marina_path)
    stats = {"documents_seen": len(docs), "documents_written": 0, "chunks_written": 0}

    if dry_run:
        return stats

    with psycopg.connect(get_db_url()) as conn:
        with conn.cursor() as cur:
            _ensure_agencies(cur)
            for doc in docs:
                doc_id = _upsert_document(cur, doc)
                chunk_text = (
                    f"{doc.title}\n\n{doc.summary}\n\nSource URL: {doc.url or 'n/a'}"
                )
                chunks = _chunk_text(chunk_text, chunk_size, overlap)
                if not chunks:
                    continue
                _upsert_chunks(
                    cur,
                    doc_id,
                    chunks,
                    metadata={"source": "MARINA.md", "doc_type": doc.doc_type},
                )
                stats["documents_written"] += 1
                stats["chunks_written"] += len(chunks)
        conn.commit()

    return stats


def _extract_html_text(content: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", content)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return _normalize(text)


def _extract_pdf_text(payload: bytes) -> str:
    """Best-effort PDF extraction with optional pypdf fallback."""
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(payload))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
        extracted = "\n".join(pages)
        if extracted.strip():
            return _normalize(extracted)
    except Exception:
        pass

    # Last-resort heuristic extraction for environments without PDF tooling.
    decoded = payload.decode("latin-1", errors="ignore")
    decoded = re.sub(r"[^\x20-\x7E\n]", " ", decoded)
    decoded = re.sub(r"\s+", " ", decoded)
    return decoded.strip()


def _fetch_url_content(url: str, timeout: float = 30.0) -> tuple[str, dict[str, Any]]:
    meta: dict[str, Any] = {
        "url": url,
        "status_code": None,
        "content_type": None,
        "fetched": False,
        "error": None,
    }
    headers = {
        "User-Agent": "ALETHEIA/0.1 (+https://github.com/aletheia-research)",
        "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,*/*;q=0.8",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            meta["status_code"] = response.status_code
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            meta["content_type"] = content_type
            meta["final_url"] = str(response.url)

            if "pdf" in content_type or str(response.url).lower().endswith(".pdf"):
                text = _extract_pdf_text(response.content)
            elif "html" in content_type or "xml" in content_type:
                text = _extract_html_text(response.text)
            else:
                text = _normalize(response.text)

            meta["fetched"] = True
            return text, meta
    except Exception as exc:  # noqa: BLE001
        meta["error"] = str(exc)
        return "", meta


def ingest_reference_urls(
    marina_path: Path,
    *,
    chunk_size: int = 1200,
    overlap: int = 150,
    max_docs: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Fetch and ingest methodology references (HTML/PDF) from knowledge + extras."""
    docs = _reference_docs(marina_path)
    if max_docs is not None:
        docs = docs[: max(0, max_docs)]

    stats = {
        "documents_seen": len(docs),
        "documents_written": 0,
        "chunks_written": 0,
        "fetch_success": 0,
        "fetch_failed": 0,
    }

    if dry_run:
        return stats

    with psycopg.connect(get_db_url()) as conn:
        with conn.cursor() as cur:
            _ensure_agencies(cur)
            for doc in docs:
                if not doc.url:
                    continue
                fetched_text, fetch_meta = _fetch_url_content(doc.url)
                if fetched_text:
                    stats["fetch_success"] += 1
                else:
                    stats["fetch_failed"] += 1

                doc_id = _upsert_document(cur, doc)
                content = (
                    f"{doc.title}\n\n{doc.summary}\n\nSource URL: {doc.url}\n\n"
                    f"{fetched_text if fetched_text else 'No content extracted; see metadata for fetch error.'}"
                )
                chunks = _chunk_text(content, chunk_size, overlap)
                if not chunks:
                    continue
                _upsert_chunks(
                    cur,
                    doc_id,
                    chunks,
                    metadata={
                        "source": "phase3_url_ingest",
                        "doc_type": doc.doc_type,
                        "fetch": fetch_meta,
                        "domain": (urlparse(doc.url).netloc or "").lower(),
                    },
                )
                stats["documents_written"] += 1
                stats["chunks_written"] += len(chunks)
        conn.commit()

    return stats


def seed_phase3_methodology_breaks(
    *,
    dry_run: bool = False,
    conn: psycopg.Connection | None = None,
) -> dict[str, int]:
    """Insert expanded methodology-break corpus for Phase 3 coverage."""
    stats = {
        "break_rows_target": len(PHASE3_BREAKS),
        "break_rows_written": 0,
        "impact_links_written": 0,
        "impact_links_skipped_missing_indicator": 0,
    }
    if dry_run:
        return stats

    own_connection = conn is None
    active_conn = conn or psycopg.connect(get_db_url())
    try:
        with active_conn.cursor() as cur:
            _ensure_agencies(cur)
            for row in PHASE3_BREAKS:
                cur.execute(
                    """
                    INSERT INTO methodology_changes (
                        benchmark_case_id,
                        dataset_id,
                        change_type,
                        effective_date,
                        description,
                        impact_estimate,
                        severity,
                        comparability,
                        is_documented,
                        source_url
                    )
                    VALUES (
                        %s,
                        (SELECT id FROM datasets WHERE code = %s),
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        TRUE,
                        %s
                    )
                    ON CONFLICT (benchmark_case_id) DO UPDATE SET
                        dataset_id = EXCLUDED.dataset_id,
                        change_type = EXCLUDED.change_type,
                        effective_date = EXCLUDED.effective_date,
                        description = EXCLUDED.description,
                        impact_estimate = EXCLUDED.impact_estimate,
                        severity = EXCLUDED.severity,
                        comparability = EXCLUDED.comparability,
                        is_documented = EXCLUDED.is_documented,
                        source_url = EXCLUDED.source_url
                    RETURNING id
                    """,
                    (
                        row.benchmark_case_id,
                        row.dataset_code,
                        row.change_type,
                        row.effective_date,
                        row.description,
                        row.impact_estimate,
                        row.severity,
                        row.comparability,
                        row.source_url,
                    ),
                )
                inserted = cur.fetchone()
                if not inserted:
                    continue
                change_id = int(inserted[0])
                stats["break_rows_written"] += 1

                cur.execute(
                    """
                    SELECT i.id AS indicator_id
                    FROM indicators i
                    JOIN datasets d ON d.id = i.dataset_id
                    WHERE d.code = %s AND i.code = %s
                    LIMIT 1
                    """,
                    (row.dataset_code, row.indicator_code),
                )
                indicator = cur.fetchone()
                if not indicator:
                    stats["impact_links_skipped_missing_indicator"] += 1
                    continue
                indicator_id = int(indicator[0])

                cur.execute(
                    """
                    INSERT INTO change_indicator_impacts (change_id, indicator_id, impact_direction, impact_magnitude)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (change_id, indicator_id) DO UPDATE SET
                        impact_direction = EXCLUDED.impact_direction,
                        impact_magnitude = EXCLUDED.impact_magnitude
                    """,
                    (
                        change_id,
                        indicator_id,
                        row.impact_direction,
                        row.impact_magnitude,
                    ),
                )
                stats["impact_links_written"] += 1
        if own_connection:
            active_conn.commit()
    finally:
        if own_connection:
            active_conn.close()

    return stats


def _table_count(cur: psycopg.Cursor, table: str) -> int:
    cur.execute(
        sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0


def ingest_local_directory(
    dir_path: Path,
    *,
    chunk_size: int = 1200,
    overlap: int = 150,
    dry_run: bool = False,
) -> dict[str, int]:
    """Ingest all generic documents (PDF, MD, TXT, HTML) from a directory."""
    stats = {
        "files_seen": 0,
        "files_ingested": 0,
        "chunks_written": 0,
        "errors": 0,
    }

    if dry_run or not dir_path.exists() or not dir_path.is_dir():
        return stats

    with psycopg.connect(get_db_url()) as conn:
        with conn.cursor() as cur:
            _ensure_agencies(cur)
            for filepath in dir_path.rglob("*"):
                if not filepath.is_file():
                    continue

                stats["files_seen"] += 1
                ext = filepath.suffix.lower()
                text = ""

                try:
                    if ext == ".pdf":
                        text = _extract_pdf_text(filepath.read_bytes())
                    elif ext in (".html", ".htm"):
                        text = _extract_html_text(filepath.read_text(encoding="utf-8", errors="ignore"))
                    elif ext in (".md", ".txt"):
                        text = _normalize(filepath.read_text(encoding="utf-8", errors="ignore"))
                    else:
                        continue
                except Exception:
                    stats["errors"] += 1
                    continue

                if not text:
                    continue

                doc = CorpusDocument(
                    title=filepath.name,
                    doc_type="local_knowledge",
                    summary=f"Local knowledge file: {filepath.name}",
                    url=f"file://{filepath.absolute()}",
                )

                doc_id = _upsert_document(cur, doc)
                content = f"{doc.title}\n\n{text}"
                chunks = _chunk_text(content, chunk_size, overlap)

                if not chunks:
                    continue

                _upsert_chunks(
                    cur,
                    doc_id,
                    chunks,
                    metadata={
                        "source": "local_directory",
                        "doc_type": doc.doc_type,
                        "filename": filepath.name,
                        "filepath": str(filepath),
                    },
                )
                stats["files_ingested"] += 1
                stats["chunks_written"] += len(chunks)
        conn.commit()

    return stats


def kb_counts() -> dict[str, int]:
    with psycopg.connect(get_db_url()) as conn:
        with conn.cursor() as cur:
            return {
                "methodology_changes": _table_count(cur, "methodology_changes"),
                "document_chunks": _table_count(cur, "document_chunks"),
                "documents": _table_count(cur, "documents"),
            }


def run_phase3_ingest(
    marina_path: Path,
    *,
    chunk_size: int,
    overlap: int,
    dry_run: bool,
    seed_phase3: bool,
    fetch_urls: bool,
    max_docs: int | None,
    materialize_embeddings: bool,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "marina": ingest_marina_corpus(
            marina_path,
            chunk_size=chunk_size,
            overlap=overlap,
            dry_run=dry_run,
        )
    }

    if seed_phase3:
        output["phase3_breaks"] = seed_phase3_methodology_breaks(dry_run=dry_run)

    if fetch_urls:
        output["url_ingest"] = ingest_reference_urls(
            marina_path,
            chunk_size=chunk_size,
            overlap=overlap,
            max_docs=max_docs,
            dry_run=dry_run,
        )

    if not dry_run:
        output["counts"] = kb_counts()

    if materialize_embeddings and not dry_run:
        from aletheia.vectorizer import (
            create_vectorizers,
            materialize_embeddings_once,
            vectorizer_status,
        )

        create_vectorizers()
        output["materialize"] = materialize_embeddings_once()
        output["vectorizer"] = vectorizer_status()

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest methodology notes and papers into the ALETHEIA knowledge base."
    )
    parser.add_argument(
        "--marina-path",
        default="MARINA.md",
        help="Path to MARINA.md",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1200,
        help="Character chunk size.",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=150,
        help="Character overlap between chunks.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report counts without writing to DB.",
    )
    parser.add_argument(
        "--seed-phase3",
        action="store_true",
        help="Insert expanded methodology-break corpus (PH3-xxx rows).",
    )
    parser.add_argument(
        "--fetch-urls",
        action="store_true",
        help="Fetch and ingest full text from knowledge/external reference URLs.",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=None,
        help="Optional cap on number of URLs to fetch.",
    )
    parser.add_argument(
        "--materialize-embeddings",
        action="store_true",
        help="Run vectorizer setup/status after ingest writes.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Override ALETHEIA_DB_URL for this ingest run.",
    )
    args = parser.parse_args()

    if args.db_url:
        os.environ["ALETHEIA_DB_URL"] = args.db_url

    stats = run_phase3_ingest(
        Path(args.marina_path),
        chunk_size=args.chunk_size,
        overlap=args.chunk_overlap,
        dry_run=args.dry_run,
        seed_phase3=bool(args.seed_phase3),
        fetch_urls=bool(args.fetch_urls),
        max_docs=args.max_docs,
        materialize_embeddings=bool(args.materialize_embeddings),
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
