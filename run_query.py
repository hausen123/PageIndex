"""
Ask a question against the indexed document(s) in data/index/, without
re-indexing. With more than one indexed document, the most relevant one is
auto-selected before answering. Uses the harness-enforced agent loop
(src/query_agent/guarded_agent.py): get_page_content must be called at least
once before any answer is accepted — local models don't reliably follow
"verify before answering" as a prompt instruction, so this is enforced
structurally instead. Prints the cited page ranges alongside the answer.

Usage:
    python run_query.py "質問文"
    python run_query.py "質問文" --log /tmp/my_run_io.jsonl

Model is set via config.yaml's retrieve_model, not a CLI flag.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pageindex import PageIndexClient
from pageindex.utils import ConfigLoader
from query_agent.guarded_agent import query_agent_guarded

# Gemma4 release notes recommend top_k=50, min_p=0.05 to curb repetition collapse;
# temperature=0 (greedy) has no escape hatch since Ollama's sampler ignores repeat_penalty for this model.
GEMMA4_SAFE_KWARGS = {
    "temperature": 0.2,
    "top_p": 0.9,
    "extra_body": {"top_k": 50, "min_p": 0.05},
}

WORKSPACE = Path(__file__).parent / "data" / "index"
DEFAULT_LOG = "/tmp/run_query_io.jsonl"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", help="Question to ask the agent")
    parser.add_argument("--log", default=DEFAULT_LOG, help=f"Log raw LLM input/output as JSONL to this path (default: {DEFAULT_LOG})")
    args = parser.parse_args()

    from query_agent.llm_io_logger import enable, log_event
    enable(args.log)
    print(f"Logging LLM I/O to: {args.log}")

    client = PageIndexClient(workspace=WORKSPACE)
    if not client.documents:
        raise RuntimeError(f"No cached document found in workspace: {WORKSPACE}")

    # Note: client.retrieve_model is normalized for the OpenAI Agents SDK (adds a
    # "litellm/" prefix); guarded_agent.py calls litellm directly, so we read the
    # raw config value instead.
    model = ConfigLoader().load().retrieve_model
    model_kwargs = GEMMA4_SAFE_KWARGS if "gemma4" in model else {}

    print(f"Question: '{args.question}'")
    answer, citations = query_agent_guarded(client, args.question, model=model, model_kwargs=model_kwargs)
    print("\n=== Final Answer ===")
    print(answer)
    print("\n=== 根拠資料 ===")
    for i, c in enumerate(citations, 1):
        print(f"[{i}]{c['doc_title']} ({c['doc_date']})(page {c['pages']})")
    log_event({"type": "citations", "citations": citations})


if __name__ == "__main__":
    main()
