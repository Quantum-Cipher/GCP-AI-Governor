CREATE SCHEMA IF NOT EXISTS `numeric-axe-zll0l.governor_audit`
OPTIONS (
  location = 'US'
);

CREATE TABLE IF NOT EXISTS `numeric-axe-zll0l.governor_audit.transcripts`
(
  insert_timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  project_id       STRING,
  event_type       STRING,
  live_mode        BOOL,
  final_decision   STRING,
  raw_transcript   JSON
)
PARTITION BY DATE(insert_timestamp)
OPTIONS (
  description = 'AI Governor transcripts and decisions'
);
