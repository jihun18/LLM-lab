"""Bounded project-role comparison from explicit table columns, not LLM claims."""
import re


def _tables(text):
    lines = text.splitlines()
    for index in range(len(lines) - 1):
        if not lines[index].lstrip().startswith("|"):
            continue
        headers = [s.strip() for s in lines[index].strip().strip("|").split("|")]
        separator = [s.strip() for s in lines[index + 1].strip().strip("|").split("|")]
        if len(headers) != len(separator) or not all(re.fullmatch(r":?-{3,}:?", s) for s in separator):
            continue
        rows = []
        for line in lines[index + 2:]:
            if not line.lstrip().startswith("|"):
                break
            cells = [s.strip() for s in line.strip().strip("|").split("|")]
            if len(cells) != len(headers):
                rows = []
                break
            rows.append(cells)
        yield headers, rows


def deterministic_role_comparison(question, results):
    from .query_requirements import role_conflicts
    if role_conflicts(question, results):
        return None
    if not any(word in question for word in ("역할", "용도")) or not any(word in question for word in ("차이", "비교", "다른지")):
        return None
    candidates = []
    for source_index, result in enumerate(results):
        for headers, rows in _tables(result.text):
            if len(headers) < 3 or headers[0] != "항목":
                continue
            columns = [i for i in range(1, len(headers)) if re.search(r"(?<![a-z0-9_])" + re.escape(headers[i]) + r"(?![a-z0-9_])", question, re.I)]
            if len(columns) < 2 or len({headers[i].lower() for i in columns}) != len(columns):
                continue
            # Only simple role/comparison requests. Unknown names and additional
            # Korean requests cannot be silently omitted from the answer.
            remainder = question
            for column in columns:
                remainder = re.sub(re.escape(headers[column]), "", remainder, flags=re.I)
            remainder = re.sub(r"[\s,?.!·/]+", "", remainder)
            grammar = ("설명해주세요", "설명해줘", "비교해주세요", "비교해줘", "알려주세요", "알려줘",
                       "프레임워크", "프로젝트", "각각", "무엇인가요", "무엇이야", "어떻게", "다른지",
                       "차이는", "차이", "비교", "역할", "용도", "에서는", "에서", "여기", "이", "두", "의", "와", "과", "를", "을", "는", "은", "도")
            if not re.fullmatch("(?:" + "|".join(map(re.escape, grammar)) + ")*", remainder):
                continue
            selected = [row for row in rows if row[0] in {"역할", "API 문서"}]
            if not any(row[0] == "역할" for row in selected):
                continue
            if len({row[0] for row in selected}) != len(selected) or any(not row[i] for row in selected for i in columns):
                continue
            facts = [(headers[i], [(row[0], row[i]) for row in selected]) for i in columns]
            candidates.append((source_index, result, facts))
    if not candidates:
        return None
    # Two explicit comparison tables disagreeing => normal generation/review,
    # not an arbitrary first convenient table.
    signature = {name.lower(): dict(values) for name, values in candidates[0][2]}
    if any({name.lower(): dict(values) for name, values in facts} != signature for _, _, facts in candidates[1:]):
        return None
    source_index, source, facts = candidates[0]
    answer = "이 프로젝트의 Wiki 비교표 기준:\n"
    answer += "\n".join(f"- {name}: " + "; ".join(f"{label} — {value}" for label, value in values) for name, values in facts)
    answer += "\n\n이 표는 프로젝트의 구현 차이이며, 프레임워크의 일반적인 성능이나 기능 한계를 뜻하지 않습니다."
    answer += f"\n\n[출처: {source.source}#{source.heading}]"
    return answer, {"passed": True, "method": "deterministic_role_comparison",
                    "display_label": "역할 비교표 원문 추출 완료", "facts": facts,
                    "source_index": source_index, "issues": [],
                    "scope": "원문 셀의 복사 여부만 보장하며 원문 자체의 사실성은 보장하지 않습니다."}
