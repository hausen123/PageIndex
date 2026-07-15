"""
Ask a question against the indexed document in agent/workspace/, without
re-indexing. Uses the harness-enforced agent loop (agent/guarded_agent.py):
get_page_content must be called at least once before any answer is accepted —
local models don't reliably follow "verify before answering" as a prompt
instruction, so this is enforced structurally instead.

Usage:
    python3 run_agent.py "質問文"
    python3 run_agent.py "質問文" --model ollama_chat/qwen3:14b
    python3 run_agent.py "質問文" --io-log /tmp/my_run_io.jsonl
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pageindex import PageIndexClient
from pageindex.utils import ConfigLoader
from agent.guarded_agent import query_agent_guarded

# Gemma4 release notes recommend top_k=50, min_p=0.05 to curb repetition collapse;
# temperature=0 (greedy) has no escape hatch since Ollama's sampler ignores repeat_penalty for this model.
GEMMA4_SAFE_KWARGS = {
    "temperature": 0.2,
    "top_p": 0.9,
    "extra_body": {"top_k": 50, "min_p": 0.05},
}

WORKSPACE = Path(__file__).parent / "agent" / "workspace"
DEFAULT_IO_LOG = "/tmp/run_agent_io.jsonl"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", help="Question to ask the agent")
    parser.add_argument("--doc", default=None, help="doc_id to query directly, skipping document selection")
    parser.add_argument("--model", default=None, help="litellm model string (default: config.yaml's retrieve_model)")
    parser.add_argument("--io-log", default=DEFAULT_IO_LOG, help=f"Log raw LLM input/output as JSONL to this path (default: {DEFAULT_IO_LOG})")
    args = parser.parse_args()

    from agent.llm_io_logger import enable
    enable(args.io_log)
    print(f"Logging LLM I/O to: {args.io_log}")

    client = PageIndexClient(workspace=WORKSPACE)
    if not client.documents:
        raise RuntimeError(f"No cached document found in workspace: {WORKSPACE}")
    if args.doc and args.doc not in client.documents:
        raise RuntimeError(f"--doc={args.doc!r} not found. Available: {list(client.documents.keys())}")

    # Note: client.retrieve_model is normalized for the OpenAI Agents SDK (adds a
    # "litellm/" prefix); guarded_agent.py calls litellm directly, so we read the
    # raw config value instead.
    model = args.model or ConfigLoader().load().retrieve_model
    model_kwargs = GEMMA4_SAFE_KWARGS if "gemma4" in model else {}

    print(f"Question: '{args.question}'")
    answer = query_agent_guarded(client, args.question, model=model, doc_id=args.doc, model_kwargs=model_kwargs)
    print("\n=== Final Answer ===")
    print(answer)


if __name__ == "__main__":
    main()
