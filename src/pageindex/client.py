import os
import uuid
import json
from datetime import datetime
from pathlib import Path

from .page_index import page_index
from .retrieve import get_document, get_document_structure, get_page_content, search_document
from .utils import ConfigLoader, extract_doc_date, extract_doc_title, get_page_tokens, remove_fields

META_INDEX = "_meta.json"


def _normalize_retrieve_model(model: str) -> str:
    """Preserve supported Agents SDK prefixes and route other provider paths via LiteLLM."""
    passthrough_prefixes = ("litellm/", "openai/")
    if not model or "/" not in model:
        return model
    if model.startswith(passthrough_prefixes):
        return model
    return f"litellm/{model}"


class PageIndexClient:
    """
    A client for indexing and retrieving document content.
    Flow: index() -> get_document() / get_document_structure() / get_page_content()
    """
    def __init__(self, api_key: str = None, model: str = None, retrieve_model: str = None, workspace: str = None):
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
        elif not os.getenv("OPENAI_API_KEY") and os.getenv("CHATGPT_API_KEY"):
            os.environ["OPENAI_API_KEY"] = os.getenv("CHATGPT_API_KEY")
        self.workspace = Path(workspace).expanduser() if workspace else None
        overrides = {}
        if model:
            overrides["model"] = model
        if retrieve_model:
            overrides["retrieve_model"] = retrieve_model
        opt = ConfigLoader().load(overrides or None)
        self.model = opt.model
        self.retrieve_model = _normalize_retrieve_model(opt.retrieve_model or self.model)
        if self.workspace:
            self.workspace.mkdir(parents=True, exist_ok=True)
        self.documents = {}
        if self.workspace:
            self._load_workspace()

    def index(self, file_path: str) -> str:
        """Index a PDF document. Returns a document_id."""
        # Persist a canonical absolute path so workspace reloads do not
        # reinterpret caller-relative paths against the workspace directory.
        file_path = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        if os.path.splitext(file_path)[1].lower() != '.pdf':
            raise ValueError(f"Unsupported file format for: {file_path}")

        doc_id = str(uuid.uuid4())

        print(f"Indexing PDF: {file_path}")
        # Extract per-page text once, shared by structure generation (below)
        # and the 'pages' cache (so queries don't need the original PDF).
        # PyMuPDF handles Japanese font/CMap encodings PyPDF2 garbles; pages
        # with no text layer at all (scanned PDFs) fall back to OCR.
        page_list = get_page_tokens(file_path, model=self.model, ocr_fallback=True)
        pages = [{'page': i, 'content': text} for i, (text, _) in enumerate(page_list, 1)]

        # if_add_node_summary/if_add_doc_description/if_add_node_text are left
        # to config.yaml — PDF retrieval reads from the 'pages' cache above,
        # not from structure text, so node text isn't needed here regardless
        # of the config value.
        result = page_index(
            doc=file_path,
            page_list=page_list,
            model=self.model,
            if_add_node_id='yes',
        )
        doc_title = extract_doc_title(pages[0]['content'], model=self.model) if pages else ''
        doc_date = extract_doc_date(pages[0]['content'], model=self.model) if pages else ''
        if not doc_date:
            doc_date = datetime.fromtimestamp(os.path.getctime(file_path)).strftime('%Y-%m-%d')

        self.documents[doc_id] = {
            'id': doc_id,
            'type': 'pdf',
            'path': file_path,
            'doc_name': result.get('doc_name', ''),
            'doc_title': doc_title,
            'doc_date': doc_date,
            'doc_description': result.get('doc_description', ''),
            'page_count': len(pages),
            'structure': result['structure'],
            'pages': pages,
        }

        print(f"Indexing complete. Document ID: {doc_id}")
        if self.workspace:
            self._save_doc(doc_id)
        return doc_id

    @staticmethod
    def _make_meta_entry(doc: dict) -> dict:
        """Build a lightweight meta entry from a document dict."""
        return {
            'type': doc.get('type', ''),
            'doc_name': doc.get('doc_name', ''),
            'doc_title': doc.get('doc_title', ''),
            'doc_date': doc.get('doc_date', ''),
            'doc_description': doc.get('doc_description', ''),
            'path': doc.get('path', ''),
            'page_count': doc.get('page_count'),
        }

    @staticmethod
    def _read_json(path) -> dict | None:
        """Read a JSON file, returning None on any error."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Warning: missing {Path(path).name}")
            return None
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: corrupt {Path(path).name}: {e}")
            return None

    def _save_doc(self, doc_id: str):
        doc = self.documents[doc_id].copy()
        # Strip text from structure nodes — redundant with the 'pages' cache
        if doc.get('structure'):
            doc['structure'] = remove_fields(doc['structure'], fields=['text'])
        path = self.workspace / f"{doc_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        self._save_meta(doc_id, self._make_meta_entry(doc))
        # Drop heavy fields; will lazy-load on demand
        self.documents[doc_id].pop('structure', None)
        self.documents[doc_id].pop('pages', None)

    def delete_document(self, doc_id: str):
        """Remove a document's index cache (its JSON file and _meta.json entry).
        The source PDF in data/docs/ is left untouched — deleting the index is
        not the same as deleting the document, and re-indexing should stay cheap."""
        if doc_id not in self.documents:
            raise KeyError(f"Document {doc_id} not found")
        del self.documents[doc_id]
        if self.workspace:
            (self.workspace / f"{doc_id}.json").unlink(missing_ok=True)
            meta = self._read_meta() or {}
            meta.pop(doc_id, None)
            with open(self.workspace / META_INDEX, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

    def _rebuild_meta(self) -> dict:
        """Scan individual doc JSON files and return a meta dict."""
        meta = {}
        for path in self.workspace.glob("*.json"):
            if path.name == META_INDEX:
                continue
            doc = self._read_json(path)
            if doc and isinstance(doc, dict):
                meta[path.stem] = self._make_meta_entry(doc)
        return meta

    def _read_meta(self) -> dict | None:
        """Read and validate _meta.json, returning None on any corruption."""
        meta = self._read_json(self.workspace / META_INDEX)
        if meta is not None and not isinstance(meta, dict):
            print(f"Warning: {META_INDEX} is not a JSON object, ignoring")
            return None
        return meta

    def _save_meta(self, doc_id: str, entry: dict):
        meta = self._read_meta() or self._rebuild_meta()
        meta[doc_id] = entry
        meta_path = self.workspace / META_INDEX
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _load_workspace(self):
        meta = self._read_meta()
        if meta is None:
            meta = self._rebuild_meta()
            if meta:
                print(f"Loaded {len(meta)} document(s) from workspace (legacy mode).")
        for doc_id, entry in meta.items():
            doc = dict(entry, id=doc_id)
            if doc.get('path') and not os.path.isabs(doc['path']):
                doc['path'] = str((self.workspace / doc['path']).resolve())
            self.documents[doc_id] = doc

    def _ensure_doc_loaded(self, doc_id: str):
        """Load full document JSON on demand (structure, pages, etc.)."""
        doc = self.documents.get(doc_id)
        if not doc or doc.get('structure') is not None:
            return
        full = self._read_json(self.workspace / f"{doc_id}.json")
        if not full:
            return
        doc['structure'] = full.get('structure', [])
        if full.get('pages'):
            doc['pages'] = full['pages']

    def get_document(self, doc_id: str) -> str:
        """Return document metadata JSON."""
        return get_document(self.documents, doc_id)

    def get_document_structure(self, doc_id: str, titles_only: bool = False) -> str:
        """Return document tree structure JSON (without text fields)."""
        if self.workspace:
            self._ensure_doc_loaded(doc_id)
        return get_document_structure(self.documents, doc_id, titles_only=titles_only)

    def get_page_content(self, doc_id: str, pages: str) -> str:
        """Return page content for the given pages string (e.g. '5-7', '3,8', '12')."""
        if self.workspace:
            self._ensure_doc_loaded(doc_id)
        return get_page_content(self.documents, doc_id, pages)

    def search_document(self, doc_id: str, keyword: str, max_snippets: int = 10) -> str:
        """Search all page/line content for a keyword substring; returns matching pages + snippets."""
        if self.workspace:
            self._ensure_doc_loaded(doc_id)
        return search_document(self.documents, doc_id, keyword, max_snippets=max_snippets)
