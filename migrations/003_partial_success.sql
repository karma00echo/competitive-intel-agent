-- Additive, restart-safe MySQL ENUM extension; no historical rows rewritten.
ALTER TABLE agent_runs MODIFY COLUMN status
    ENUM('RUNNING', 'COMPLETED', 'FAILED', 'PARTIAL_SUCCESS') NOT NULL DEFAULT 'RUNNING';
ALTER TABLE reports MODIFY COLUMN report_type
    ENUM('BASELINE', 'CHANGE_TRACKING', 'PARTIAL_EVIDENCE') NOT NULL;
