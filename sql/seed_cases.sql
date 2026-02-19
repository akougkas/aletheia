-- Seed data for Marina's 10 benchmark cases.
-- This script is intentionally idempotent.

-- Agencies
INSERT INTO agencies (code, name, country, url) VALUES
    ('CDC', 'Centers for Disease Control and Prevention', 'USA', 'https://www.cdc.gov'),
    ('BLS', 'Bureau of Labor Statistics', 'USA', 'https://www.bls.gov'),
    ('CENSUS', 'U.S. Census Bureau', 'USA', 'https://www.census.gov'),
    ('EUROSTAT', 'European Statistical Office', 'EU', 'https://ec.europa.eu/eurostat'),
    ('ECB', 'European Central Bank', 'EU', 'https://www.ecb.europa.eu'),
    ('CSO', 'Central Statistics Office', 'Ireland', 'https://www.cso.ie')
ON CONFLICT (code) DO NOTHING;

-- Datasets
INSERT INTO datasets (code, name, agency_id, description, frequency) VALUES
    ('NHIS', 'National Health Interview Survey', (SELECT id FROM agencies WHERE code = 'CDC'),
     'Annual survey of civilian noninstitutionalized population on health topics', 'annual'),
    ('CPS', 'Current Population Survey', (SELECT id FROM agencies WHERE code = 'BLS'),
     'Monthly survey of households on labor force characteristics', 'monthly'),
    ('ACS', 'American Community Survey', (SELECT id FROM agencies WHERE code = 'CENSUS'),
     'Annual survey of demographic, social, economic, and housing characteristics', 'annual'),
    ('CPI', 'Consumer Price Index', (SELECT id FROM agencies WHERE code = 'BLS'),
     'Measures average change in prices paid by urban consumers', 'monthly'),
    ('EU-LFS', 'EU Labour Force Survey', (SELECT id FROM agencies WHERE code = 'EUROSTAT'),
     'Quarterly survey on labor participation across EU member states', 'quarterly'),
    ('HICP', 'Harmonised Index of Consumer Prices', (SELECT id FROM agencies WHERE code = 'EUROSTAT'),
     'Comparable measure of consumer price inflation in the EU', 'monthly'),
    ('EU-MORTALITY', 'Eurostat Weekly Mortality Statistics', (SELECT id FROM agencies WHERE code = 'EUROSTAT'),
     'Weekly excess mortality and delayed registration monitoring for EU countries', 'weekly'),
    ('ESA2010', 'European System of Accounts 2010', (SELECT id FROM agencies WHERE code = 'EUROSTAT'),
     'Macroeconomic accounting framework for EU national accounts', 'annual'),
    ('EU-SILC', 'EU Statistics on Income and Living Conditions', (SELECT id FROM agencies WHERE code = 'EUROSTAT'),
     'Reference source for comparative statistics on income distribution and social exclusion', 'annual')
ON CONFLICT (code) DO NOTHING;

-- Indicators
INSERT INTO indicators (dataset_id, code, name, unit, description) VALUES
    ((SELECT id FROM datasets WHERE code = 'NHIS'), 'ECIGARETTE_ADULT', 'Adult e-cigarette use', 'percent',
     'Percentage of adults who currently use e-cigarettes'),
    ((SELECT id FROM datasets WHERE code = 'NHIS'), 'AFFORD_MEDICAL', 'Unable to afford medical care', 'percent',
     'Percentage of adults who could not afford needed medical care'),
    ((SELECT id FROM datasets WHERE code = 'CPS'), 'UNEMPLOYMENT_RATE', 'Unemployment rate', 'percent',
     'Percentage of labor force that is unemployed'),
    ((SELECT id FROM datasets WHERE code = 'ACS'), 'MEDIAN_HH_INCOME', 'Real median household income', 'dollars',
     'Inflation-adjusted median household income'),
    ((SELECT id FROM datasets WHERE code = 'CPI'), 'CPI_ALL', 'CPI All Items', 'index',
     'Consumer Price Index for All Urban Consumers'),
    ((SELECT id FROM datasets WHERE code = 'EU-LFS'), 'EU_UNEMPLOYMENT', 'EU unemployment rate', 'percent',
     'Unemployment rate for EU member states'),
    ((SELECT id FROM datasets WHERE code = 'HICP'), 'HICP_ALL', 'HICP All Items', 'index',
     'Harmonised Index of Consumer Prices'),
    ((SELECT id FROM datasets WHERE code = 'EU-MORTALITY'), 'EXCESS_MORTALITY', 'Excess mortality', 'percent',
     'Deviation from expected mortality after delayed registrations and revisions'),
    ((SELECT id FROM datasets WHERE code = 'ESA2010'), 'GDP_LEVEL', 'GDP level', 'euros',
     'Gross Domestic Product level'),
    ((SELECT id FROM datasets WHERE code = 'EU-SILC'), 'AROP_RATE', 'At-risk-of-poverty rate', 'percent',
     'Share of population with income below 60% of national median')
ON CONFLICT (dataset_id, code) DO NOTHING;

-- Methodology changes (Marina benchmark cases)
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
) VALUES (
    'MB-001',
    (SELECT id FROM datasets WHERE code = 'NHIS'),
    'questionnaire_redesign',
    '2019-01-01',
    'Major questionnaire redesign in 2019 affected e-cigarette use questions. The redesigned survey changed how e-cigarette use was asked, moving from a two-part question structure to a single direct question. Sample adult questionnaire was completely restructured.',
    'The apparent increase from 3.2% (2018) to 4.4% (2019) in adult e-cigarette use is partially attributable to the questionnaire redesign. NCHS estimates the redesign accounts for approximately 0.5-1.0 percentage points of the observed change.',
    'moderate',
    'comparable_with_adjustments',
    TRUE,
    'https://www.cdc.gov/nchs/nhis/2019_quest_redesign.htm'
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
    source_url = EXCLUDED.source_url;

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
) VALUES (
    'MB-002',
    (SELECT id FROM datasets WHERE code = 'NHIS'),
    'questionnaire_redesign',
    '2019-01-01',
    'The 2019 NHIS redesign also affected questions about healthcare affordability. Questions about inability to afford medical care were restructured, affecting comparability with pre-2019 estimates.',
    'Estimates of adults who could not afford needed medical care are not directly comparable between 2018 and 2019 due to question wording changes.',
    'major',
    'not_comparable',
    TRUE,
    'https://www.cdc.gov/nchs/nhis/2019_quest_redesign.htm'
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
    source_url = EXCLUDED.source_url;

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
) VALUES (
    'MB-003',
    (SELECT id FROM datasets WHERE code = 'CPS'),
    'classification_change',
    '2020-03-01',
    'During COVID-19, many workers who were absent from work due to pandemic-related business closures were misclassified as employed but absent rather than unemployed. BLS acknowledged this classification error but did not adjust published statistics.',
    'BLS estimated the misclassification could have increased the unemployment rate by about 1 percentage point in April 2020 (official rate: 14.7%, adjusted estimate: ~15.7%+).',
    'moderate',
    'comparable_with_adjustments',
    TRUE,
    'https://www.bls.gov/cps/employment-situation-covid19-faq-april-2020.pdf'
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
    source_url = EXCLUDED.source_url;

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
) VALUES (
    'MB-004',
    (SELECT id FROM datasets WHERE code = 'ACS'),
    'collection_mode',
    '2020-03-01',
    'The ACS suspended in-person interviews during COVID-19, leading to decreased response rates and potential nonresponse bias. Lower-income households were less likely to respond to mail and internet surveys alone.',
    'Census Bureau noted that 2020 ACS data may overestimate median household income due to differential nonresponse by income level.',
    'moderate',
    'comparable_with_adjustments',
    TRUE,
    'https://www.census.gov/programs-surveys/acs/technical-documentation/user-notes/2020.html'
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
    source_url = EXCLUDED.source_url;

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
) VALUES (
    'MB-005',
    (SELECT id FROM datasets WHERE code = 'CPI'),
    'collection_mode',
    '2020-03-01',
    'BLS suspended in-person price collection during COVID-19. Many outlets were closed, and prices for unavailable items were imputed or carried forward. This particularly affected services like airfare, lodging, and entertainment.',
    'Items comprising roughly 25% of the CPI basket had limited or imputed price data during spring 2020, affecting the accuracy of inflation measures.',
    'moderate',
    'comparable_with_adjustments',
    TRUE,
    'https://www.bls.gov/cpi/covid-19-impact.htm'
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
    source_url = EXCLUDED.source_url;

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
) VALUES (
    'MB-006',
    (SELECT id FROM datasets WHERE code = 'EU-LFS'),
    'definition_change',
    '2021-01-01',
    'From 2021, the EU-LFS adopted new definitions of employment and unemployment following the 19th ICLS resolution. The reference period changed from one week to four weeks for job search, and treatment of temporary layoffs was modified.',
    'Eurostat estimates the new methodology reduced the EU unemployment rate by approximately 0.3-0.4 percentage points compared to the previous methodology.',
    'moderate',
    'comparable_with_adjustments',
    TRUE,
    'https://ec.europa.eu/eurostat/web/lfs/methodology'
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
    source_url = EXCLUDED.source_url;

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
) VALUES (
    'MB-007',
    (SELECT id FROM datasets WHERE code = 'HICP'),
    'imputation_method',
    '2020-03-01',
    'During COVID-19 lockdowns, many prices could not be collected (restaurants, hotels, package holidays). Eurostat allowed countries to use imputation methods, but approaches varied across countries.',
    'The impact on overall HICP was modest (~0.1pp) but significant for specific categories. Cross-country comparability was reduced during spring 2020.',
    'minor',
    'comparable_with_adjustments',
    TRUE,
    'https://ec.europa.eu/eurostat/documents/10186/10693286/Guidance-on-the-compilation-of-HICP.pdf'
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
    source_url = EXCLUDED.source_url;

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
) VALUES (
    'MB-008',
    (SELECT id FROM datasets WHERE code = 'EU-MORTALITY'),
    'other',
    '2020-01-01',
    'Excess mortality calculations during 2020-2021 were affected by delayed death registrations and revisions. Initial estimates were often revised upward as late registrations were incorporated.',
    'Initial excess mortality estimates for some countries were revised upward by 5-15% as registration backlogs were cleared.',
    'minor',
    'uncertain',
    TRUE,
    'https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Excess_mortality_-_statistics'
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
    source_url = EXCLUDED.source_url;

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
) VALUES (
    'MB-009',
    (SELECT id FROM datasets WHERE code = 'ESA2010'),
    'classification_change',
    '2014-09-01',
    'ESA 2010 introduced new rules for capitalizing R&D expenditure and revised treatment of pension schemes. This changed GDP levels for all EU countries retroactively.',
    'GDP levels increased by 2-4% for most EU countries due to R&D capitalization alone. The UK saw an increase of about 2.5% in GDP level.',
    'major',
    'not_comparable',
    TRUE,
    'https://ec.europa.eu/eurostat/web/esa-2010'
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
    source_url = EXCLUDED.source_url;

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
) VALUES (
    'MB-010',
    (SELECT id FROM datasets WHERE code = 'EU-SILC'),
    'sample_redesign',
    '2016-01-01',
    'Ireland implemented a new income variable in EU-SILC in 2016, using administrative data sources (Revenue Commissioners) instead of purely survey-based income. This is an explicit series break.',
    'CSO flagged this as a break in series. The at-risk-of-poverty rate dropped significantly, but this is partially methodological rather than reflecting real change.',
    'major',
    'not_comparable',
    TRUE,
    'https://www.cso.ie/en/releasesandpublications/er/silc/surveyonincomeandlivingconditionssilc2016/'
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
    source_url = EXCLUDED.source_url;

-- Link each benchmark case to at least one indicator.
INSERT INTO change_indicator_impacts (change_id, indicator_id, impact_direction, impact_magnitude)
SELECT mc.id, i.id, 'increase', '0.5-1.0 percentage points'
FROM methodology_changes mc
JOIN indicators i ON i.code = 'ECIGARETTE_ADULT'
WHERE mc.benchmark_case_id = 'MB-001'
ON CONFLICT (change_id, indicator_id) DO UPDATE
SET impact_direction = EXCLUDED.impact_direction,
    impact_magnitude = EXCLUDED.impact_magnitude;

INSERT INTO change_indicator_impacts (change_id, indicator_id, impact_direction, impact_magnitude)
SELECT mc.id, i.id, 'unknown', NULL
FROM methodology_changes mc
JOIN indicators i ON i.code = 'AFFORD_MEDICAL'
WHERE mc.benchmark_case_id = 'MB-002'
ON CONFLICT (change_id, indicator_id) DO UPDATE
SET impact_direction = EXCLUDED.impact_direction,
    impact_magnitude = EXCLUDED.impact_magnitude;

INSERT INTO change_indicator_impacts (change_id, indicator_id, impact_direction, impact_magnitude)
SELECT mc.id, i.id, 'decrease', '~1 percentage point undercount'
FROM methodology_changes mc
JOIN indicators i ON i.code = 'UNEMPLOYMENT_RATE'
WHERE mc.benchmark_case_id = 'MB-003'
ON CONFLICT (change_id, indicator_id) DO UPDATE
SET impact_direction = EXCLUDED.impact_direction,
    impact_magnitude = EXCLUDED.impact_magnitude;

INSERT INTO change_indicator_impacts (change_id, indicator_id, impact_direction, impact_magnitude)
SELECT mc.id, i.id, 'increase', 'Likely overestimate in 2020 due to nonresponse'
FROM methodology_changes mc
JOIN indicators i ON i.code = 'MEDIAN_HH_INCOME'
WHERE mc.benchmark_case_id = 'MB-004'
ON CONFLICT (change_id, indicator_id) DO UPDATE
SET impact_direction = EXCLUDED.impact_direction,
    impact_magnitude = EXCLUDED.impact_magnitude;

INSERT INTO change_indicator_impacts (change_id, indicator_id, impact_direction, impact_magnitude)
SELECT mc.id, i.id, 'unknown', 'About 25% basket affected by imputation or sparse collection'
FROM methodology_changes mc
JOIN indicators i ON i.code = 'CPI_ALL'
WHERE mc.benchmark_case_id = 'MB-005'
ON CONFLICT (change_id, indicator_id) DO UPDATE
SET impact_direction = EXCLUDED.impact_direction,
    impact_magnitude = EXCLUDED.impact_magnitude;

INSERT INTO change_indicator_impacts (change_id, indicator_id, impact_direction, impact_magnitude)
SELECT mc.id, i.id, 'decrease', 'About 0.3-0.4 percentage point lower under new definitions'
FROM methodology_changes mc
JOIN indicators i ON i.code = 'EU_UNEMPLOYMENT'
WHERE mc.benchmark_case_id = 'MB-006'
ON CONFLICT (change_id, indicator_id) DO UPDATE
SET impact_direction = EXCLUDED.impact_direction,
    impact_magnitude = EXCLUDED.impact_magnitude;

INSERT INTO change_indicator_impacts (change_id, indicator_id, impact_direction, impact_magnitude)
SELECT mc.id, i.id, 'unknown', 'Roughly 0.1 percentage point at aggregate level'
FROM methodology_changes mc
JOIN indicators i ON i.code = 'HICP_ALL'
WHERE mc.benchmark_case_id = 'MB-007'
ON CONFLICT (change_id, indicator_id) DO UPDATE
SET impact_direction = EXCLUDED.impact_direction,
    impact_magnitude = EXCLUDED.impact_magnitude;

INSERT INTO change_indicator_impacts (change_id, indicator_id, impact_direction, impact_magnitude)
SELECT mc.id, i.id, 'increase', 'Initial values revised up by around 5-15%'
FROM methodology_changes mc
JOIN indicators i ON i.code = 'EXCESS_MORTALITY'
WHERE mc.benchmark_case_id = 'MB-008'
ON CONFLICT (change_id, indicator_id) DO UPDATE
SET impact_direction = EXCLUDED.impact_direction,
    impact_magnitude = EXCLUDED.impact_magnitude;

INSERT INTO change_indicator_impacts (change_id, indicator_id, impact_direction, impact_magnitude)
SELECT mc.id, i.id, 'increase', 'GDP level shift around 2-4% from reclassification'
FROM methodology_changes mc
JOIN indicators i ON i.code = 'GDP_LEVEL'
WHERE mc.benchmark_case_id = 'MB-009'
ON CONFLICT (change_id, indicator_id) DO UPDATE
SET impact_direction = EXCLUDED.impact_direction,
    impact_magnitude = EXCLUDED.impact_magnitude;

INSERT INTO change_indicator_impacts (change_id, indicator_id, impact_direction, impact_magnitude)
SELECT mc.id, i.id, 'decrease', 'Observed drop partly methodological from income source redesign'
FROM methodology_changes mc
JOIN indicators i ON i.code = 'AROP_RATE'
WHERE mc.benchmark_case_id = 'MB-010'
ON CONFLICT (change_id, indicator_id) DO UPDATE
SET impact_direction = EXCLUDED.impact_direction,
    impact_magnitude = EXCLUDED.impact_magnitude;
