"""
Tree search demo against tests/data/NRA078003434-002-002.pdf using PageIndex + OpenAI Agents SDK.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import set_tracing_disabled
from agents.model_settings import ModelSettings

from pageindex import PageIndexClient
import pageindex.utils as utils

from examples.agentic_vectorless_rag_demo import query_agent

# Gemma4 release notes recommend top_k=50, min_p=0.05 to curb repetition collapse;
# temperature=0 (greedy) has no escape hatch since Ollama's sampler ignores repeat_penalty for this model.
GEMMA4_SAFE_SETTINGS = ModelSettings(
    temperature=0.2,
    top_p=0.9,
    extra_body={"top_k": 50, "min_p": 0.05},
)

PDF_PATH = Path(__file__).parent / "data" / "NRA078003434-002-002.pdf"
WORKSPACE = Path(__file__).parent / "workspace"


if __name__ == "__main__":

    set_tracing_disabled(True)

    client = PageIndexClient(workspace=WORKSPACE)

    doc_id = next(
        (did for did, doc in client.documents.items() if doc.get('doc_name') == PDF_PATH.name),
        None,
    )
    if doc_id:
        print(f"Loaded cached doc_id: {doc_id}")
    else:
        doc_id = client.index(PDF_PATH)
        print(f"Indexed. doc_id: {doc_id}")

    question = "耐震設計方針について、地震力の算定方法を説明してください。"
    print(f"\nQuestion: '{question}'")
    answer = query_agent(client, doc_id, question, verbose=True, model_settings=GEMMA4_SAFE_SETTINGS)
    print("\n\n=== Final Answer ===")
    print(answer)
