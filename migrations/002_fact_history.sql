-- Phase six fact-version metadata and run observations.
-- These additive tables avoid ALTER TABLE so restricted application/test users
-- can initialize the feature without mutating phase-one tables.

CREATE TABLE IF NOT EXISTS fact_versions (
    fact_id BIGINT UNSIGNED NOT NULL,
    competitor_id BIGINT UNSIGNED NOT NULL,
    source_id BIGINT UNSIGNED NOT NULL,
    normalized_value JSON NOT NULL,
    normalized_value_hash CHAR(64) NOT NULL,
    valid_from DATETIME(6) NOT NULL,
    valid_to DATETIME(6) NULL,
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    supersedes_fact_id BIGINT UNSIGNED NULL,
    comparison_status ENUM(
        'PENDING', 'BASELINE', 'ADDED', 'REMOVED', 'MODIFIED',
        'UNCHANGED', 'UNCOMPARABLE'
    ) NOT NULL DEFAULT 'PENDING',
    PRIMARY KEY (fact_id),
    CONSTRAINT fk_fact_versions_fact
        FOREIGN KEY (fact_id) REFERENCES product_facts (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_fact_versions_competitor
        FOREIGN KEY (competitor_id) REFERENCES competitors (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_fact_versions_source
        FOREIGN KEY (source_id) REFERENCES sources (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_fact_versions_supersedes
        FOREIGN KEY (supersedes_fact_id) REFERENCES product_facts (id)
        ON DELETE SET NULL ON UPDATE RESTRICT,
    KEY ix_fact_versions_current
        (competitor_id, is_current, fact_id),
    KEY ix_fact_versions_value
        (competitor_id, normalized_value_hash),
    KEY ix_fact_versions_supersedes (supersedes_fact_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS fact_observations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    competitor_id BIGINT UNSIGNED NOT NULL,
    run_id BIGINT UNSIGNED NOT NULL,
    fact_id BIGINT UNSIGNED NOT NULL,
    source_id BIGINT UNSIGNED NOT NULL,
    snapshot_id BIGINT UNSIGNED NOT NULL,
    evidence_text TEXT NOT NULL,
    confidence DECIMAL(5,4) NOT NULL,
    observed_at DATETIME(6) NOT NULL,
    comparison_status ENUM(
        'PENDING', 'BASELINE', 'ADDED', 'REMOVED', 'MODIFIED',
        'UNCHANGED', 'UNCOMPARABLE'
    ) NOT NULL DEFAULT 'PENDING',
    PRIMARY KEY (id),
    CONSTRAINT fk_fact_observations_competitor
        FOREIGN KEY (competitor_id) REFERENCES competitors (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_fact_observations_run
        FOREIGN KEY (run_id) REFERENCES agent_runs (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_fact_observations_fact
        FOREIGN KEY (fact_id) REFERENCES product_facts (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_fact_observations_source
        FOREIGN KEY (source_id) REFERENCES sources (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_fact_observations_snapshot
        FOREIGN KEY (snapshot_id) REFERENCES snapshots (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT ck_fact_observations_confidence
        CHECK (confidence >= 0 AND confidence <= 1),
    UNIQUE KEY uq_fact_observations_run_fact (run_id, fact_id),
    KEY ix_fact_observations_run (competitor_id, run_id),
    KEY ix_fact_observations_fact (fact_id, observed_at),
    KEY ix_fact_observations_source_run (source_id, run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO fact_versions (
    fact_id, competitor_id, source_id, normalized_value,
    normalized_value_hash, valid_from, is_current, comparison_status
)
SELECT
    pf.id, pf.competitor_id, sn.source_id, pf.fact_value,
    SHA2(CAST(pf.fact_value AS CHAR), 256), pf.extracted_at, FALSE, 'PENDING'
FROM product_facts pf
JOIN snapshots sn ON sn.id = pf.snapshot_id;

INSERT IGNORE INTO fact_observations (
    competitor_id, run_id, fact_id, source_id, snapshot_id,
    evidence_text, confidence, observed_at, comparison_status
)
SELECT
    pf.competitor_id, pf.run_id, pf.id, sn.source_id, pf.snapshot_id,
    pf.evidence_text, pf.confidence, pf.extracted_at, 'PENDING'
FROM product_facts pf
JOIN snapshots sn ON sn.id = pf.snapshot_id;

UPDATE fact_versions fv
JOIN product_facts pf ON pf.id = fv.fact_id
JOIN (
    SELECT
        competitor_id, fact_category, fact_key, MAX(id) AS latest_fact_id
    FROM product_facts
    GROUP BY competitor_id, fact_category, fact_key
) latest ON latest.latest_fact_id = pf.id
SET fv.is_current = TRUE, fv.comparison_status = 'BASELINE';
