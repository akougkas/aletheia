-- Validation checks for Marina benchmark seed integrity.
-- Run after sql/seed_cases.sql. Raises an exception on failure.

DO $$
DECLARE
    expected_case_ids TEXT[] := ARRAY[
        'MB-001', 'MB-002', 'MB-003', 'MB-004', 'MB-005',
        'MB-006', 'MB-007', 'MB-008', 'MB-009', 'MB-010'
    ];
    missing_case_ids TEXT[];
    expected_case_count INTEGER := 10;
    case_count INTEGER;
    linked_case_count INTEGER;
    unlinked_count INTEGER;
    wrong_case8_dataset_count INTEGER;
BEGIN
    SELECT COUNT(*)
    INTO case_count
    FROM methodology_changes
    WHERE benchmark_case_id = ANY(expected_case_ids);

    IF case_count <> expected_case_count THEN
        RAISE EXCEPTION
            'Expected % benchmark cases, found %',
            expected_case_count,
            case_count;
    END IF;

    SELECT ARRAY_AGG(case_id)
    INTO missing_case_ids
    FROM (
        SELECT c AS case_id
        FROM UNNEST(expected_case_ids) AS c
        WHERE NOT EXISTS (
            SELECT 1
            FROM methodology_changes mc
            WHERE mc.benchmark_case_id = c
        )
        ORDER BY c
    ) missing;

    IF missing_case_ids IS NOT NULL THEN
        RAISE EXCEPTION 'Missing benchmark_case_id values: %', missing_case_ids;
    END IF;

    SELECT COUNT(DISTINCT mc.benchmark_case_id)
    INTO linked_case_count
    FROM methodology_changes mc
    JOIN change_indicator_impacts cii ON cii.change_id = mc.id
    WHERE mc.benchmark_case_id = ANY(expected_case_ids);

    IF linked_case_count <> expected_case_count THEN
        RAISE EXCEPTION
            'Expected indicator links for % cases, found %',
            expected_case_count,
            linked_case_count;
    END IF;

    SELECT COUNT(*)
    INTO unlinked_count
    FROM methodology_changes mc
    WHERE mc.benchmark_case_id = ANY(expected_case_ids)
      AND NOT EXISTS (
          SELECT 1
          FROM change_indicator_impacts cii
          WHERE cii.change_id = mc.id
      );

    IF unlinked_count > 0 THEN
        RAISE EXCEPTION '% benchmark cases do not map to indicators', unlinked_count;
    END IF;

    SELECT COUNT(*)
    INTO wrong_case8_dataset_count
    FROM methodology_changes mc
    JOIN datasets d ON d.id = mc.dataset_id
    WHERE mc.benchmark_case_id = 'MB-008'
      AND d.code <> 'EU-MORTALITY';

    IF wrong_case8_dataset_count > 0 THEN
        RAISE EXCEPTION
            'MB-008 must be mapped to EU-MORTALITY dataset';
    END IF;

    RAISE NOTICE 'Seed validation passed: % cases with complete indicator links.',
        expected_case_count;
END
$$;
