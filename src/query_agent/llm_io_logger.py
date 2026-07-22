"""
Pure LLM input/output logger for PageIndex experiments.

Registers a litellm callback that captures the exact request (messages, tools,
model) and response (content, tool_calls, finish_reason) for every litellm
call, regardless of call site — this catches both PageIndex's own
llm_completion/llm_acompletion (pageindex/utils.py) and calls made internally
by the OpenAI Agents SDK's LitellmModel, since both go through litellm.

Writes one JSON object per line (JSONL) to the given path.

Usage:
    from agent.llm_io_logger import enable
    enable("/tmp/my_run_io.jsonl")
    # ... run whatever makes litellm calls (sync or async, streaming or not) ...
"""
import json
import time
from pathlib import Path

import litellm
from litellm.integrations.custom_logger import CustomLogger


def _readable_arguments(arguments):
    """Re-encode a tool call's JSON-string arguments without \\uXXXX escapes,
    for log readability only — the escaped and unescaped forms are equally
    valid JSON, so this has no effect on how the arguments are parsed."""
    try:
        return json.dumps(json.loads(arguments), ensure_ascii=False)
    except (TypeError, ValueError):
        return arguments


def _serialize_tool_call(tc):
    tc = tc.model_dump() if hasattr(tc, "model_dump") else dict(tc)
    function = tc.get("function")
    if isinstance(function, dict) and "arguments" in function:
        function["arguments"] = _readable_arguments(function["arguments"])
    return tc


def _serialize_tool_calls(tool_calls):
    if not tool_calls:
        return None
    out = []
    for tc in tool_calls:
        if hasattr(tc, "model_dump") or isinstance(tc, dict):
            out.append(_serialize_tool_call(tc))
        else:
            out.append(str(tc))
    return out


def _readable_messages(messages):
    """Return a copy of messages with any embedded tool_calls arguments
    re-encoded for readability (see _readable_arguments)."""
    out = []
    for m in messages or []:
        m = dict(m)
        if m.get("tool_calls"):
            m["tool_calls"] = [_serialize_tool_call(tc) for tc in m["tool_calls"]]
        out.append(m)
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
            "input_messages": _readable_messages(messages),
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


_active_logger = None


def enable(path):
    """Register the logger as the sole litellm callback and return it.
    Truncates the log file so each run starts fresh (overwrite, not append
    across runs) — records within a single run are still appended in order."""
    global _active_logger
    open(path, "w", encoding="utf-8").close()
    logger = JSONLIOLogger(path)
    litellm.callbacks = [logger]
    _active_logger = logger
    return logger


def log_event(record: dict):
    """Append a harness-synthesized record (not an LLM call) to the active
    log, e.g. citations — a no-op if enable() hasn't been called."""
    if _active_logger is None:
        return
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **record}
    with open(_active_logger.path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
