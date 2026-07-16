import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pageindex import PageIndexClient

WORKSPACE = Path(__file__).parent / "data" / "index"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index a PDF or Markdown document into data/index/")
    parser.add_argument("path", type=str, help="Path to the PDF or Markdown file")
    parser.add_argument("--model", type=str, default=None, help="Model to use (overrides config.yaml)")
    args = parser.parse_args()

    client = PageIndexClient(model=args.model, workspace=str(WORKSPACE))
    doc_id = client.index(args.path)
    print(f"Indexed. doc_id: {doc_id}")
