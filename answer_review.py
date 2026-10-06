"""Create local-only blank human review sheets from generated evaluation JSON."""
import argparse
import json
from pathlib import Path


def write_review_sheet(report_path):
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    lines = ["# PrivAI 답변 사람 검토표", "", "자동 점수는 사실성 판정이 아닙니다. 빈칸은 발표 전에 사람이 채워주세요.",
             "0=틀림, 1=부분적, 2=충분함. 거절은 적절/부적절, 응답시간은 수용/불편으로 표시합니다.",
             "", "검토자: ______  검토일: ______", ""]
    for row in report["results"]:
        if "answer" not in row:
            continue
        mode_label = f" · 근거 방식: {row['context_mode']}" if row.get("context_mode") else ""
        lines.extend([f"## {row['case_id']} · {row.get('generation_model', 'unknown')}{mode_label}", "",
                      f"질문: {row['question']}", "", row["answer"], "",
                      "검색 근거: " + ", ".join(row["retrieved"]),
                      f"전체 응답시간: {row['elapsed_seconds']:.3f}초", "",
                      "- 정답성(0/1/2): ___", "- 질문 조건·대상 일치(0/1/2): ___",
                      "- 출처가 실제 주장을 뒷받침하는가(0/1/2): ___",
                      "- 거절 적절성: ___", "- 응답시간 수용 여부: ___", "- 수정 의견: ___", ""])
    path = report_path.with_suffix(".review.md")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", type=Path, nargs="+")
    for path in parser.parse_args().reports:
        print(write_review_sheet(path))
