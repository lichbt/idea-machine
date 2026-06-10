"""SQLAlchemy ORM models + session helpers."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.types import JSON

import config

Base = declarative_base()


class RawSignal(Base):
    __tablename__ = "raw_signals"

    id = Column(Integer, primary_key=True)
    source = Column(String)
    url = Column(Text)
    content = Column(Text)
    content_hash = Column(String, unique=True)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="pending")


class ValidatedIdea(Base):
    __tablename__ = "validated_ideas"

    id = Column(Integer, primary_key=True)
    signal_id = Column(Integer, ForeignKey("raw_signals.id"))
    pain_point_title = Column(Text)
    search_keyword = Column(Text)  # short category term for Google Trends
    app_search_queries = Column(JSON)  # 3-5 pain-specific app-store phrases
    scores = Column(JSON)
    total_score = Column(Integer)
    passed = Column(Boolean)
    validated_at = Column(DateTime, default=datetime.utcnow)


class SwotResearch(Base):
    __tablename__ = "swot_research"

    id = Column(Integer, primary_key=True)
    validated_idea_id = Column(Integer, ForeignKey("validated_ideas.id"))
    strengths_raw = Column(JSON)
    weaknesses_raw = Column(JSON)
    opportunities_raw = Column(JSON)
    threats_raw = Column(JSON)
    market_raw = Column(JSON)  # market-size / growth search evidence
    research_status = Column(String)  # complete / partial / failed / pending_retry
    researched_at = Column(DateTime, default=datetime.utcnow)


class SwotAnalysis(Base):
    __tablename__ = "swot_analysis"

    id = Column(Integer, primary_key=True)
    swot_research_id = Column(Integer, ForeignKey("swot_research.id"))
    strengths = Column(JSON)
    weaknesses = Column(JSON)
    opportunities = Column(JSON)
    threats = Column(JSON)
    competitors = Column(JSON)
    market_analysis = Column(JSON)  # size / TAM / growth synthesis
    verdict = Column(String)
    overall_score = Column(Integer)
    demand_score = Column(Integer)  # 0-100 idea-specific demand (downloads+trend)
    demand_data = Column(JSON)      # raw demand evidence (app/play/trend)
    reliability_penalty = Column(Integer, default=0)
    score_reliability = Column(String)
    verdict_reasoning = Column(Text)
    biggest_risk = Column(Text)
    biggest_opportunity = Column(Text)
    challenge = Column(JSON)  # adversarial red-team rebuttal + any verdict downgrade
    synthesized_at = Column(DateTime, default=datetime.utcnow)


class Idea(Base):
    __tablename__ = "ideas"

    id = Column(Integer, primary_key=True)
    swot_analysis_id = Column(Integer, ForeignKey("swot_analysis.id"))
    name = Column(Text)
    oneliner = Column(Text)
    core_features = Column(JSON)
    tech_stack = Column(Text)
    revenue_model = Column(Text)
    build_weeks = Column(Integer)
    similarity_flag = Column(Boolean, default=False)
    similar_idea_id = Column(Integer)
    # Opportunity judge (auto-pilot go/no-go scorer)
    opportunity_score = Column(Integer)          # 0-100 rubric score
    opportunity_recommendation = Column(String)  # PROCEED / ITERATE / DROP
    opportunity_scores = Column(JSON)            # per-criterion subscores
    opportunity_reasoning = Column(Text)
    build_brief = Column(JSON)                   # MVP build brief (--brief)
    created_at = Column(DateTime, default=datetime.utcnow)


_engine = None
_SessionFactory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(config.DATABASE_URL, future=True)
        # WAL + a generous busy timeout let several connections (the concurrent
        # LLM workers' sessions) read/write without "database is locked" errors.
        if config.DATABASE_URL.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=30000")
                cur.close()
    return _engine


# Columns added after the initial schema; create_all won't add them to an
# existing table, so we ALTER-ADD them idempotently on init.
_ADDED_COLUMNS = {
    "validated_ideas": {"search_keyword": "TEXT", "app_search_queries": "JSON"},
    "swot_research": {"market_raw": "JSON"},
    "swot_analysis": {
        "market_analysis": "JSON",
        "demand_score": "INTEGER",
        "demand_data": "JSON",
        "challenge": "JSON",
    },
    "ideas": {
        "opportunity_score": "INTEGER",
        "opportunity_recommendation": "TEXT",
        "opportunity_scores": "JSON",
        "opportunity_reasoning": "TEXT",
        "build_brief": "JSON",
    },
}


def _migrate_add_columns(engine):
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # fresh DB: create_all already included the column
            present = {c["name"] for c in insp.get_columns(table)}
            for name, sqltype in cols.items():
                if name not in present:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}"))


def init_db():
    """Create all tables if they do not exist, then apply column migrations."""
    engine = get_engine()
    _migrate_add_columns(engine)  # before create_all: only touches existing tables
    Base.metadata.create_all(engine)


def get_session():
    """Return a new ORM session. Caller is responsible for commit/close."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), future=True)
    return _SessionFactory()
