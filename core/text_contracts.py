"""Conservative checks for explicit Markdown role pairs and verbatim UI lists.

These are source-derived contracts, not a general semantic truth checker.
"""
import re


def normalized(text):
    return re.sub(r"[^a-z0-9가-힣]", "", text.lower())


def verify_text_contracts(question, answer, results):
    body = re.sub(r"\[출처:[^\]]+\]", "", answer)
    checks = []
    issues = []
    if any(word in question for word in ("역할", "용도", "무슨 용", "각각")):
        for result in results:
            pairs = re.findall(r"(?m)^-\s+([^:\n]+):\s*\*\*([^*\n]+)\*\*\s*$", result.text)
            pairs = [(role, entity) for role, entity in pairs if entity.lower() in question.lower()]
            if len(pairs) < 2:
                continue
            # Unique source words identify an explicit conflicting role. Unknown
            # paraphrases remain unverified; they aren't classified as errors.
            words = [set(re.findall(r"[가-힣]{2,}|[a-zA-Z]{2,}", role.lower())) for role, _ in pairs]
            unique = [w - set().union(*(other for j, other in enumerate(words) if j != i)) for i, w in enumerate(words)]
            entities = "|".join(re.escape(entity) for _, entity in pairs)
            clauses = re.split(r"[.!?\n;,]+", body)
            for clause in clauses:
                matches = list(re.finditer(entities, clause, re.I))
                for pos, match in enumerate(matches):
                    entity = match.group()
                    index = next(i for i, (_, name) in enumerate(pairs) if name.lower() == entity.lower())
                    segment = normalized(clause[match.end():matches[pos + 1].start() if pos + 1 < len(matches) else len(clause)])
                    # A role introduced with '에는'/'에는 ... 사용' can belong
                    # to the NEXT entity, not the preceding one. Abstain rather
                    # than mislabel a grammatically inverted correct sentence.
                    if pos + 1 < len(matches) and re.search(r"(?:에는|에서는|위해)\s*$", clause[match.end():matches[pos + 1].start()]):
                        continue
                    # Negation/comparison requires semantic review, not this rule.
                    if any(marker in segment for marker in ("아니", "않", "보다", "대신")):
                        continue
                    for other, terms in enumerate(unique):
                        hits = [term for term in terms if normalized(term) in segment]
                        if other != index and len(hits) >= 2:
                            issues.append(f"역할 연결 불일치: {entity}에 {pairs[other][1]}의 근거 역할이 연결됐습니다.")
            checks.append({"type": "role_pairs", "source": result.source, "pairs": pairs})
            break
    # Exact wording is enforced only when the question explicitly requests UI
    # phrases and a count matching one source's quoted bullet list.
    count_match = re.search(r"(\d+)\s*(?:개|가지)", question)
    count = int(count_match.group(1)) if count_match else next((n for word, n in (("네 가지", 4), ("세 가지", 3), ("두 가지", 2)) if word in question), None)
    if count and "문구" in question:
        for result in results:
            items = re.findall(r"(?m)^-\s+`([^`\n]+)`\s*$", result.text)
            if len(items) != count:
                continue
            missing = [item for item in items if normalized(item) not in normalized(body)]
            issues.extend(f"필수 문구 누락 또는 변형: {item}" for item in missing)
            checks.append({"type": "verbatim_list", "source": result.source, "required": items, "missing": missing})
            break
    if not checks:
        return None
    return {"passed": False if issues else None,
            "method": "source_text_contract_validation",
            "display_label": "검증 실패" if issues else "역할·목록 제한 검사 완료 · 문장 의미는 사람 검토 필요",
            "checks": checks, "issues": issues}
