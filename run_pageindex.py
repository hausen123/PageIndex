import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pageindex import PageIndexClient

WORKSPACE = Path(__file__).parent / "data" / "index"
DOCS_DIR = Path(__file__).parent / "data" / "docs"


def _copy_into_docs_dir(src_path: Path) -> Path:
    """Copy the source PDF into data/docs/, so indexed documents are kept
    alongside their cache rather than referencing an arbitrary external path.
    A no-op if the file already lives in data/docs/. On a filename collision
    with a different file already there, appends a short random suffix
    rather than overwriting."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    if src_path.parent == DOCS_DIR:
        return src_path

    dest_path = DOCS_DIR / src_path.name
    if dest_path.exists():
        dest_path = DOCS_DIR / f"{src_path.stem}_{uuid.uuid4().hex[:8]}{src_path.suffix}"
    shutil.copy2(src_path, dest_path)
    return dest_path


def _print_list(client: PageIndexClient):
    if not client.documents:
        print(f"No cached document found in workspace: {WORKSPACE}")
        return
    for doc_id, doc in client.documents.items():
        print(f"doc_id: {doc_id}")
        print(f"  doc_name : {doc.get('doc_name', '')}")
        print(f"  doc_title: {doc.get('doc_title', '')}")
        print(f"  doc_date : {doc.get('doc_date', '')}")
        print(f"  pages    : {doc.get('page_count', '')}")


def _print_toc(nodes: list, indent: int = 0):
    for node in nodes:
        pages = f"p.{node['start_index']}-{node['end_index']}"
        print(f"{'  ' * indent}{node.get('title', '')} ({pages})")
        if node.get("nodes"):
            _print_toc(node["nodes"], indent + 1)


def _print_show(client: PageIndexClient, doc_id: str):
    if doc_id not in client.documents:
        print(f"doc_id not found: {doc_id}")
        return
    doc = client.documents[doc_id]
    print(f"doc_id     : {doc_id}")
    print(f"doc_name   : {doc.get('doc_name', '')}")
    print(f"doc_title  : {doc.get('doc_title', '')}")
    print(f"doc_date   : {doc.get('doc_date', '')}")
    print(f"pages      : {doc.get('page_count', '')}")
    print(f"path       : {doc.get('path', '')}")
    print(f"description: {doc.get('doc_description', '')}")
    print()
    print("[目次]")
    structure = json.loads(client.get_document_structure(doc_id, titles_only=True))
    _print_toc(structure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index a PDF document into data/index/")
    parser.add_argument("path", type=str, nargs="?", help="Path to the PDF file to index")
    parser.add_argument("--list", action="store_true", help="List indexed documents")
    parser.add_argument("--show", metavar="DOC_ID", help="Show a single document's metadata and table of contents")
    parser.add_argument("--delete", metavar="DOC_ID", help="Remove a document's index cache (keeps the source PDF)")
    args = parser.parse_args()

    if args.list:
        _print_list(PageIndexClient(workspace=str(WORKSPACE)))
    elif args.show:
        _print_show(PageIndexClient(workspace=str(WORKSPACE)), args.show)
    elif args.delete:
        client = PageIndexClient(workspace=str(WORKSPACE))
        client.delete_document(args.delete)
        print(f"Deleted index cache for doc_id: {args.delete}")
    elif args.path:
        src_path = Path(args.path).expanduser().resolve()
        dest_path = _copy_into_docs_dir(src_path)

        client = PageIndexClient(workspace=str(WORKSPACE))
        doc_id = client.index(str(dest_path))
        print(f"Indexed. doc_id: {doc_id}")
    else:
        parser.error("provide a PDF path to index, or use --list / --show / --delete")
