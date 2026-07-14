"""
Pure LLM input/output logger for PageIndex experiments.

Registers a litellm callback that captures the exact request (messages, tools,
model) and response (content, tool_calls, finish_reason) for every litellm
call, regardless of call site — this catches both PageIndex's own
llm_completion/llm_acompletion (pageindex/utils.py) and calls made internally
by the OpenAI Agents SDK's LitellmModel, since both go through litellm.

Writes one JSON object per line (JSONL) to the given path.

Usage:
    from tests.llm_io_logger import enable
    enable("/tmp/my_run_io.jsonl")
    # ... run whatever makes litellm calls (sync or async, streaming or not) ...
"""
import json
import time
from pathlib import Path

import litellm
from litellm.integrations.custom_logger import CustomLogger


def _serialize_tool_calls(tool_calls):
    if not tool_calls:
        return None
    out = []
    for tc in tool_calls:
        if hasattr(tc, "model_dump"):
            out.append(tc.model_dump())
        elif isinstance(tc, dict):
            out.append(tc)
        else:
            out.append(str(tc))
    return out


class JSONLIOLogger(CustomLogger):
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _record(self, kwargs, response_obj, start_time, end_time, ok, error=None):
        messages = kwargs.get("messages")
        model = kwargs.get("model")
        optional_params = kwargs.get("optional_params") or {}
        tools = optional_params.get("tools") or kwargs.get("tools")

        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_s": (end_time - start_time).total_seconds() if start_time and end_time else None,
            "model": model,
            "input_messages": messages,
            "tools": tools,
            "ok": ok,
        }

        if ok and response_obj is not None:
            try:
                choice = response_obj.choices[0]
                msg = choice.message
                record["output_content"] = msg.content
                record["output_reasoning"] = getattr(msg, "reasoning_content", None)
                record["output_tool_calls"] = _serialize_tool_calls(msg.tool_calls)
                record["finish_reason"] = choice.finish_reason
            except Exception as e:
                record["output_parse_error"] = str(e)
                record["output_raw"] = str(response_obj)[:5000]
        elif not ok:
            record["error"] = str(error)

        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._record(kwargs, response_obj, start_time, end_time, ok=True)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._record(kwargs, response_obj, start_time, end_time, ok=True)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self._record(kwargs, response_obj, start_time, end_time, ok=False, error=kwargs.get("exception"))

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self._record(kwargs, response_obj, start_time, end_time, ok=False, error=kwargs.get("exception"))


def enable(path):
    """Register the logger as the sole litellm callback and return it."""
    logger = JSONLIOLogger(path)
    litellm.callbacks = [logger]
    return logger
