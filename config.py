"""All tunable parameters and environment-loaded secrets."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# ── Thresholds ────────────────────────────────────────────────────────────
VALIDATION_THRESHOLD = 45
# Lowered 75 -> 70 (2026-06-09): the funnel showed 0 PROCEED verdicts ever — the
# conservative SWOT scoring caps strong ideas at CAUTION. 70 lets genuinely good
# ones reach a PROCEED verdict.
SWOT_PROCEED_THRESHOLD = 70
SWOT_CAUTION_THRESHOLD = 55
SIMILARITY_THRESHOLD = 0.85

# ── Idea generation (concept diversity) ───────────────────────────────────
# Concept dedup needs a LOWER bar than raw-signal clustering: two short
# "name: oneliner" strings for the same product score only ~0.6-0.8 cosine
# (e.g. two freelancer-invoicing apps measured 0.68/0.80), well under 0.85 — so
# the synthesizer's duplicate check used SIMILARITY_THRESHOLD and never fired.
# This separate, lower threshold catches conceptual clones; the synthesizer also
# shows the LLM the nearest existing concepts and regenerates once if it still
# returns a near-duplicate.
CONCEPT_SIMILARITY_THRESHOLD = float(os.getenv("CONCEPT_SIMILARITY_THRESHOLD", "0.6"))
CONCEPT_NEIGHBORS = int(os.getenv("CONCEPT_NEIGHBORS", "5"))  # existing concepts shown to the LLM
CONCEPT_REGEN_MAX = int(os.getenv("CONCEPT_REGEN_MAX", "1"))  # regen attempts on a duplicate

# ── Auto-pilot (autonomous hunt) ──────────────────────────────────────────
# `run.py --autopilot` loops discovery -> SWOT -> opportunity scoring in rounds.
# The Opportunity Judge (agents/opportunity.py) scores each finished idea 0-100 on
# a fixed rubric and recommends PROCEED / ITERATE / DROP. The loop STOPS when an
# idea clears the bar (score >= AUTOPILOT_PROCEED_SCORE AND recommendation
# PROCEED), else runs up to AUTOPILOT_MAX_ROUNDS and reports the best found. Each
# round uses fresh feedback seeds, so it explores new categories every loop.
AUTOPILOT_MAX_ROUNDS = int(os.getenv("AUTOPILOT_MAX_ROUNDS", "5"))
# Lowered 75 -> 70 (2026-06-09) to match SWOT_PROCEED_THRESHOLD — at 75 the
# conservative judge never reached PROCEED, so the hunt could never "win". The
# judge's PROCEED rule (agents/opportunity.py) references this value, so they stay
# in sync.
AUTOPILOT_PROCEED_SCORE = int(os.getenv("AUTOPILOT_PROCEED_SCORE", "70"))

# ── Caps ──────────────────────────────────────────────────────────────────
MAX_IDEAS_PER_RUN = 20
MAX_SWOT_PER_RUN = 5
MIN_SIGNAL_CLUSTER = 3  # fewer mentions than this in a cluster => insufficient
# Novelty rescue: a cluster smaller than MIN_SIGNAL_CLUSTER is normally dropped
# (popularity filter). But an underserved pain is mentioned rarely, so rescue a
# sub-threshold cluster when its language shows strong pain (utils.pain.pain_score
# >= this). Set very high to disable. Keeps novel high-pain signals alive.
# NOTE: at 3 this rescued ~all singletons (271 rescues / 0 drops in one run),
# effectively disabling the popularity filter. 7 keeps only genuinely high-pain
# singletons so the rescue stays the rare exception it's meant to be.
PAIN_KEEP_THRESHOLD = int(os.getenv("PAIN_KEEP_THRESHOLD", "7"))

# ── Discovery ranking (willingness-to-pay + recency) ──────────────────────
# Beyond raw pain frequency, two signals predict a BETTER idea: explicit
# willingness to pay (someone already pays / would pay for a fix => monetizable)
# and recency (a fresh complaint reflects a live, still-unmet need). These fold
# into a single discovery_score the Scout uses to rank signals WITHIN each source
# so the per-run cap keeps the strongest, not an arbitrary slice. Signals whose
# source carries no authored date simply get no recency bonus (degrade, never
# penalise).
WTP_WEIGHT = float(os.getenv("WTP_WEIGHT", "2.0"))        # multiplier on wtp markers
RECENCY_MAX = float(os.getenv("RECENCY_MAX", "5.0"))      # max bonus for a brand-new signal
RECENCY_HALFLIFE_DAYS = float(os.getenv("RECENCY_HALFLIFE_DAYS", "90"))

# ── Gap-targeting (app discovery) ─────────────────────────────────────────
# An app with a LARGE audience but a LOW rating = a validated market with a
# failing incumbent = a real gap (high market_gap + monetizability). The store
# scrapers rank apps by this so they prioritise underserved markets over
# well-loved leaders, and tag such apps "UNDERSERVED" so the scorer sees it.
GAP_MIN_AUDIENCE = int(os.getenv("GAP_MIN_AUDIENCE", "500"))  # min ratings/installs to count
GAP_RATING_CEILING = float(os.getenv("GAP_RATING_CEILING", "3.7"))  # avg <= this => underserved

# ── Feedback-driven seeds (adaptive discovery) ────────────────────────────
# Instead of always searching the same static APPSTORE/PLAYSTORE_SEARCH_TERMS,
# the Scout can generate FRESH app-store category seeds each run from verdict
# history: it learns which categories PROCEEDed (lean toward their neighbours)
# vs KILLed (avoid saturated spaces), and explicitly avoids categories already
# tried — which also breaks the dedup deadlock (new seeds => new apps =>
# new signals). Falls back to the static lists if the LLM/history is unavailable.
FEEDBACK_SEEDS = os.getenv("FEEDBACK_SEEDS", "true").lower() in ("1", "true", "yes")
FEEDBACK_SEED_COUNT = int(os.getenv("FEEDBACK_SEED_COUNT", "8"))
FEEDBACK_HISTORY_MAX = int(os.getenv("FEEDBACK_HISTORY_MAX", "40"))  # recent categories shown to the LLM

# ── Cluster labeling (crisp pain statements) ──────────────────────────────
# Raw signals are messy (a profane review, a rambling forum post). Before
# writing the FINAL selected signals, one batched LLM call distills each into a
# crisp one-line PAIN STATEMENT prepended above the raw evidence — so the
# Validator scores the underlying problem, not the noise. Bounded to the post-cap
# selection (<= MAX_IDEAS_PER_RUN) and degrades gracefully (keeps raw text on any
# failure). One extra LLM call per run.
CLUSTER_LABELING = os.getenv("CLUSTER_LABELING", "true").lower() in ("1", "true", "yes")

# ── Cross-run pain memory ─────────────────────────────────────────────────
# Organic sources resurface the same pains across runs, so the machine keeps
# re-evaluating ideas it already scored. Before writing new signals, the Scout
# embeds each against the pains it has ALREADY evaluated (all ValidatedIdea pain
# titles) and drops ones that are too similar — so every run explores new ground
# (and saves the validator/SWOT cost of re-scoring a known pain). No new storage:
# the memory IS the validated-idea history.
PAIN_MEMORY = os.getenv("PAIN_MEMORY", "true").lower() in ("1", "true", "yes")
PAIN_MEMORY_THRESHOLD = float(os.getenv("PAIN_MEMORY_THRESHOLD", "0.72"))  # cosine; higher = stricter (fewer dropped)

# ── LLM backends ──────────────────────────────────────────────────────────
# Primary: Claude CLI (`claude -p`). Fallback: OpenRouter API.
CLAUDE_MAX_RETRIES = 3
CLAUDE_MAX_TOKENS = 4096
# Independent LLM calls (validator per-signal, category-pain per-category,
# opportunity per-idea) run through a bounded thread pool — several `claude -p`
# processes at once. Faster, and the controlled concurrency avoids the flaky
# "exited 1" seen under rapid SEQUENTIAL calls. Set to 1 to disable.
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "4"))

CLAUDE_CLI_BIN = os.getenv("CLAUDE_CLI_BIN", "claude")
CLAUDE_CLI_MODEL = os.getenv("CLAUDE_CLI_MODEL", "sonnet")  # CLI accepts aliases
CLAUDE_CLI_TIMEOUT = int(os.getenv("CLAUDE_CLI_TIMEOUT", "180"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5")

# LLM backend selection. DEFAULT IS "cli": this project uses the Claude CLI
# (`claude -p`) for ALL LLM work and makes NO LLM API/HTTP calls. The OpenAI-
# compatible / OpenRouter HTTP paths below remain as opt-in fallbacks but are
# never used unless LLM_BACKEND is explicitly set to "openai" or "auto".
#   cli    -> only the Claude CLI (default; no API calls).
#   openai -> only the OpenAI-compatible HTTP endpoint.
#   auto   -> OpenAI-compatible endpoint if configured, else the Claude CLI.
# NOTE: data-source APIs (Serper search, App/Play stores, GitHub) are separate
# from the LLM backend and are still used — "no API" here means the LLM layer.
LLM_BACKEND = os.getenv("LLM_BACKEND", "cli").lower()
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")  # e.g. http://localhost:20128/v1
LLM_MODEL = os.getenv("LLM_MODEL", "")
# Read timeout (seconds) for the OpenAI-compatible HTTP gateway. With streaming
# this is the max gap allowed *between* SSE chunks, not the total generation
# time — so large syntheses on a slow router model won't trip it. Kept separate
# from CLAUDE_CLI_TIMEOUT (a different backend).
LLM_HTTP_TIMEOUT = int(os.getenv("LLM_HTTP_TIMEOUT", "300"))

# ── SWOT scoring weights (must sum to 1.0) ────────────────────────────────
SWOT_WEIGHTS = {
    "strengths": 0.25,
    "weaknesses": 0.20,
    "opportunities": 0.20,
    "threats": 0.35,
}
RELIABILITY_PENALTY = 10

# ── SWOT quality ──────────────────────────────────────────────────────────
# Confidence-weighted scoring: the synthesizer emits a confidence per quadrant;
# we shrink each quadrant's score toward the neutral 50 by these factors, so a
# low-evidence quadrant can't dominate the weighted score (esp. threats @ 0.35).
SWOT_CONFIDENCE_SHRINK = {"high": 1.0, "medium": 0.7, "low": 0.4}
# Adversarial second opinion: after synthesis a red-team LLM call argues the
# strongest case to KILL and can DOWNGRADE (never upgrade) an over-optimistic
# verdict. The single biggest decision-quality lever.
SWOT_ADVERSARIAL = os.getenv("SWOT_ADVERSARIAL", "true").lower() in ("1", "true", "yes")
# LLM-tailored research queries: Pass 1 asks the LLM for sharp, idea-specific
# Google queries per quadrant instead of templated `pain + suffix` strings.
SWOT_PLAN_QUERIES = os.getenv("SWOT_PLAN_QUERIES", "true").lower() in ("1", "true", "yes")

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
# Reddit closed self-service API app creation (prefs/apps fails) AND now 403s the
# no-auth .json endpoints; the .rss fallback still works but is thin (capped,
# HTML-truncated, no real subreddit crawl). So when a SERPER key is present we
# search Reddit via Google instead (site:reddit.com/r/<sub>) — far better
# targeted, full titles + pain-dense snippets, one Serper call per subreddit.
# Method priority in scrapers/reddit.py: PRAW (if creds) -> Serper -> RSS.
REDDIT_USE_SERPER = os.getenv("REDDIT_USE_SERPER", "true").lower() in ("1", "true", "yes")
# Results to fetch per subreddit via the web-search backend (utils.search).
# Serper paginates internally to reach this (free tier caps num=10/page); Brave
# caps at 20/request. ~6 subreddits => that many search calls per Scout run.
REDDIT_SEARCH_RESULTS = int(os.getenv("REDDIT_SEARCH_RESULTS", "20"))

# GitHub Issues: surface DEVELOPER-TOOL pain (acute pains, buyers with budget).
# CATEGORY-driven like the app stores: search each devtool domain, sort by
# REACTIONS (how many people want it = validation, akin to app ratings), tag each
# issue's repo, and let category-pain synthesis find requests that recur across
# DIFFERENT repos = a cross-repo devtool gap. Works unauthenticated at ~10 req/min;
# set GITHUB_TOKEN for 30.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_CATEGORY_TERMS = [
    "ci cd pipeline", "authentication oauth", "database orm", "api gateway",
    "logging observability", "feature flags", "background job queue",
    "error monitoring", "secrets management", "infrastructure as code",
]
GITHUB_ISSUES_PER_CATEGORY = 30      # fetched per category (sorted by reactions)
GITHUB_MAX_ISSUES_PER_REPO = 3       # cap per repo so one mega-repo can't dominate

# Ecosystem-wave scout ("picks & shovels"): demand-FIRST discovery. Finds
# fast-growing platforms (protocols/SDKs/frameworks) on GitHub by star VELOCITY,
# probes which standard tooling categories are still unserved around each, and
# synthesizes those gaps into pain-style signals. The machine's only winner
# (MCPScope) was this archetype, found by accident — this systematizes it.
ECOSYSTEM_MAX_AGE_DAYS = 540         # only "young" repos (~18 mo) count as waves
ECOSYSTEM_MIN_STARS = 800            # floor before velocity ranking applies
ECOSYSTEM_CANDIDATES = 30            # velocity-ranked repos fed to the LLM filter
ECOSYSTEM_TOP_WAVES = 3              # waves whose tooling gaps get probed
ECOSYSTEM_GAP_TERMS = [              # what every young ecosystem eventually needs
    "debugger inspector", "testing framework", "monitoring observability",
    "registry directory", "analytics", "deployment hosting",
    "security scanner", "migration tool",
]
ECOSYSTEM_GAP_SATURATED_STARS = 300  # a gap tool above this = gap already served
ECOSYSTEM_SIGNALS_PER_WAVE = 2       # max pain signals emitted per wave
# Commercial-saturation web probe: GitHub repo counts miss funded SaaS incumbents
# (LangSmith/Datadog don't show up as "<ecosystem> monitoring" repos — learned the
# hard way: first ecosystem batch was 5/5 SWOT-KILLed on commercial competition).
# For each GitHub-unserved gap, a web search feeds the commercial landscape to the
# synthesis LLM, which skips gaps already owned by established products. Costs up
# to ECOSYSTEM_TOP_WAVES x len(ECOSYSTEM_GAP_TERMS) Serper/Brave queries per run.
ECOSYSTEM_WEB_PROBE = os.getenv("ECOSYSTEM_WEB_PROBE", "true").lower() == "true"
ECOSYSTEM_WEB_RESULTS = 5            # search results per gap fed to the LLM

# Trustpilot: best-effort B2B/SaaS review scraping for category complaints.
# Anti-bot protected — frequently returns nothing; degrades gracefully (logs and
# skips, never raises). Treated as a bonus source, not a dependency.
TRUSTPILOT_CATEGORIES = [
    "saas", "software", "accounting_software", "project_management_software",
]
TRUSTPILOT_PAGES_PER_CATEGORY = 1
TRUSTPILOT_MAX_RATING = 3  # keep reviews at or below this star rating (complaints)

# App Store: find apps per search term, pull low-star reviews (complaints).
APPSTORE_COUNTRY = "us"
APPSTORE_SEARCH_TERMS = [
    "workout planner", "calorie counter", "sleep tracker", "meditation",
    "social media scheduler", "budgeting", "expense tracker",
    "subscription manager", "habit tracker", "plant care", "pet care",
]
APPSTORE_APPS_PER_TERM = 8  # broader category sample (was 5) for category-pain synthesis
APPSTORE_REVIEWS_PER_APP = 10
APPSTORE_MAX_RATING = 2  # only keep reviews at or below this star rating

# Google Play: Android mirror of the App Store source — find apps per search
# term, pull low-star reviews (complaints). Uses google-play-scraper, no key.
PLAYSTORE_COUNTRY = "us"
PLAYSTORE_SEARCH_TERMS = [
    "workout planner", "calorie counter", "sleep tracker", "meditation",
    "social media scheduler", "budgeting", "expense tracker",
    "subscription manager", "habit tracker", "plant care", "pet care",
]
PLAYSTORE_APPS_PER_TERM = 8  # broader category sample (was 5) for category-pain synthesis
PLAYSTORE_REVIEWS_PER_APP = 10
PLAYSTORE_MAX_RATING = 2  # only keep reviews at or below this star rating

# ── Category pain synthesis (app/play) ────────────────────────────────────
# A complaint that recurs across MULTIPLE apps in a category = a category GAP
# (real unmet need), not one app's bug. The Scout groups app/play low-star
# reviews by category and runs ONE LLM call per category to extract the 2-3
# cross-app recurring pains, REPLACING the raw per-app review signals with those
# stronger category-pain signals. Degrades gracefully per category (raw reviews
# pass through if a category has too few cross-app reviews or the LLM fails).
CATEGORY_PAIN_SYNTHESIS = os.getenv("CATEGORY_PAIN_SYNTHESIS", "true").lower() in ("1", "true", "yes")
CATEGORY_PAIN_MIN_REVIEWS = int(os.getenv("CATEGORY_PAIN_MIN_REVIEWS", "6"))  # min reviews in a category to synthesize
CATEGORY_PAIN_MIN_APPS = int(os.getenv("CATEGORY_PAIN_MIN_APPS", "2"))  # min distinct apps (cross-app requirement)
CATEGORY_PAIN_MAX_REVIEWS = int(os.getenv("CATEGORY_PAIN_MAX_REVIEWS", "30"))  # reviews sent to the LLM per category

# Product Hunt: recent launches + their comments (needs PRODUCTHUNT_API_TOKEN).
PRODUCTHUNT_POSTS = 20
PRODUCTHUNT_COMMENTS_PER_POST = 10

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

# ── Web search backend (Serper / Brave) ───────────────────────────────────
# All web search (SWOT research + Reddit discovery) goes through utils.search.
# SEARCH_BACKEND: 'auto' (Serper if its key is set, else Brave), 'serper', 'brave'.
# Brave's free tier (2,000 queries/month) is the no-Serper option — get a free key
# at https://brave.com/search/api/ and set BRAVE_API_KEY in .env.
SEARCH_BACKEND = os.getenv("SEARCH_BACKEND", "auto").lower()

# ── API keys / secrets (from .env) ────────────────────────────────────────
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "idea-machine/0.1")
# Optional: a "script" Reddit app authenticates via the password grant. Set
# these to your Reddit account's username/password to use a script app; leave
# unset to use application-only (read-only) OAuth.
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME", "")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD", "")
PRODUCTHUNT_API_TOKEN = os.getenv("PRODUCTHUNT_API_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def missing_keys():
    """Return list of required secret names that are unset.

    The LLM layer uses the Claude CLI first (its own auth) and OpenRouter as a
    fallback, so no LLM key is strictly required here. If the CLI is unavailable
    at runtime and OPENROUTER_API_KEY is unset, the backend will error per-call.
    """
    required = {
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    }
    missing = [name for name, val in required.items() if not val]
    # A web-search key is required, but either provider satisfies it.
    if not (SERPER_API_KEY or BRAVE_API_KEY):
        missing.append("SERPER_API_KEY or BRAVE_API_KEY")
    return missing
