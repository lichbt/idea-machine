-- Product Idea Machine schema (SQLite dev / Postgres prod compatible)

-- Raw scraped signals
CREATE TABLE IF NOT EXISTS raw_signals (
  id INTEGER PRIMARY KEY,
  source TEXT,                  -- reddit / producthunt / hackernews / appstore
  url TEXT,
  content TEXT,
  content_hash TEXT UNIQUE,     -- deduplication fingerprint
  scraped_at TIMESTAMP,
  status TEXT DEFAULT 'pending' -- pending / validated / insufficient / duplicate / validation_failed
);

-- Validator output
CREATE TABLE IF NOT EXISTS validated_ideas (
  id INTEGER PRIMARY KEY,
  signal_id INTEGER REFERENCES raw_signals(id),
  pain_point_title TEXT,
  scores JSON,                  -- {pain_intensity, market_gap, buildability, monetizability}
  total_score INTEGER,
  passed BOOLEAN,
  validated_at TIMESTAMP
);

-- SWOT Pass 1 raw evidence
CREATE TABLE IF NOT EXISTS swot_research (
  id INTEGER PRIMARY KEY,
  validated_idea_id INTEGER REFERENCES validated_ideas(id),
  strengths_raw JSON,           -- URLs + snippets
  weaknesses_raw JSON,
  opportunities_raw JSON,
  threats_raw JSON,
  research_status TEXT,         -- complete / partial / failed / pending_retry
  researched_at TIMESTAMP
);

-- SWOT Pass 2 synthesis
CREATE TABLE IF NOT EXISTS swot_analysis (
  id INTEGER PRIMARY KEY,
  swot_research_id INTEGER REFERENCES swot_research(id),
  strengths JSON,               -- {prose, score, confidence, confidence_reason, evidence[]}
  weaknesses JSON,
  opportunities JSON,
  threats JSON,
  competitors JSON,             -- [{name, pricing, traction, weakness, big_player_risk}]
  verdict TEXT,                 -- PROCEED / PROCEED_WITH_CAUTION / KILL
  overall_score INTEGER,
  reliability_penalty INTEGER,  -- 0 or -10 if data was missing
  score_reliability TEXT,       -- HIGH / LOW
  verdict_reasoning TEXT,
  biggest_risk TEXT,
  biggest_opportunity TEXT,
  synthesized_at TIMESTAMP
);

-- Final product concepts
CREATE TABLE IF NOT EXISTS ideas (
  id INTEGER PRIMARY KEY,
  swot_analysis_id INTEGER REFERENCES swot_analysis(id),
  name TEXT,
  oneliner TEXT,
  core_features JSON,
  tech_stack TEXT,
  revenue_model TEXT,
  build_weeks INTEGER,
  similarity_flag BOOLEAN DEFAULT 0,  -- potential duplicate warning
  similar_idea_id INTEGER,
  created_at TIMESTAMP
);
