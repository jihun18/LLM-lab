"""Limited role lists and per-tool measured memory rows; no general NLP."""
import re
from .table_comparison import _tables


def plain_role_pairs(text):
    pairs = []
    explicit = re.findall(r"(?m)^-\s+\*{0,2}([A-Za-z][A-Za-z0-9_.-]*)\*{0,2}:\s*(.+)$", text)
    # Only this explicit reversed layout carries both an identity and value.
    # Do not reinterpret generic '- description: **Name**' Wiki bullets.
    explicit += re.findall(r"(?m)^-\s+역할:\s*\*\*([A-Za-z][A-Za-z0-9_.-]*)\*\*\s+—\s+(.+)$", text)
    for name, role in explicit:
        # A mere name, numeric resource amount, or arbitrary note is not a role.
        if any(term in role.lower() for term in ("api", "ui", "백엔드", "구현", "비교군", "시연", "화면", "학습")):
            pairs.append((name, role.strip()))
    return pairs


def memory_rows(name, result, statistic=None):
    rows_found = []
    for headers, rows in _tables(result.text):
        columns = [i for i, header in enumerate(headers)
                   if "메모리 사용" in header or "메모리사용" in header
                   or "rss" in header.lower() or "ram 사용" in header.lower()]
        all_memory_columns = set(columns)
        if statistic:
            # A generic RSS cell, row maximum, or document heading cannot
            # establish a measurement statistic. Require one explicit header.
            metric = r"(?:메모리(?:사용량)?|RSS|RAM(?:사용량)?)"
            columns = [i for i in columns if re.fullmatch(
                "(?:" + statistic + metric + "|" + metric + statistic + ")",
                re.sub(r"\s+", "", headers[i]), re.I)]
            if len(columns) != 1:
                continue
        # Recognize an explicit identity column, not the first matching cell.
        identity = [i for i, header in enumerate(headers)
                    if header.strip().lower() in {"도구", "프레임워크", "대상", "tool", "framework", "대상명", "도구명"}]
        if len(identity) != 1:
            continue
        target_column = identity[0]
        for row in rows:
            if row[target_column].lower() != name.lower():
                continue
            if any(re.fullmatch(r"\d+(?:\.\d+)?\s*(?:GB|MB|KB|GiB|MiB|KiB)", row[i], re.I) for i in columns):
                rows_found.append("; ".join(f"{headers[i]} — {row[i]}" for i in range(len(headers))
                                            if i != target_column and
                                            (not statistic or i not in all_memory_columns or i in columns)))
    return rows_found


def role_candidates(name, results):
    candidates = []
    for result in results:
        candidates.extend((role, result) for entity, role in plain_role_pairs(result.text) if entity.lower() == name.lower())
        for headers, rows in _tables(result.text):
            if headers[0] == "항목":
                for i, entity in enumerate(headers[1:], 1):
                    if entity.lower() == name.lower():
                        candidates.extend((row[i], result) for row in rows if row[0] == "역할" and row[i])
    return candidates


def role_value_key(value):
    normalized = re.sub(r"[\s*`]", "", value).lower()
    # Two documented project wording pairs only, not semantic equivalence NLP.
    return {"최소구현비교": "최소비교군", "빠른aiui": "빠른데모ui"}.get(normalized, normalized)
