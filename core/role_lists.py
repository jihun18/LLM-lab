"""Limited role lists and per-tool measured memory rows; no general NLP."""
import re
from .table_comparison import _tables


def plain_role_pairs(text):
    pairs = []
    for name, role in re.findall(r"(?m)^-\s+\*{0,2}([A-Za-z][A-Za-z0-9_.-]*)\*{0,2}:\s*(.+)$", text):
        # A mere name, numeric resource amount, or arbitrary note is not a role.
        if any(term in role.lower() for term in ("api", "ui", "백엔드", "구현", "비교군", "시연", "화면", "학습")):
            pairs.append((name, role.strip()))
    return pairs


def memory_rows(name, result):
    rows_found = []
    for headers, rows in _tables(result.text):
        columns = [i for i, header in enumerate(headers)
                   if "메모리 사용" in header or "메모리사용" in header
                   or "rss" in header.lower() or "ram 사용" in header.lower()]
        for row in rows:
            if row[0].lower() != name.lower():
                continue
            if any(re.fullmatch(r"\d+(?:\.\d+)?\s*(?:GB|MB|KB|GiB|MiB)", row[i], re.I) for i in columns):
                rows_found.append("; ".join(f"{headers[i]} — {row[i]}" for i in range(1, len(headers))))
    return rows_found
