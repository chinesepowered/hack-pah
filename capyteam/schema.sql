-- CapyTeam schema for SingleStore (columnstore tables, Helios 10.x).
-- Every agent session, every event, every money claim and every lesson lives here.

CREATE TABLE IF NOT EXISTS sessions (
  session_id     VARCHAR(80) NOT NULL,
  capy_name      VARCHAR(64),
  agent_version  VARCHAR(16),
  variant        VARCHAR(32),
  mode           VARCHAR(16),          -- practice | drill | race | live
  source         VARCHAR(32),          -- sandbox | firedrill | airbyte
  campaign_id    VARCHAR(80),
  scenario       VARCHAR(128),
  task           VARCHAR(32),
  status         VARCHAR(16),          -- running | done | failed | blocked
  started_at     DATETIME(6),
  updated_at     DATETIME(6),
  ended_at       DATETIME(6),
  turns          INT DEFAULT 0,
  tool_calls     INT DEFAULT 0,
  tokens         INT DEFAULT 0,
  cost_usd       DOUBLE DEFAULT 0,
  latency_ms     BIGINT DEFAULT 0,
  outcome        JSON,
  verdict        JSON,
  lessons_used   JSON,
  SORT KEY (started_at),
  SHARD KEY (session_id),
  PRIMARY KEY (session_id)
);

CREATE TABLE IF NOT EXISTS events (
  session_id     VARCHAR(80) NOT NULL,
  seq            INT NOT NULL,
  ts             DATETIME(6) NOT NULL,
  kind           VARCHAR(32),          -- user | assistant | tool_call | tool_result | claim | guard | lesson | error | end
  building       VARCHAR(32),          -- stripe | quickbooks | gmail | archive | harbor | school | home
  capy_name      VARCHAR(64),
  agent_version  VARCHAR(16),
  mode           VARCHAR(16),
  summary        VARCHAR(512),
  payload        JSON,
  SORT KEY (ts),
  SHARD KEY (session_id)
);

CREATE TABLE IF NOT EXISTS money_claims (
  claim_key      VARCHAR(191) NOT NULL, -- e.g. refund:ch_123  (one business action, ever)
  session_id     VARCHAR(80) NOT NULL,
  capy_name      VARCHAR(64),
  agent_version  VARCHAR(16),
  action         VARCHAR(32),
  target         VARCHAR(128),
  amount_cents   BIGINT,
  status         VARCHAR(16),          -- claimed | done | failed
  created_at     DATETIME(6),
  updated_at     DATETIME(6),
  result         JSON,
  SHARD KEY (claim_key),
  PRIMARY KEY (claim_key)
);

CREATE TABLE IF NOT EXISTS lessons (
  lesson_id      VARCHAR(64) NOT NULL,
  title          VARCHAR(255),
  rule           TEXT,
  kind           VARCHAR(16),          -- prompt | guard
  guard          JSON,                 -- structured policy the harness enforces
  source_session VARCHAR(80),
  failure        VARCHAR(64),
  introduced_in  VARCHAR(16),
  active         TINYINT DEFAULT 1,
  created_at     DATETIME(6),
  times_applied  INT DEFAULT 0,
  embedding      VECTOR(2560, F32),
  FULLTEXT USING VERSION 2 lessons_ft (title, rule),
  SHARD KEY (lesson_id),
  PRIMARY KEY (lesson_id)
);

CREATE TABLE IF NOT EXISTS drills (
  drill_id       VARCHAR(80) NOT NULL,
  campaign_id    VARCHAR(80),
  session_id     VARCHAR(80),
  scenario       VARCHAR(128),
  agent_version  VARCHAR(16),
  variant        VARCHAR(32),
  source         VARCHAR(16),          -- practice | firedrill
  ending         VARCHAR(32),
  passed         TINYINT,
  score          DOUBLE,
  results        JSON,
  created_at     DATETIME(6),
  SHARD KEY (drill_id),
  PRIMARY KEY (drill_id)
);

CREATE TABLE IF NOT EXISTS versions (
  version        VARCHAR(16) NOT NULL,
  parent         VARCHAR(16),
  status         VARCHAR(16),          -- shipped | experiment | draft
  created_at     DATETIME(6),
  notes          TEXT,
  lesson_ids     JSON,
  guards         JSON,
  SHARD KEY (version),
  PRIMARY KEY (version)
);

CREATE TABLE IF NOT EXISTS scenarios (
  scenario_id    VARCHAR(80) NOT NULL,
  name           VARCHAR(255),
  source_session VARCHAR(80),
  lesson_id      VARCHAR(64),
  kind           VARCHAR(16),          -- firedrill | practice
  spec           JSON,
  created_at     DATETIME(6),
  SHARD KEY (scenario_id),
  PRIMARY KEY (scenario_id)
);
