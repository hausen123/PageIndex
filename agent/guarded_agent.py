"""
Hand-rolled agent loop that structurally guarantees get_page_content is called
at least once before any final answer is accepted from the model — a harness-
level guarantee rather than a system-prompt request, since local models don't
reliably follow "always verify before answering" as an instruction (see
agent/README.md for the measured failure rate without this gate).

Uses litellm directly (bypassing the OpenAI Agents SDK's Runner) so we control
turn-by-turn whether a "final answer" is accepted or rejected and forced to
continue.
"""
import json
import logging
import time

import litellm

from pageindex.utils import ConfigLoader

_LLM_TIMEOUT = ConfigLoader().load().llm_timeout
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
Document metadata (name, description, page count) and its table of contents (titles
and page ranges only, no summaries) are provided below — no need to look them up
yourself. Some node titles are just a short heading; others happen to be a full
sentence of source text. Either way, a title is a pointer to where to look, never
the full answer by itself.
TOOL USE:
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

SELECT_DOCUMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "select_document",
        "description": "Select which document to use to answer the question.",
        "parameters": {
            "type": "object",
            "properties": {"doc_id": {"type": "string"}},
            "required": ["doc_id"],
        },
    },
}

_SELECT_DOCUMENT_NUDGE = (
    "That doc_id does not exist. Available doc_ids are: {doc_ids}. "
    "Call select_document again with one of these exact doc_id values."
)


def _select_document(client, question: str, model: str, model_kwargs: dict, verbose: bool = True) -> str:
    """
    A single, isolated turn (separate from the main tool loop) whose only job is
    to pick which workspace document to query. Forced via tool_choice so the
    model can't skip straight to answering — only used when the workspace holds
    more than one document; see query_agent_guarded.
    """
    docs = [
        {
            "doc_id": did,
            "doc_name": doc.get("doc_name", ""),
            "doc_description": doc.get("doc_description", ""),
        }
        for did, doc in client.documents.items()
    ]
    messages = [
        {
            "role": "user",
            "content": (
                "Select the document most relevant to the following question by calling "
                "select_document with its doc_id.\n\n"
                f"Question: {question}\n\n"
                f"Available documents:\n{json.dumps(docs, ensure_ascii=False, indent=2)}"
            ),
        }
    ]

    for _ in range(3):
        response = _completion_with_retries(
            model=model,
            messages=messages,
            tools=[SELECT_DOCUMENT_TOOL],
            tool_choice={"type": "function", "function": {"name": "select_document"}},
            **model_kwargs,
        )
        msg = response.choices[0].message
        tool_calls = msg.tool_calls or []
        if not tool_calls:
            messages.append({"role": "user", "content": "You must call select_document."})
            continue

        try:
            args = json.loads(tool_calls[0].function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        doc_id = args.get("doc_id")

        if verbose:
            print(f"\n[select_document]: {doc_id}")

        if doc_id in client.documents:
            return doc_id

        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in tool_calls],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_calls[0].id,
                "content": _SELECT_DOCUMENT_NUDGE.format(doc_ids=list(client.documents.keys())),
            }
        )

    raise RuntimeError("Failed to select a valid document after 3 attempts")


def _execute_tool(client, doc_id, name, args):
    if name == "get_page_content":
        return client.get_page_content(doc_id, args.get("pages", ""))
    elif name == "search_document":
        return client.search_document(doc_id, args.get("keyword", ""))
    return json.dumps({"error": f"Unknown tool: {name}"})


def query_agent_guarded(
    client,
    question: str,
    model: str,
    doc_id: str | None = None,
    model_kwargs: dict | None = None,
    max_turns: int = 12,
    verbose: bool = True,
) -> str:
    """
    Ask a question with a hard guarantee: get_page_content must be called at
    least once before a final answer is accepted. If the model tries to answer
    without it, the answer is discarded and the model is told to continue.

    doc_id: which workspace document to query. If None: auto-selected when the
    workspace holds exactly one document; with 2+ documents, a forced, isolated
    tool call (_select_document) picks one before the main loop starts — the
    main loop itself is identical either way.

    get_document metadata and get_document_structure's table of contents are
    fetched by the harness and injected below rather than left as first-turn
    tool choices: both take no arguments and are always called once the
    document is fixed, so there is nothing for the LLM to decide — no LLM
    turn is spent on either.
    """
    model_kwargs = model_kwargs or {}

    if doc_id is None:
        if len(client.documents) == 1:
            doc_id = next(iter(client.documents))
        elif len(client.documents) > 1:
            doc_id = _select_document(client, question, model, model_kwargs, verbose=verbose)
        else:
            raise RuntimeError("No documents found in workspace")

    doc_info = client.get_document(doc_id)
    doc_structure = client.get_document_structure(doc_id, titles_only=True)
    if verbose:
        print(f"\n[get_document]: {doc_info}")
        print(f"\n[get_document_structure]: {doc_structure}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Document metadata: {doc_info}\n\n"
                f"Table of contents: {doc_structure}\n\n"
                f"Question: {question}"
            ),
        },
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
