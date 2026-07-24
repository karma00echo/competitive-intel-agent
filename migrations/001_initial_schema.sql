-- Universal Competitive Intelligence Agent - phase one schema.
-- MySQL 8.0+ / 9.x, InnoDB, utf8mb4.

CREATE TABLE IF NOT EXISTS competitors (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    canonical_name VARCHAR(255) NOT NULL,
    normalized_name VARCHAR(255) NOT NULL,
    aliases JSON NOT NULL,
    official_domain VARCHAR(255) NULL,
    status ENUM('ACTIVE', 'PENDING_CONFIRMATION', 'ARCHIVED') NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_competitors_normalized_name (normalized_name),
    KEY ix_competitors_official_domain (official_domain),
    KEY ix_competitors_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS agent_runs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    competitor_id BIGINT UNSIGNED NULL,
    input_name VARCHAR(255) NOT NULL,
    normalized_input VARCHAR(255) NOT NULL,
    run_mode ENUM('UNKNOWN', 'BASELINE', 'TRACKING') NOT NULL DEFAULT 'UNKNOWN',
    current_state ENUM(
        'SOURCE_DISCOVERY', 'SOURCE_VALIDATION', 'PAGE_FETCHING',
        'FACT_EXTRACTION', 'BASELINE_CREATION', 'HISTORY_COMPARISON',
        'EVIDENCE_CHECKING', 'REPORT_GENERATION', 'COMPLETED', 'FAILED'
    ) NOT NULL,
    status ENUM('RUNNING', 'COMPLETED', 'FAILED') NOT NULL DEFAULT 'RUNNING',
    max_tool_calls SMALLINT UNSIGNED NOT NULL DEFAULT 30,
    tool_call_count SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    finished_at DATETIME(6) NULL,
    error_code VARCHAR(100) NULL,
    error_message TEXT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_agent_runs_competitor
        FOREIGN KEY (competitor_id) REFERENCES competitors (id)
        ON DELETE SET NULL ON UPDATE RESTRICT,
    CONSTRAINT ck_agent_runs_tool_budget
        CHECK (tool_call_count <= max_tool_calls),
    KEY ix_agent_runs_competitor_started (competitor_id, started_at),
    KEY ix_agent_runs_status_started (status, started_at),
    KEY ix_agent_runs_normalized_input (normalized_input)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS sources (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    competitor_id BIGINT UNSIGNED NOT NULL,
    source_type ENUM('HOMEPAGE', 'FEATURES', 'PRICING', 'CHANGELOG', 'OTHER')
        NOT NULL,
    url TEXT NOT NULL,
    normalized_url VARCHAR(2048) NOT NULL,
    normalized_url_hash BINARY(32) NOT NULL,
    domain VARCHAR(255) NOT NULL,
    verification_status ENUM('VERIFIED', 'REJECTED', 'PENDING_CONFIRMATION')
        NOT NULL,
    verification_reason TEXT NULL,
    confidence DECIMAL(5,4) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    verified_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_sources_competitor
        FOREIGN KEY (competitor_id) REFERENCES competitors (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT ck_sources_confidence CHECK (confidence >= 0 AND confidence <= 1),
    UNIQUE KEY uq_sources_competitor_url (competitor_id, normalized_url_hash),
    KEY ix_sources_lookup
        (competitor_id, source_type, verification_status, is_active),
    KEY ix_sources_domain (domain)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS snapshots (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source_id BIGINT UNSIGNED NOT NULL,
    run_id BIGINT UNSIGNED NOT NULL,
    requested_url TEXT NOT NULL,
    final_url TEXT NULL,
    http_status SMALLINT UNSIGNED NULL,
    fetch_status ENUM('SUCCESS', 'FAILED', 'BLOCKED', 'JS_UNSUPPORTED', 'NOT_MODIFIED')
        NOT NULL,
    page_title TEXT NULL,
    raw_content LONGTEXT NULL,
    clean_content LONGTEXT NULL,
    raw_hash CHAR(64) NULL,
    clean_hash CHAR(64) NULL,
    content_type VARCHAR(255) NULL,
    fetched_at DATETIME(6) NOT NULL,
    error_code VARCHAR(100) NULL,
    error_message TEXT NULL,
    cleaner_version VARCHAR(50) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_snapshots_source
        FOREIGN KEY (source_id) REFERENCES sources (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_snapshots_run
        FOREIGN KEY (run_id) REFERENCES agent_runs (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT ck_snapshots_http_status
        CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599),
    UNIQUE KEY uq_snapshots_source_run (source_id, run_id),
    KEY ix_snapshots_source_fetch_time (source_id, fetched_at),
    KEY ix_snapshots_success_lookup (source_id, fetch_status, fetched_at),
    KEY ix_snapshots_clean_hash (clean_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS product_facts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    competitor_id BIGINT UNSIGNED NOT NULL,
    run_id BIGINT UNSIGNED NOT NULL,
    snapshot_id BIGINT UNSIGNED NOT NULL,
    fact_category ENUM(
        'POSITIONING', 'FEATURE', 'PLAN', 'PRICE', 'PRODUCT_UPDATE', 'OTHER'
    ) NOT NULL,
    fact_key VARCHAR(500) NOT NULL,
    fact_value JSON NOT NULL,
    value_text TEXT NULL,
    statement_type ENUM('FACT', 'INFERENCE', 'RECOMMENDATION') NOT NULL,
    source_url TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    confidence DECIMAL(5,4) NOT NULL,
    evidence_status ENUM('PENDING', 'CONFIRMED', 'REJECTED', 'CONFLICTING')
        NOT NULL DEFAULT 'PENDING',
    extracted_at DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_product_facts_competitor
        FOREIGN KEY (competitor_id) REFERENCES competitors (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_product_facts_run
        FOREIGN KEY (run_id) REFERENCES agent_runs (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_product_facts_snapshot
        FOREIGN KEY (snapshot_id) REFERENCES snapshots (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT ck_product_facts_confidence
        CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT ck_product_facts_source_url CHECK (CHAR_LENGTH(source_url) > 0),
    CONSTRAINT ck_product_facts_evidence CHECK (CHAR_LENGTH(evidence_text) > 0),
    UNIQUE KEY uq_product_facts_run_snapshot_key (run_id, snapshot_id, fact_key),
    KEY ix_product_facts_lookup (competitor_id, fact_category, fact_key),
    KEY ix_product_facts_run (competitor_id, run_id),
    KEY ix_product_facts_evidence_status (evidence_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS changes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    competitor_id BIGINT UNSIGNED NOT NULL,
    run_id BIGINT UNSIGNED NOT NULL,
    change_type ENUM('ADDED', 'REMOVED', 'MODIFIED', 'UNCHANGED', 'UNKNOWN')
        NOT NULL,
    fact_key VARCHAR(500) NOT NULL,
    old_fact_id BIGINT UNSIGNED NULL,
    new_fact_id BIGINT UNSIGNED NULL,
    old_value JSON NULL,
    new_value JSON NULL,
    evidence_text TEXT NULL,
    impact_assessment TEXT NULL,
    confidence DECIMAL(5,4) NULL,
    verification_status ENUM('CONFIRMED', 'PENDING', 'REJECTED')
        NOT NULL DEFAULT 'PENDING',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_changes_competitor
        FOREIGN KEY (competitor_id) REFERENCES competitors (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_changes_run
        FOREIGN KEY (run_id) REFERENCES agent_runs (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_changes_old_fact
        FOREIGN KEY (old_fact_id) REFERENCES product_facts (id)
        ON DELETE SET NULL ON UPDATE RESTRICT,
    CONSTRAINT fk_changes_new_fact
        FOREIGN KEY (new_fact_id) REFERENCES product_facts (id)
        ON DELETE SET NULL ON UPDATE RESTRICT,
    CONSTRAINT ck_changes_confidence
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    KEY ix_changes_run_type (competitor_id, run_id, change_type),
    KEY ix_changes_fact_key (fact_key),
    KEY ix_changes_old_fact (old_fact_id),
    KEY ix_changes_new_fact (new_fact_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS reports (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    competitor_id BIGINT UNSIGNED NOT NULL,
    run_id BIGINT UNSIGNED NOT NULL,
    report_type ENUM('BASELINE', 'CHANGE_TRACKING') NOT NULL,
    status ENUM('GENERATED', 'FAILED') NOT NULL,
    content_markdown LONGTEXT NULL,
    summary_json JSON NULL,
    generated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    generator_version VARCHAR(100) NOT NULL,
    error_message TEXT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_reports_competitor
        FOREIGN KEY (competitor_id) REFERENCES competitors (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_reports_run
        FOREIGN KEY (run_id) REFERENCES agent_runs (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    UNIQUE KEY uq_reports_run_type (run_id, report_type),
    KEY ix_reports_competitor_generated (competitor_id, generated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS stage_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id BIGINT UNSIGNED NOT NULL,
    stage ENUM(
        'SOURCE_DISCOVERY', 'SOURCE_VALIDATION', 'PAGE_FETCHING',
        'FACT_EXTRACTION', 'BASELINE_CREATION', 'HISTORY_COMPARISON',
        'EVIDENCE_CHECKING', 'REPORT_GENERATION', 'COMPLETED', 'FAILED'
    ) NOT NULL,
    attempt_no SMALLINT UNSIGNED NOT NULL,
    max_attempts SMALLINT UNSIGNED NOT NULL,
    status ENUM('ENTERED', 'SUCCEEDED', 'FAILED') NOT NULL DEFAULT 'ENTERED',
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    finished_at DATETIME(6) NULL,
    details_json JSON NULL,
    error_code VARCHAR(100) NULL,
    error_message TEXT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_stage_events_run
        FOREIGN KEY (run_id) REFERENCES agent_runs (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT ck_stage_events_attempt
        CHECK (attempt_no >= 1 AND attempt_no <= max_attempts),
    UNIQUE KEY uq_stage_events_attempt (run_id, stage, attempt_no),
    KEY ix_stage_events_run_started (run_id, started_at),
    KEY ix_stage_events_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS tool_calls (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id BIGINT UNSIGNED NOT NULL,
    stage_event_id BIGINT UNSIGNED NULL,
    call_index SMALLINT UNSIGNED NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    input_summary JSON NULL,
    output_summary JSON NULL,
    status ENUM('RUNNING', 'SUCCEEDED', 'FAILED') NOT NULL DEFAULT 'RUNNING',
    retryable BOOLEAN NOT NULL DEFAULT FALSE,
    duration_ms INT UNSIGNED NULL,
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    finished_at DATETIME(6) NULL,
    error_code VARCHAR(100) NULL,
    error_message TEXT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_tool_calls_run
        FOREIGN KEY (run_id) REFERENCES agent_runs (id)
        ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_tool_calls_stage_event
        FOREIGN KEY (stage_event_id) REFERENCES stage_events (id)
        ON DELETE SET NULL ON UPDATE RESTRICT,
    CONSTRAINT ck_tool_calls_call_index CHECK (call_index >= 1),
    UNIQUE KEY uq_tool_calls_run_index (run_id, call_index),
    KEY ix_tool_calls_run_tool (run_id, tool_name),
    KEY ix_tool_calls_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
