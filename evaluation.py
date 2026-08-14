from __future__ import annotations

from typing import Any
import re


def korean_ratio(text: str) -> float:
    """Return the share of Hangul among Hangul and Latin letters."""
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    total = hangul + latin
    return hangul / total if total else 0.0


def sentence_count(text: str) -> int:
    normalized = text.strip()
    if not normalized:
        return 0
    normalized = re.sub(r"(?m)^\s*\d+[.)]\s*", "", normalized)
    endings = re.findall(r"[.!?](?:[\"'’”])?(?=\s|$)", normalized)
    return len(endings) if endings else 1


def numbered_item_count(text: str) -> int:
    lines = re.findall(r"(?m)^\s*(?:\d+[.)]|\[\d+\]|[-*])\s+", text)
    if lines:
        return len(lines)
    inline = re.findall(r"(?:^|\s)(?:\d+[.)]|\[\d+\])\s*", text)
    return len(inline)


def score_response(answer: str, case: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    scores: list[float] = []

    if case.get("require_korean"):
        ratio = korean_ratio(answer)
        passed = ratio >= 0.7
        checks["korean"] = {"ratio": round(ratio, 3), "passed": passed}
        scores.append(1.0 if passed else 0.0)

    if "expected_sentence_count" in case:
        actual = sentence_count(answer)
        expected = int(case["expected_sentence_count"])
        passed = actual == expected
        checks["sentence_count"] = {
            "expected": expected,
            "actual": actual,
            "passed": passed,
        }
        scores.append(1.0 if passed else 0.0)

    if "expected_numbered_items" in case:
        actual = numbered_item_count(answer)
        expected = int(case["expected_numbered_items"])
        passed = actual == expected
        checks["numbered_items"] = {
            "expected": expected,
            "actual": actual,
            "passed": passed,
        }
        scores.append(1.0 if passed else 0.0)

    keywords = case.get("expected_keywords", [])
    if keywords:
        matched = [keyword for keyword in keywords if keyword.lower() in answer.lower()]
        coverage = len(matched) / len(keywords)
        checks["keywords"] = {
            "expected": keywords,
            "matched": matched,
            "coverage": round(coverage, 3),
        }
        scores.append(coverage)

    auto_score = round(sum(scores) / len(scores) * 100, 1) if scores else 0.0
    return {"auto_score": auto_score, "checks": checks}
