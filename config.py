"""All tunable parameters and environment-loaded secrets."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# ── Thresholds ────────────────────────────────────────────────────────────
VALIDATION_THRESHOLD = 45
SWOT_PROCEED_THRESHOLD = 75
SWOT_CAUTION_THRESHOLD = 55
SIMILARITY_THRESHOLD = 0.85

# ── Caps ──────────────────────────────────────────────────────────────────
MAX_IDEAS_PER_RUN = 20
MAX_SWOT_PER_RUN = 5
MIN_SIGNAL_CLUSTER = 5  # fewer mentions than this in a cluster => insufficient

# ── LLM backends ──────────────────────────────────────────────────────────
# Primary: Claude CLI (`claude -p`). Fallback: OpenRouter API.
CLAUDE_MAX_RETRIES = 3
CLAUDE_MAX_TOKENS = 4096

CLAUDE_CLI_BIN = os.getenv("CLAUDE_CLI_BIN", "claude")
CLAUDE_CLI_MODEL = os.getenv("CLAUDE_CLI_MODEL", "sonnet")  # CLI accepts aliases
CLAUDE_CLI_TIMEOUT = int(os.getenv("CLAUDE_CLI_TIMEOUT", "180"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5")

# ── SWOT scoring weights (must sum to 1.0) ────────────────────────────────
SWOT_WEIGHTS = {
    "strengths": 0.25,
    "weaknesses": 0.20,
    "opportunities": 0.20,
    "threats": 0.35,
}
RELIABILITY_PENALTY = 10

# ── Sources ───────────────────────────────────────────────────────────────
REDDIT_SUBREDDITS = [
    "entrepreneur", "SaaS", "startups",
    "indiehackers", "smallbusiness", "webdev",
]
REDDIT_QUERY_TERMS = [
    "is there a tool",
    "I wish there was",
    "why is there no",
    "I hate that",
    "anyone else frustrated",
]
REDDIT_POSTS_PER_QUERY = 15

# App Store: find apps per search term, pull low-star reviews (complaints).
APPSTORE_COUNTRY = "us"
APPSTORE_SEARCH_TERMS = [
    "project management", "productivity", "time tracking",
    "invoicing", "note taking", "habit tracker",
]
APPSTORE_APPS_PER_TERM = 5
APPSTORE_REVIEWS_PER_APP = 10
APPSTORE_MAX_RATING = 2  # only keep reviews at or below this star rating

# AppSumo: scrape public marketplace listings (name + pitch + tags).
APPSUMO_BROWSE_URLS = [
    "https://appsumo.com/browse/",
    "https://appsumo.com/collections/software/",
]
APPSUMO_MAX_LISTINGS = 30
# Fetch each listing's product page for review count + rating (market-size
# proxy). Costs one extra request per listing; disable to scrape listings only.
APPSUMO_FETCH_MARKET = True

# ── Demand measurement (idea-specific market sizing) ───────────────────────
# Per idea, we gauge REAL demand from app downloads + search-trend rather than a
# generic industry TAM. Sources: App Store rating counts, Play Store installs,
# Google Trends direction. These roll up into a 0-100 demand_score.
DEMAND_APPS_PER_STORE = 5          # apps to sample per store per keyword
DEMAND_COUNTRY = "us"
# demand_score = volume_score (0-VOLUME_MAX from downloads, log-scaled) +
# trend_score (0-TREND_MAX from Google Trends direction).
DEMAND_VOLUME_MAX = 60
DEMAND_TREND_MAX = 40
DEMAND_VOLUME_LOG_FACTOR = 7.5     # ~100M-audience saturates volume_score
# Demand gate: low measured demand caps the SWOT verdict regardless of the
# qualitative SWOT score (an idea nobody searches for / downloads isn't worth
# following). Only applied when demand is actually measurable.
DEMAND_KILL_BELOW = 20             # demand_score < this -> verdict forced KILL
DEMAND_CAUTION_BELOW = 40          # < this -> PROCEED downgraded to CAUTION

# ── Prior-art app search (pain-specific) ───────────────────────────────────
# Instead of one generic category keyword, the Validator distills each pain into
# several specific app-store search phrases. We search those, union + dedup the
# apps, rank by relevance x traction, and pull reviews for the top few — to find
# apps that ALREADY tried to fix this pain and judge whether it's still unsolved.
# Demand volume is then measured from these pain-specific apps (not category
# leaders), and the same apps populate the competitor cards.
DEMAND_APP_QUERIES_MAX = 5         # cap on phrases used per idea
PRIOR_ART_APPS_MAX = 8             # unique apps kept after union/dedup/rank
PRIOR_ART_REVIEW_APPS = 3          # top apps to fetch reviews for
PRIOR_ART_REVIEWS_PER_APP = 20     # reviews sampled per app
PRIOR_ART_REVIEW_SNIPPET_CHARS = 300  # truncate each review body to this

# ── Schedule ──────────────────────────────────────────────────────────────
SCHEDULE_DAY = "monday"
SCHEDULE_TIME = "08:00"

# ── Paths ─────────────────────────────────────────────────────────────────
LOCKFILE_PATH = os.getenv("LOCKFILE_PATH", str(BASE_DIR / "idea_machine.lock"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'idea_machine.db'}")

# ── API keys / secrets (from .env) ────────────────────────────────────────
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "idea-machine/0.1")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def missing_keys():
    """Return list of required secret names that are unset.

    The LLM layer uses the Claude CLI first (its own auth) and OpenRouter as a
    fallback, so no LLM key is strictly required here. If the CLI is unavailable
    at runtime and OPENROUTER_API_KEY is unset, the backend will error per-call.
    """
    required = {
        "SERPER_API_KEY": SERPER_API_KEY,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    }
    return [name for name, val in required.items() if not val]
