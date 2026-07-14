# Local Ollama / gemma4 testing

This directory holds tooling and fixtures used to validate PageIndex's agentic
tree-search flow (`examples/agentic_vectorless_rag_demo.py`) against local
models served via [Ollama](https://ollama.com), as an alternative to
OpenAI/Anthropic-hosted models.

## Prerequisites

1. Ollama installed and running, with a model pulled:
   ```bash
   ollama pull odytrice/gemma4:4090-26b
   ```
   gemma4:26b (Q4, tuned for a 24GB GPU) is the model this workflow has been
   validated against. See "Model notes" below before switching models.

2. A cached tree index for the PDF you want to query, in `tests/workspace/`
   (one `<doc_id>.json` file per document — see `PageIndexClient(workspace=...)`
   in `pageindex/client.py`). Build one either by running `python3
   run_pageindex.py --pdf_path <file>` and wrapping the resulting
   `results/<name>_structure.json` into a workspace doc entry, or by calling
   `PageIndexClient.index(pdf_path)` directly, which indexes and caches it.

No API keys are required for this flow — it talks to Ollama over HTTP, not
OpenAI/Anthropic.

## Asking a question

```bash
source .venv/bin/activate
python3 tests/query_doc.py "質問文"
```

Options:
- `--model <litellm model string>` — defaults to `ollama_chat/odytrice/gemma4:4090-26b`.
  Use `ollama_chat/`, not `ollama/` — the latter leaks tool-call JSON into plain
  text during streaming instead of proper `tool_calls` deltas, which breaks the
  Agents SDK's tool-call detection entirely.
- `--io-log <path>` — logs every LLM call's exact input messages, tools, and
  output (content/tool_calls/reasoning/finish_reason) to a JSONL file via
  `tests/llm_io_logger.py`. Use this whenever debugging an agent that
  loops, hallucinates, or answers off-topic — it lets you see exactly what
  the model had in context at each step, rather than guessing.

`tests/io_logs/` has three reference logs (gemma4:26b, qwen3:14b, qwen3:30b)
from a run that worked correctly, useful as a "what good output looks like"
baseline.

## Model notes

Sampling parameters matter a lot for gemma4 specifically: Ollama's Go sampler
silently ignores `repeat_penalty` for gemma4, so `temperature=0` (greedy) has
no escape hatch once the model starts repeating itself. `tests/query_doc.py`
applies gemma4's officially recommended settings (`temperature=0.2, top_p=0.9,
top_k=50, min_p=0.05`) automatically when the model name contains "gemma4".

Compared across accuracy, completeness, and speed on this test document,
gemma4:26b outperformed qwen3:14b and qwen3:30b (see commit history / the
reference io_logs above for details) — hence it's the default.

## Known failure modes and mitigations already in place

Local models don't follow tool-use conventions as reliably as GPT-4o/GPT-5.x.
Things that have bitten this flow, and what was done about each:

1. **Full tree structure (with summaries) floods the model's context** and it
   gets stuck ruminating over candidate sections without ever calling a tool.
   → `get_document_structure()` now returns titles/page-ranges only
   (`titles_only=True`), no summaries.
2. **No section title matches the question's wording** (the topic is discussed
   inside a differently-titled section). → `search_document(keyword)` does a
   plain substring search over all page content as a fallback.
3. **A `search_document` snippet cuts off mid-sentence** and the model can't
   resolve the ambiguity from the snippet alone, so it loops. → the system
   prompt tells the agent to always follow up with `get_page_content` on the
   matching page(s) before answering, rather than answering from the snippet.

Even with all of the above, gemma4 can still occasionally collapse into a
repetition loop (a documented upstream issue — see the vLLM/Ollama GitHub
issues linked in commit `18d3e98`). If a run seems to hang, check GPU
utilization (`nvidia-smi`) — if it's near-idle but the process is still
"running", it's likely stuck in a loop and safe to kill and retry.
