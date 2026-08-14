from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import psutil

from core.ollama_client import OllamaClient
from evaluation import score_response


ROOT = Path(__file__).resolve().parent
DEFAULT_MODELS = ["qwen3:0.6b", "qwen3:1.7b"]
SYSTEM_PROMPT = "지시한 형식과 사실을 지키고 간결하고 정확한 한국어로 답하세요."


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_case(
    client: OllamaClient,
    process: psutil.Process,
    model: str,
    case: dict[str, Any],
) -> dict[str, Any]:
    memory_before = process.memory_info().rss
    response = client.chat(case["prompt"], model, SYSTEM_PROMPT)
    memory_after = process.memory_info().rss
    evaluation = score_response(response["answer"], case)
    return {
        "model": model,
        "case_id": case["id"],
        "title": case["title"],
        "prompt": case["prompt"],
        **response,
        **evaluation,
        "client_memory_delta_mb": round((memory_after - memory_before) / 1024 / 1024, 2),
    }


def summaries(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for model in dict.fromkeys(item["model"] for item in results):
        rows = [item for item in results if item["model"] == model]
        output.append(
            {
                "model": model,
                "cases": len(rows),
                "average_seconds": round(mean(row["elapsed_seconds"] for row in rows), 3),
                "average_tokens_per_second": round(
                    mean(row["tokens_per_second"] or 0 for row in rows), 2
                ),
                "average_auto_score": round(mean(row["auto_score"] for row in rows), 1),
            }
        )
    return output


def write_reports(
    output_dir: Path,
    stamp: str,
    results: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
) -> list[Path]:
    output_dir.mkdir(exist_ok=True)
    json_path = output_dir / f"evaluation-{stamp}.json"
    csv_path = output_dir / f"evaluation-{stamp}.csv"
    md_path = output_dir / f"evaluation-{stamp}.md"

    json_path.write_text(
        json.dumps({"summary": summary_rows, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )

    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "model",
                "case_id",
                "title",
                "elapsed_seconds",
                "tokens_per_second",
                "eval_count",
                "auto_score",
                "answer",
            ],
        )
        writer.writeheader()
        for row in results:
            writer.writerow({key: row.get(key) for key in writer.fieldnames})

    lines = [
        "# Local LLM 자동 평가 보고서",
        "",
        "> 자동 점수는 형식 준수, 한국어 비율, 핵심어 포함 여부만 평가합니다. 사실성은 사람이 별도로 검토해야 합니다.",
        "",
        "## 모델 요약",
        "",
        "| 모델 | 문항 | 평균 시간(초) | 평균 token/s | 평균 자동점수 |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['model']} | {row['cases']} | {row['average_seconds']} | "
            f"{row['average_tokens_per_second']} | {row['average_auto_score']} |"
        )
    lines.extend(["", "## 문항별 결과", ""])
    for row in results:
        lines.extend(
            [
                f"### {row['model']} · {row['title']}",
                "",
                f"- 시간: {row['elapsed_seconds']}초",
                f"- 속도: {row['tokens_per_second'] or '-'} token/s",
                f"- 자동점수: {row['auto_score']}",
                "",
                row["answer"].strip(),
                "",
                "- 사람 검토 — 사실성(1~5): ",
                "- 사람 검토 — 자연스러움(1~5): ",
                "- 사람 검토 메모: ",
                "",
            ]
        )
    md_path.write_text("\n".join(lines), encoding="utf-8-sig")
    return [json_path, csv_path, md_path]


def main() -> None:
    parser = argparse.ArgumentParser(description="Ollama 경량 모델 한국어 자동 평가")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--cases", default=str(ROOT / "evaluation_cases.json"))
    parser.add_argument("--max-cases", type=int, default=None)
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    if args.max_cases is not None:
        cases = cases[: max(args.max_cases, 0)]
    if not cases:
        raise SystemExit("실행할 평가 문항이 없습니다.")

    client = OllamaClient()
    process = psutil.Process()
    results = []
    for model in args.models:
        print(f"\n[{model}] 평가 시작 ({len(cases)}문항)")
        for index, case in enumerate(cases, start=1):
            result = run_case(client, process, model, case)
            results.append(result)
            print(
                f"  {index}/{len(cases)} {case['title']}: "
                f"{result['elapsed_seconds']:.2f}s, "
                f"{result['tokens_per_second'] or 0:.2f} token/s, "
                f"자동점수 {result['auto_score']:.1f}"
            )

    summary_rows = summaries(results)
    paths = write_reports(
        ROOT / "benchmark-results",
        datetime.now().strftime("%Y%m%d-%H%M%S"),
        results,
        summary_rows,
    )
    print("\n모델 요약")
    for row in summary_rows:
        print(
            f"  {row['model']}: {row['average_seconds']}초, "
            f"{row['average_tokens_per_second']} token/s, "
            f"자동점수 {row['average_auto_score']}"
        )
    for path in paths:
        print(f"결과 저장: {path}")


if __name__ == "__main__":
    main()
