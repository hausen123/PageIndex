import argparse
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index a PDF document into data/index/")
    parser.add_argument("path", type=str, help="Path to the PDF file")
    parser.add_argument("--model", type=str, default=None, help="Model to use (overrides config.yaml)")
    args = parser.parse_args()

    src_path = Path(args.path).expanduser().resolve()
    dest_path = _copy_into_docs_dir(src_path)

    client = PageIndexClient(model=args.model, workspace=str(WORKSPACE))
    doc_id = client.index(str(dest_path))
    print(f"Indexed. doc_id: {doc_id}")
