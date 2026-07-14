"""
Ask a question against the cached NRA078003434-002-002.pdf tree index via the
OpenAI Agents SDK, without re-indexing.

Usage:
    python3 tests/query_doc.py "質問文"
    python3 tests/query_doc.py "質問文" --model ollama_chat/qwen3:14b
    python3 tests/query_doc.py "質問文" --io-log /tmp/my_run_io.jsonl
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import set_tracing_disabled
from agents.model_settings import ModelSettings

from pageindex import PageIndexClient
from examples.agentic_vectorless_rag_demo import query_agent

# Gemma4 release notes recommend top_k=50, min_p=0.05 to curb repetition collapse;
# temperature=0 (greedy) has no escape hatch since Ollama's sampler ignores repeat_penalty for this model.
GEMMA4_SAFE_SETTINGS = ModelSettings(
    temperature=0.2,
    top_p=0.9,
    extra_body={"top_k": 50, "min_p": 0.05},
)

DEFAULT_MODEL = "ollama_chat/odytrice/gemma4:4090-26b"
WORKSPACE = Path(__file__).parent / "workspace"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", help="Question to ask the agent")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"litellm model string (default: {DEFAULT_MODEL})")
    parser.add_argument("--io-log", default=None, help="If set, log raw LLM input/output as JSONL to this path")
    parser.add_argument("--verbose", action="store_true", default=True, help="Print tool calls/outputs (default on)")
    args = parser.parse_args()

    if args.io_log:
        from tests.llm_io_logger import enable
        enable(args.io_log)
        print(f"Logging LLM I/O to: {args.io_log}")

    set_tracing_disabled(True)

    client = PageIndexClient(workspace=WORKSPACE)
    doc_id = next(iter(client.documents.keys()), None)
    if not doc_id:
        raise RuntimeError(f"No cached document found in workspace: {WORKSPACE}")
    client.retrieve_model = f"litellm/{args.model}"

    model_settings = GEMMA4_SAFE_SETTINGS if "gemma4" in args.model else None

    print(f"Question: '{args.question}'")
    answer = query_agent(client, doc_id, args.question, verbose=args.verbose, model_settings=model_settings)
    print("\n=== Final Answer ===")
    print(answer)


if __name__ == "__main__":
    main()
