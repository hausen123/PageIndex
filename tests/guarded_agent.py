"""
Hand-rolled agent loop that structurally guarantees get_page_content is called
at least once before any final answer is accepted from the model — a harness-
level guarantee rather than a system-prompt request, since local models don't
reliably follow "always verify before answering" as an instruction (see
tests/README.md for the measured failure rate without this gate).

Uses litellm directly (bypassing the OpenAI Agents SDK's Runner) so we control
turn-by-turn whether a "final answer" is accepted or rejected and forced to
continue.
"""
import json
import logging
import os
import time

import litellm

_LLM_TIMEOUT = float(os.getenv("PAGEINDEX_LLM_TIMEOUT", "1800"))
_LLM_MAX_RETRIES = 5


def _completion_with_retries(**kwargs):
    for attempt in range(_LLM_MAX_RETRIES):
        try:
            return litellm.completion(timeout=_LLM_TIMEOUT, **kwargs)
        except Exception as e:
            logging.error(f"LLM call failed (attempt {attempt + 1}/{_LLM_MAX_RETRIES}): {e}")
            if attempt < _LLM_MAX_RETRIES - 1:
                time.sleep(2)
            else:
                raise

SYSTEM_PROMPT = """
You are PageIndex, a document QA assistant.
TOOL USE:
- Call get_document() first to confirm status and page/line count.
- Call get_document_structure() to get a lightweight table of contents (titles and
  page ranges only, no summaries). Some node titles are just a short heading;
  others happen to be a full sentence of source text. Either way, a title is a
  pointer to where to look, never the full answer by itself.
- Always call search_document(keyword) with a short keyword from the question, even
  if a title already looks like a match — a topic is often split across multiple
  sections (e.g. one section identifies a risk, a separate section covers the
  actual countermeasure/design for it). search_document reports every page the
  keyword appears on (pages_with_match) — check that list for other candidate
  pages before moving on.
- Call get_page_content(pages="5-7") with tight ranges; never fetch the whole
  document. You must call it before answering — this is enforced, not optional.
- Before each tool call, output one short sentence explaining the reason.
Always answer in Japanese (日本語で回答してください), regardless of what language your
reasoning or tool-call explanations were in. Answer based only on tool output. Be concise.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_document",
            "description": "Get document metadata: status, page count, name, and description.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_structure",
            "description": "Get a lightweight table of contents (titles and page ranges only, no summaries).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_content",
            "description": (
                "Get the text content of specific pages. Use tight ranges: e.g. '5-7' for "
                "pages 5 to 7, '3,8' for pages 3 and 8, '12' for page 12."
            ),
            "parameters": {
                "type": "object",
                "properties": {"pages": {"type": "string"}},
                "required": ["pages"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_document",
            "description": (
                "Search all page content for a keyword substring (case-insensitive). "
                "Returns every matching page (pages_with_match), not just a sample."
            ),
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"],
            },
        },
    },
]

NUDGE_MESSAGE = (
    "You have not called get_page_content yet in this conversation. You must read the "
    "actual page content with get_page_content before answering — do not answer from "
    "titles or search snippets alone, they can omit or cut off the exact detail the "
    "question asks about. Call get_page_content on the relevant page(s) now."
)


def _execute_tool(client, doc_id, name, args):
    if name == "get_document":
        return client.get_document(doc_id)
    elif name == "get_document_structure":
        return client.get_document_structure(doc_id, titles_only=True)
    elif name == "get_page_content":
        return client.get_page_content(doc_id, args.get("pages", ""))
    elif name == "search_document":
        return client.search_document(doc_id, args.get("keyword", ""))
    return json.dumps({"error": f"Unknown tool: {name}"})


def query_agent_guarded(
    client,
    doc_id: str,
    question: str,
    model: str,
    model_kwargs: dict | None = None,
    max_turns: int = 12,
    verbose: bool = True,
) -> str:
    """
    Ask a question with a hard guarantee: get_page_content must be called at
    least once before a final answer is accepted. If the model tries to answer
    without it, the answer is discarded and the model is told to continue.
    """
    model_kwargs = model_kwargs or {}
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    page_content_called = False

    for _ in range(max_turns):
        response = _completion_with_retries(model=model, messages=messages, tools=TOOLS, tool_choice="auto", **model_kwargs)
        msg = response.choices[0].message

        if msg.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                }
            )
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name == "get_page_content":
                    page_content_called = True
                result = _execute_tool(client, doc_id, name, args)
                if verbose:
                    print(f"\n[tool call]: {name}({args})")
                    preview = result[:200] + "..." if len(result) > 200 else result
                    print(f"[tool call output]: {preview}")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            continue

        # Model produced a final answer with no tool call.
        if not page_content_called:
            if verbose:
                print("\n[guard] rejected answer — get_page_content not yet called, forcing continuation")
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({"role": "user", "content": NUDGE_MESSAGE})
            continue

        return msg.content or ""

    return "[Error: exceeded max_turns without a verified (get_page_content-backed) answer]"
