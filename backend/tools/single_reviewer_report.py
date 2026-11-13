"""Single-reviewer final report prepared for a documented protocol deviation.

This report never sets `official_accepted`. It records that the two-reviewer
protocol was not met, reports single-reviewer descriptive rates, and only
evaluates the single-reviewer citation/workflow targets when the observed
workflow file is supplied.

Usage:
    python tools/single_reviewer_report.py dataset.json annotator-a.json report.json \
        --workflow workflow-observations.json \
        --approved-by "Name" --approval-reference "email/date"
"""
import argparse
import json
from pathlib import Path

from single_reviewer_pilot import compute


def workflow_metrics(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    records = data.get("records") or []
    grouped = {}
    prohibited = []
    for record in records:
        item_id = record.get("item_id")
        runs = ((record.get("prediction") or {}).get("runs") or [])
        grouped.setdefault(item_id, []).extend(runs)
        for run in runs:
            for flag in ("third_round", "duplicate_scoring", "qa_score_changed"):
                if run.get(flag) is True:
                    prohibited.append({"item_id": item_id,
                                       "variant": record.get("variant"),
                                       "repeat": run.get("repeat"), "flag": flag})
    scenarios = {}
    for item_id, runs in grouped.items():
        if len(runs) != 6:
            scenarios[item_id] = "pending"
            continue
        matches = [run.get("scenario_match") for run in runs]
        if any(value is False for value in matches):
            scenarios[item_id] = "fail"
        elif all(value is True for value in matches):
            scenarios[item_id] = "pass"
        else:
            scenarios[item_id] = "pending"
    passed = sum(1 for value in scenarios.values() if value == "pass")
    failed = [list(key) for key, value in scenarios.items() if value == "fail"]
    pending = [list(key) for key, value in scenarios.items() if value == "pending"]
    return {
        "provided": True,
        "scenario_status": {"passed": passed, "failed": len(failed), "pending": len(pending),
                            "total": len(scenarios)},
        "failed": failed,
        "pending": pending,
        "prohibited_errors": prohibited,
        "target": 18,
    }


def conclusion(result, workflow):
    citation = result["evidence"]["claim_support_rate"]
    if workflow is None or citation is None:
        status = "insufficient"
    elif (citation >= 0.85 and workflow["scenario_status"]["passed"] >= 18
          and not workflow["prohibited_errors"]):
        status = "pass"
    else:
        status = "fail"
    return {
        "status": status,
        "citation_support": citation,
        "citation_support_target": 0.85,
        "workflow": workflow,
        "note": (
            "Single-reviewer descriptive conclusion only. It does not satisfy the "
            "proposal's two-independent-reviewer agreement requirement and cannot "
            "set official_accepted."
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("annotation")
    parser.add_argument("output")
    parser.add_argument("--workflow")
    parser.add_argument("--approved-by", default="")
    parser.add_argument("--approval-reference", default="")
    parser.add_argument("--markdown")
    args = parser.parse_args()
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8-sig"))
    annotation = json.loads(Path(args.annotation).read_text(encoding="utf-8-sig"))
    result = compute(dataset, annotation)
    workflow = workflow_metrics(Path(args.workflow)) if args.workflow else None
    approved_by = args.approved_by.strip()
    reference = args.approval_reference.strip()
    report = {
        **result,
        "schema": "citepath-single-reviewer-final-v1",
        "status": "single_reviewer_evaluation",
        "official_accepted": None,
        "protocol_deviation": {
            "required_reviewers": 2,
            "provided_reviewers": 1,
            "approved_by": approved_by or None,
            "approval_reference": reference or None,
            "approval_status": "recorded" if approved_by and reference else "pending",
            "note": (
                "The proposal requires two independent human reviewers and adjudication. "
                "This report is a single-reviewer evaluation; do not describe it as the "
                "two-reviewer official result."
            ),
        },
        "single_reviewer_conclusion": conclusion(result, workflow),
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.markdown:
        workflow_line = "未提供 120 次观察"
        if workflow:
            workflow_line = (f"{workflow['scenario_status']['passed']}/20 场景通过，"
                             f"{workflow['scenario_status']['failed']} 失败，"
                             f"{workflow['scenario_status']['pending']} 待定，"
                             f"禁止错误 {len(workflow['prohibited_errors'])}")
        lines = [
            "# 单复核人评估报告（非正式双人评测）",
            "",
            f"- `official_accepted`: `null`",
            f"- 复核人：{report['annotator_id'] or '未填'}",
            f"- 完成标注：{result['label_completion']['completed']}/{result['label_completion']['expected']}",
            f"- MCQ 正确率：{result['mcq']['accuracy']}",
            f"- 简答通过率：{result['short']['pass_rate']}",
            f"- 引用支持率：{result['evidence']['claim_support_rate']}",
            f"- 流程：{workflow_line}",
            f"- 单复核人结论：`{report['single_reviewer_conclusion']['status']}`",
            f"- 协议偏离批准：{report['protocol_deviation']['approval_status']}",
            "",
            "本报告不是提案要求的两位独立人工复核 + 裁决结果，`official_accepted` 保持 `null`。",
        ]
        Path(args.markdown).write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": report["status"], "official_accepted": None,
                      "conclusion": report["single_reviewer_conclusion"]["status"],
                      "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
