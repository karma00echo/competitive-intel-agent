-- Additive report types. Production deployment requires separate approval.
ALTER TABLE reports MODIFY COLUMN report_type
  ENUM('BASELINE', 'CHANGE_TRACKING', 'PARTIAL_EVIDENCE',
       'COMPETITIVE_ANALYSIS', 'COMPETITIVE_ANALYSIS_PARTIAL') NOT NULL;
