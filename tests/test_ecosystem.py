"""Ecosystem-wave scraper — pure-logic + fully-mocked tests (no network/LLM)."""
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

import config
from scrapers import ecosystem


def _iso(days_ago):
    return (datetime.now(timezone.utc)
            - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


# --- _age_days -----------------------------------------------------------

def test_age_days_parses_iso():
    assert ecosystem._age_days(_iso(10)) in (9, 10, 11)


def test_age_days_garbage_returns_none():
    assert ecosystem._age_days("not-a-date") is None
    assert ecosystem._age_days(None) is None


def test_age_days_floors_at_one():
    assert ecosystem._age_days(_iso(0)) == 1


# --- classify_gap --------------------------------------------------------

def test_gap_sparse_results_is_unserved():
    assert ecosystem.classify_gap(total_count=2, top_stars=10_000) is True


def test_gap_many_but_weak_results_is_unserved():
    assert ecosystem.classify_gap(total_count=40, top_stars=50) is True


def test_gap_strong_incumbent_is_served():
    assert ecosystem.classify_gap(
        total_count=40, top_stars=config.ECOSYSTEM_GAP_SATURATED_STARS) is False


# --- _short_name ---------------------------------------------------------

def test_short_name_uses_repo_half():
    assert ecosystem._short_name("vercel/ai") == "ai"


def test_short_name_falls_back_to_owner_for_generic_repos():
    assert ecosystem._short_name(
        "modelcontextprotocol/python-sdk") == "modelcontextprotocol"


# --- _detect_waves -------------------------------------------------------

def test_detect_waves_ranks_by_velocity(monkeypatch):
    payload = {"items": [
        {"full_name": "a/slow", "html_url": "u1", "description": "d",
         "topics": [], "language": "Go",
         "stargazers_count": 9000, "created_at": _iso(450)},   # 20/day
        {"full_name": "b/fast", "html_url": "u2", "description": "d",
         "topics": [], "language": "Py",
         "stargazers_count": 6000, "created_at": _iso(60)},    # 100/day
    ]}
    monkeypatch.setattr(ecosystem.requests, "get",
                        lambda *a, **k: FakeResp(payload))
    waves = ecosystem._detect_waves()
    assert [w["full_name"] for w in waves] == ["b/fast", "a/slow"]
    assert waves[0]["velocity"] == pytest.approx(100, rel=0.1)


def test_detect_waves_network_failure_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise ecosystem.requests.RequestException("down")
    monkeypatch.setattr(ecosystem.requests, "get", boom)
    assert ecosystem._detect_waves() == []


# --- _select_platforms ---------------------------------------------------

def _candidates():
    return [
        {"full_name": "a/proto", "description": "A protocol for agents",
         "topics": ["protocol"], "stars": 5000, "age_days": 100,
         "velocity": 50.0},
        {"full_name": "b/todo-app", "description": "Beautiful todo app",
         "topics": ["productivity"], "stars": 4000, "age_days": 100,
         "velocity": 40.0},
    ]


def test_select_platforms_uses_llm_picks(monkeypatch):
    monkeypatch.setattr(ecosystem, "call_json",
                        lambda *a, **k: {"waves": ["b/todo-app", "a/proto"]})
    picked = ecosystem._select_platforms(_candidates(), top=1)
    assert [w["full_name"] for w in picked] == ["b/todo-app"]


def test_select_platforms_heuristic_on_llm_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no llm")
    monkeypatch.setattr(ecosystem, "call_json", boom)
    picked = ecosystem._select_platforms(_candidates(), top=2)
    assert [w["full_name"] for w in picked] == ["a/proto"]  # platform-worded only


# --- _probe_web ------------------------------------------------------------

def test_probe_web_shapes_and_truncates(monkeypatch):
    monkeypatch.setattr(ecosystem, "web_search", lambda q, num: [
        {"title": "T" * 300, "link": "u", "snippet": "S" * 300}])
    hits = ecosystem._probe_web("proto", "monitoring")
    assert len(hits) == 1
    assert len(hits[0]["title"]) == 120 and len(hits[0]["snippet"]) == 200


def test_probe_web_failure_returns_none(monkeypatch):
    def boom(q, num):
        raise RuntimeError("quota")
    monkeypatch.setattr(ecosystem, "web_search", boom)
    assert ecosystem._probe_web("proto", "monitoring") is None


def test_probe_gaps_adds_web_only_for_unserved(monkeypatch):
    served = {"total_count": 100,
              "items": [{"full_name": "big/tool", "stargazers_count": 9000}]}
    unserved = {"total_count": 1,
                "items": [{"full_name": "x/y", "stargazers_count": 5}]}
    seq = iter([FakeResp(unserved), FakeResp(served)])
    monkeypatch.setattr(ecosystem.requests, "get", lambda *a, **k: next(seq))
    monkeypatch.setattr(ecosystem, "_throttle", lambda: None)
    monkeypatch.setattr(ecosystem, "web_search", lambda q, num: [
        {"title": "LangSmith", "link": "u", "snippet": "funded SaaS"}])
    wave = {"full_name": "a/proto"}
    probes = ecosystem._probe_gaps(wave, gap_terms=["monitoring", "testing"])
    assert "web" in probes["monitoring"]          # unserved -> web probed
    assert "web" not in probes["testing"]         # served -> no web spend


# --- _synthesize_signals -------------------------------------------------

def _wave_with_gaps():
    return {"full_name": "a/proto", "url": "https://github.com/a/proto",
            "description": "A protocol", "stars": 5000, "age_days": 100,
            "velocity": 50.0,
            "gaps": {"debugger inspector":
                     {"count": 1, "top_stars": 0, "top_repo": None,
                      "unserved": True}}}


def test_synthesize_signals_shapes_output(monkeypatch):
    monkeypatch.setattr(ecosystem, "call_json", lambda *a, **k: {
        "signals": [
            {"ecosystem": "a/proto", "gap": "debugger inspector",
             "pain": "Devs cannot see what their proto agent sends."},
            {"ecosystem": "ghost/unknown", "gap": "x", "pain": "skipped"},
            "garbage",
        ]})
    sigs = ecosystem._synthesize_signals([_wave_with_gaps()])
    assert len(sigs) == 1
    s = sigs[0]
    assert s["source"] == "ecosystem"
    assert s["synthesized"] is True
    assert s["app"] == "a/proto"
    assert s["content"].startswith("[a/proto ecosystem — debugger inspector]")
    assert ecosystem._age_days(s["created_at"]) == 1  # stamped "now"


def test_synthesize_prompt_includes_web_evidence(monkeypatch):
    captured = {}

    def fake_call(prompt, system=None, **kw):
        captured["prompt"] = prompt
        return {"signals": []}
    monkeypatch.setattr(ecosystem, "call_json", fake_call)
    wave = _wave_with_gaps()
    wave["gaps"]["debugger inspector"]["web"] = [
        {"title": "AcmeTrace — agent debugging SaaS", "snippet": "Series A"}]
    ecosystem._synthesize_signals([wave])
    assert "AcmeTrace" in captured["prompt"]
    assert "SKIP any gap" in captured["prompt"]


def test_synthesize_skips_llm_when_no_unserved_gaps(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LLM must not be called")
    monkeypatch.setattr(ecosystem, "call_json", boom)
    wave = _wave_with_gaps()
    wave["gaps"]["debugger inspector"]["unserved"] = False
    assert ecosystem._synthesize_signals([wave]) == []


# --- scrape() end-to-end, fully offline ----------------------------------

def test_scrape_end_to_end_offline(monkeypatch):
    detect_payload = {"items": [
        {"full_name": "acme/superproto",
         "html_url": "https://github.com/acme/superproto",
         "description": "A protocol for agent tools", "topics": ["protocol"],
         "language": "Python", "stargazers_count": 5000,
         "created_at": _iso(100)},
    ]}
    probe_payload = {"total_count": 1,
                     "items": [{"full_name": "x/y", "stargazers_count": 12}]}
    n = {"calls": 0}

    def fake_get(*a, **k):
        n["calls"] += 1
        return FakeResp(detect_payload if n["calls"] == 1 else probe_payload)

    monkeypatch.setattr(ecosystem.requests, "get", fake_get)
    monkeypatch.setattr(ecosystem, "_throttle", lambda: None)
    responses = iter([
        {"waves": ["acme/superproto"]},
        {"signals": [{"ecosystem": "acme/superproto",
                      "gap": "debugger inspector",
                      "pain": "No way to see what tools the agent calls."}]},
    ])
    monkeypatch.setattr(ecosystem, "call_json", lambda *a, **k: next(responses))

    sigs = ecosystem.scrape()
    assert len(sigs) == 1
    assert sigs[0]["source"] == "ecosystem"
    assert sigs[0]["url"] == "https://github.com/acme/superproto"
    # 1 detect + one probe per gap term
    assert n["calls"] == 1 + len(config.ECOSYSTEM_GAP_TERMS)


def test_scrape_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("total chaos")
    monkeypatch.setattr(ecosystem, "_detect_waves", boom)
    assert ecosystem.scrape() == []


# --- scout cluster gate keeps synthesized singletons ----------------------

def test_cluster_keeps_synthesized_singleton_drops_low_pain(monkeypatch):
    import agents.scout as scout

    fake_st = types.ModuleType("sentence_transformers")
    fake_st.util = types.SimpleNamespace(
        cos_sim=lambda a, b: [[1.0, 0.0], [0.0, 1.0]])
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)
    monkeypatch.setattr("utils.deduplicator._get_model",
                        lambda: types.SimpleNamespace(
                            encode=lambda texts, convert_to_tensor=True: texts))
    monkeypatch.setattr(scout, "most_similar", lambda t, c: (0, 1.0))
    monkeypatch.setattr(scout, "pain_score", lambda t: 0)  # rescue won't fire

    sigs = [
        {"source": "ecosystem", "content": "an ecosystem tooling gap",
         "synthesized": True},
        {"source": "reddit", "content": "a totally unrelated complaint"},
    ]
    reps = scout._cluster(sigs, min_size=3)
    assert sigs[0] in reps       # synthesized bypasses the size gate
    assert sigs[1] not in reps   # ordinary singleton with pain 0 is dropped
