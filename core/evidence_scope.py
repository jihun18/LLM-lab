"""Conservative exact-anchor checks; not a general semantic entailment check."""
import re

MODEL_TAG = re.compile(r"(?<![a-z0-9_.-])[a-z][a-z0-9_.-]*:\d+(?:\.\d+)?b(?:-[a-z0-9_.-]+)?(?![a-z0-9_.-])", re.I)
YEAR = re.compile(r"(?<!\d)20\d{2}(?!\d)")


def unsupported_query_anchors(question, results):
    text = "\n".join(r.text for r in results)
    requested_models = {s.lower() for s in MODEL_TAG.findall(question)}
    evidence_models = {s.lower() for s in MODEL_TAG.findall(text)}
    requested_years = set(YEAR.findall(question))
    evidence_years = set(YEAR.findall(text))
    return sorted((requested_models - evidence_models) | (requested_years - evidence_years))
