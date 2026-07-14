"""
Ask a question against the cached NRA078003434-002-002.pdf tree index, without
re-indexing. Uses the harness-enforced agent loop (tests/guarded_agent.py):
get_page_content must be called at least once before any answer is accepted —
local models don't reliably follow "verify before answering" as a prompt
instruction, so this is enforced structurally instead.

Usage:
    python3 tests/query_doc.py "質問文"
    python3 tests/query_doc.py "質問文" --model ollama_chat/qwen3:14b
    python3 tests/query_doc.py "質問文" --io-log /tmp/my_run_io.jsonl
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pageindex import PageIndexClient
from tests.guarded_agent import query_agent_guarded

# Gemma4 release notes recommend top_k=50, min_p=0.05 to curb repetition collapse;
# temperature=0 (greedy) has no escape hatch since Ollama's sampler ignores repeat_penalty for this model.
GEMMA4_SAFE_KWARGS = {
    "temperature": 0.2,
    "top_p": 0.9,
    "extra_body": {"top_k": 50, "min_p": 0.05},
}

DEFAULT_MODEL = "ollama_chat/odytrice/gemma4:4090-26b"
WORKSPACE = Path(__file__).parent / "workspace"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", help="Question to ask the agent")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"litellm model string (default: {DEFAULT_MODEL})")
    parser.add_argument("--io-log", default=None, help="If set, log raw LLM input/output as JSONL to this path")
    args = parser.parse_args()

    if args.io_log:
        from tests.llm_io_logger import enable
        enable(args.io_log)
        print(f"Logging LLM I/O to: {args.io_log}")

    client = PageIndexClient(workspace=WORKSPACE)
    doc_id = next(iter(client.documents.keys()), None)
    if not doc_id:
        raise RuntimeError(f"No cached document found in workspace: {WORKSPACE}")

    model_kwargs = GEMMA4_SAFE_KWARGS if "gemma4" in args.model else {}

    print(f"Question: '{args.question}'")
    answer = query_agent_guarded(client, doc_id, args.question, model=args.model, model_kwargs=model_kwargs)
    print("\n=== Final Answer ===")
    print(answer)


if __name__ == "__main__":
    main()
