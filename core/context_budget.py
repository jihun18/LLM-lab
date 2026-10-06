"""Experimental source-level reduction: never slice a paragraph or table."""
from .evidence_scope import unsupported_query_anchors


def select_context(question, results, mode="full"):
    if mode not in {"full", "primary"}:
        raise ValueError("context mode must be full or primary")
    if mode == "full" or len(results) <= 1:
        return results
    primary = results[:1]
    # Do not silently discard explicit years/model tags supplied by secondary sources.
    return results if unsupported_query_anchors(question, primary) else primary
