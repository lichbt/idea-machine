"""Unit tests for content_hash and the Reddit title cleaner."""
from scrapers.reddit import _clean_title
from utils.deduplicator import content_hash


def test_content_hash_is_deterministic():
    assert content_hash("u", "c") == content_hash("u", "c")


def test_content_hash_distinguishes_content():
    assert content_hash("u", "c") != content_hash("u", "d")
    assert content_hash("u1", "c") != content_hash("u2", "c")


def test_content_hash_handles_none():
    # must not raise on missing url/content
    assert isinstance(content_hash(None, None), str)


def test_content_hash_uses_only_content_prefix():
    # only the first 200 chars of content matter -> same prefix == same hash
    base = "x" * 200
    assert content_hash("u", base + "AAA") == content_hash("u", base + "BBB")


def test_clean_title_strips_leading_subreddit():
    assert _clean_title("r/SaaS on Reddit: Anyone frustrated") == "Anyone frustrated"


def test_clean_title_strips_trailing_decorations():
    assert _clean_title("I wish there was a tool — r/Entrepreneur - Reddit") \
        == "I wish there was a tool"
    assert _clean_title("Is there a tool that helps - Reddit") \
        == "Is there a tool that helps"


def test_clean_title_leaves_plain_title():
    assert _clean_title("How I validate ideas before building") \
        == "How I validate ideas before building"
