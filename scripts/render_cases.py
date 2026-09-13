#!/usr/bin/env python3
"""Render selected full trajectories into a reviewer-friendly Markdown file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spark_math_eval.analysis import read_jsonl

CASES = (
    (
        "p1-id44-i39",
        "原生调用伴随关系方向修复",
        "直接策略把比例方向写反；计算器策略正确建模，并以两次原生调用验证 80。",
    ),
    (
        "p2-id27-i42",
        "原生调用伴随自我纠错",
        "直接策略重复计算最后一天；计算器策略识别首个错式并在第二次调用后得到 51。",
    ),
    (
        "p2-id44-i39",
        "策略条件改善但没有实际调用",
        "计算器条件答对但没有调用工具，说明配对改善不能自动归因于计算器本身。",
    ),
    (
        "main-id10-i44",
        "两次调用上限后的答案交付失败",
        "两次执行器调用都正确；schema 撤除后模型仍输出文字化第三次调用，未提交末答。",
    ),
    (
        "p1-id24-i08",
        "精确计算无法修复错误的问题建模",
        "直接策略最终纠正但被截断；计算器策略精确执行了运动热量符号错误的方程。",
    ),
    (
        "p2-id26-i27",
        "Right answer, wrong reasoning",
        "直接策略末答正确，却把连续减少 20% 和 50% 错称为总计减少 70%，"
        "并保留矛盾推导。",
    ),
    (
        "p2-id33-i27",
        "题面与金标解释存在歧义",
        "两臂均按“每周减少 5 个”的字面含义得到 14；金标 10 依赖“降到每周 5 个”的读法。",
    ),
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _text_block(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.splitlines())


def _record_markdown(record: dict[str, Any], question: str) -> str:
    lines = [
        f"### `{record['arm']}`",
        "",
        "系统提示：",
        "",
        "````text",
        _text_block(record["request"]["system_prompt"]),
        "````",
        "",
        "用户消息：",
        "",
        "````text",
        _text_block(f"{record['request']['policy']}\n\n题目（原文）：\n{question}"),
        "````",
        "",
    ]
    tool_results = {call["id"]: call for call in record.get("tool_calls", [])}
    for turn in record["turns"]:
        lines.extend(
            [
                f"第 {turn['turn']} 轮 assistant "
                f"（finish_reason=`{turn['finish_reason']}`）：",
                "",
                "````text",
                _text_block(turn["message"].get("content") or "<EMPTY>"),
                "````",
                "",
            ]
        )
        for call in turn["message"].get("tool_calls", []):
            captured = tool_results[call["id"]]
            lines.extend(
                [
                    "原生函数调用与执行器返回：",
                    "",
                    "````json",
                    _json(
                        {
                            "call": call,
                            "executor_result": captured["result"],
                            "executor_error": captured["error"],
                        }
                    ),
                    "````",
                    "",
                ]
            )
    return "\n".join(lines)


def render() -> str:
    root = Path(__file__).parents[1]
    records = read_jsonl(root / "runs/raw.jsonl")
    selected = read_jsonl(root / "third_party/gsm_symbolic_selected.jsonl")
    record_by_key = {(row["eval_id"], row["arm"]): row for row in records}
    sample_by_id = {row["eval_id"]: row for row in selected}
    lines = [
        "# 代表性完整轨迹",
        "",
        "以下案例是 75 条推理审阅中的可读索引，不替代 `runs/raw.jsonl` 的全部 "
        "120 条原始记录。内容由原始 JSON 确定性渲染，仅规范化行尾排版空格；"
        "字节级原始字符串以 raw JSON 为准。",
        "",
    ]
    for eval_id, title, finding in CASES:
        sample = sample_by_id[eval_id]
        lines.extend(
            [
                f"## {title}：`{eval_id}`",
                "",
                f"审阅结论：{finding}",
                "",
                f"严格金标：`{sample['gold_final']}`",
                "",
            ]
        )
        for arm in ("no_tool", "calculator"):
            lines.append(
                _record_markdown(record_by_key[(eval_id, arm)], sample["question"])
            )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    output = Path("reasoning/cases.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(), encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
