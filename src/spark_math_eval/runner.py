"""Run one paired Spark-X2.5 evaluation episode through the official SDK."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

from . import DATASET_REVISION, MODEL_REVISION
from .calculator import CalculatorError, calculate

SYSTEM_PROMPT = (
    "Solve the math problem step by step. If a calculator tool is available, you "
    "may use it only for arithmetic after deciding what to compute; otherwise "
    "calculate yourself. End with exactly one line: FINAL_ANSWER: <number>, where "
    "<number> is one integer, decimal, or fraction and has no unit. Do not write "
    "anything after that line."
)
CALCULATOR_TOOL = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": (
            "Evaluate one already-formulated arithmetic expression exactly. This "
            "tool does not interpret or solve the word problem."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": (
                        "Arithmetic using numeric literals, parentheses, and "
                        "+ - * / // % ** only."
                    ),
                }
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
    },
}
RUN_ORDER_SALT = "20260913"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def episode_seed(eval_id: str) -> int:
    return 20260913 + int(sha256_text(f"seed|{eval_id}")[:8], 16) % 1_000_000


def job_order(eval_id: str, arm: str) -> str:
    return sha256_text(f"{RUN_ORDER_SALT}|{eval_id}|{arm}")


def _usage_dict(usage: Any) -> dict[str, int] | None:
    if usage is None:
        return None
    return {
        "prompt_tokens": int(usage.prompt_tokens),
        "completion_tokens": int(usage.completion_tokens),
        "total_tokens": int(usage.total_tokens),
    }


def _tool_result(arguments: str) -> tuple[dict[str, Any], str | None]:
    try:
        parsed = json.loads(arguments)
        if not isinstance(parsed, dict) or set(parsed) != {"expression"}:
            raise CalculatorError("arguments_must_only_contain_expression")
        result = calculate(parsed["expression"])
        return result, None
    except (json.JSONDecodeError, CalculatorError, TypeError) as exc:
        error = str(exc) or type(exc).__name__
        return {"ok": False, "error": error}, error


def run_episode(
    *,
    base_url: str,
    served_model: str,
    sample: dict[str, Any],
    arm: str,
    protocol_commit: str,
    runtime: dict[str, Any],
    max_completion_tokens: int = 4096,
    max_tool_calls: int = 2,
) -> dict[str, Any]:
    if arm not in {"no_tool", "calculator"}:
        raise ValueError(f"unknown arm: {arm}")
    question = str(sample["question"])
    if "####" in question or "canary" in question.lower():
        raise ValueError("forbidden answer/canary material detected in question")

    seed = episode_seed(str(sample["eval_id"]))
    record: dict[str, Any] = {
        "schema_version": 1,
        "eval_id": sample["eval_id"],
        "config": sample["config"],
        "id": sample["id"],
        "instance": sample["instance"],
        "arm": arm,
        "model": "XHToken/Spark-X2.5-4B",
        "model_revision": MODEL_REVISION,
        "dataset": "apple/GSM-Symbolic",
        "dataset_revision": DATASET_REVISION,
        "protocol_commit": protocol_commit,
        "seed": seed,
        "settings": {
            "thinking": True,
            "temperature": 0.0,
            "top_p": 1.0,
            "top_k": -1,
            "n": 1,
            "max_cumulative_completion_tokens": max_completion_tokens,
            "max_tool_calls": max_tool_calls if arm == "calculator" else 0,
            "parallel_tool_calls": False,
        },
        "request": {
            "system_prompt": SYSTEM_PROMPT,
            "system_prompt_sha256": sha256_text(SYSTEM_PROMPT),
            "user_prompt_ref": (
                f"third_party/gsm_symbolic_selected.jsonl#{sample['eval_id']}"
            ),
            "user_prompt_sha256": sha256_text(question),
            "tool_schema": CALCULATOR_TOOL if arm == "calculator" else None,
        },
        "runtime": runtime,
        "started_at": datetime.now(UTC).isoformat(),
        "turns": [],
        "tool_calls": [],
        "status": "running",
    }

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    remaining = max_completion_tokens
    executed_tool_calls = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    started = time.perf_counter()

    with httpx.Client(timeout=300.0, trust_env=False) as transport:
        client = OpenAI(
            base_url=base_url,
            api_key="local-evaluation-no-secret",
            http_client=transport,
        )
        for turn_number in range(1, 4):
            if remaining <= 0:
                record["status"] = "completion_budget_exhausted"
                break
            tools = None
            if arm == "calculator" and executed_tool_calls < max_tool_calls:
                tools = [CALCULATOR_TOOL]
            kwargs: dict[str, Any] = {
                "model": served_model,
                "messages": messages,
                "temperature": 0.0,
                "top_p": 1.0,
                "max_tokens": remaining,
                "seed": seed + turn_number - 1,
                "parallel_tool_calls": False,
                "extra_body": {
                    "top_k": -1,
                    "repetition_penalty": 1.0,
                    "chat_template_kwargs": {"enable_thinking": True},
                },
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            turn_started = time.perf_counter()
            response = client.chat.completions.create(**kwargs)
            elapsed = time.perf_counter() - turn_started
            choice = response.choices[0]
            message_dump = choice.message.model_dump(exclude_none=True)
            usage = _usage_dict(response.usage)
            completion_tokens = usage["completion_tokens"] if usage else 0
            prompt_tokens = usage["prompt_tokens"] if usage else 0
            total_completion_tokens += completion_tokens
            total_prompt_tokens += prompt_tokens
            remaining = max(0, max_completion_tokens - total_completion_tokens)
            record["turns"].append(
                {
                    "turn": turn_number,
                    "seed": seed + turn_number - 1,
                    "max_tokens_requested": kwargs["max_tokens"],
                    "tools_available": bool(tools),
                    "finish_reason": choice.finish_reason,
                    "message": message_dump,
                    "usage": usage,
                    "wall_seconds": round(elapsed, 6),
                }
            )

            tool_calls = choice.message.tool_calls or []
            if not tool_calls:
                record["terminal_content"] = choice.message.content
                record["terminal_finish_reason"] = choice.finish_reason
                record["status"] = "completed"
                break
            if arm != "calculator":
                record["status"] = "unexpected_tool_call"
                break
            if executed_tool_calls + len(tool_calls) > max_tool_calls:
                record["status"] = "tool_limit_exceeded"
                break

            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": choice.message.content,
                "tool_calls": [
                    call.model_dump(exclude_none=True) for call in tool_calls
                ],
            }
            messages.append(assistant_message)
            for call in tool_calls:
                executed_tool_calls += 1
                result, error = _tool_result(call.function.arguments)
                tool_record = {
                    "ordinal": executed_tool_calls,
                    "id": call.id,
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                    "result": result,
                    "error": error,
                }
                record["tool_calls"].append(tool_record)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.function.name,
                        "content": json.dumps(
                            result, ensure_ascii=False, sort_keys=True
                        ),
                    }
                )
        else:
            record["status"] = "turn_limit_exceeded"

    record["finished_at"] = datetime.now(UTC).isoformat()
    record["wall_seconds"] = round(time.perf_counter() - started, 6)
    record["total_prompt_tokens"] = total_prompt_tokens
    record["total_completion_tokens"] = total_completion_tokens
    record["tool_call_count"] = executed_tool_calls
    return record


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
