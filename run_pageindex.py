import argparse
from pathlib import Path

from pageindex import PageIndexClient

WORKSPACE = Path(__file__).parent / "agent" / "workspace"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index a PDF or Markdown document into the agent workspace")
    parser.add_argument("path", type=str, help="Path to the PDF or Markdown file")
    parser.add_argument("--model", type=str, default=None, help="Model to use (overrides config.yaml)")
    args = parser.parse_args()

    client = PageIndexClient(model=args.model, workspace=str(WORKSPACE))
    doc_id = client.index(args.path)
    print(f"Indexed. doc_id: {doc_id}")
