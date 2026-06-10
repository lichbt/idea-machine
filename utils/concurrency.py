"""Bounded concurrent map for independent (LLM) calls.

`pmap` runs a function over items through a small thread pool — several `claude -p`
subprocesses at once — and returns results in the SAME order as the inputs. A
function that raises yields None for that item (callers filter), so one bad item
never sinks the batch.

Used for the embarrassingly-parallel LLM steps (validator per-signal, category-
pain per-category, opportunity per-idea). Keep DB WRITES on the main thread:
parallelize the read+LLM, then write the results sequentially.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import config

log = logging.getLogger(__name__)


def _safe(fn, item):
    try:
        return fn(item)
    except Exception as e:  # noqa: BLE001 — isolate per-item failures
        log.warning("pmap item failed: %s", e)
        return None


def pmap(fn, items, workers=None):
    """Apply fn to each item concurrently (bounded), preserving input order.
    Falls back to a plain serial map when concurrency is disabled or unnecessary."""
    items = list(items)
    workers = config.LLM_CONCURRENCY if workers is None else workers
    if workers <= 1 or len(items) <= 1:
        return [_safe(fn, it) for it in items]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda it: _safe(fn, it), items))
