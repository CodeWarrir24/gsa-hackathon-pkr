# ors_knowledge_base.py
"""
One-time setup script: chunks the ORS Collection Manual PDF, embeds each chunk
locally using sentence-transformers (no external vector store required), and
saves a FAISS index + chunks to disk.

Run once from the workspace root:
    venv/bin/python tools/gsa_pkr_toolkit/ors_knowledge_base.py

On success it creates:
    tools/gsa_pkr_toolkit/docs/ors_index.faiss
    tools/gsa_pkr_toolkit/docs/ors_chunks.json

No ORS_VECTOR_INDEX_ID needed — the search_ors_manual tool reads these files
directly using local FAISS search.

Requirements:
    pip install pypdf faiss-cpu sentence-transformers
"""

import json
import os
import sys

# ---------------------------------------------------------------------------
# Resolve .env (two levels up from this file = workspace root)
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    env_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    )
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val

_load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
PDF_PATH   = os.path.join(_HERE, "docs", "ors_collection_manual.pdf")
INDEX_PATH = os.path.join(_HERE, "docs", "ors_index.faiss")
CHUNKS_PATH = os.path.join(_HERE, "docs", "ors_chunks.json")

CHUNK_SIZE    = 512   # characters per chunk
CHUNK_OVERLAP = 64    # overlap between consecutive chunks
EMBED_MODEL   = "all-MiniLM-L6-v2"  # fast, lightweight, runs locally

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_deps() -> None:
    missing = []
    for pkg in ("pypdf", "faiss", "sentence_transformers"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        pkg_names = {"faiss": "faiss-cpu", "sentence_transformers": "sentence-transformers"}
        install = " ".join(pkg_names.get(p, p) for p in missing)
        print(f"ERROR: Missing dependencies. Install them with:")
        print(f"  venv/bin/pip install {install}")
        sys.exit(1)


def _extract_text(pdf_path: str) -> str:
    from pypdf import PdfReader  # type: ignore[import]
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"[Page {i + 1}]\n{text.strip()}")
    return "\n\n".join(pages)


def _chunk_text(text: str, size: int, overlap: int) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return [c.strip() for c in chunks if c.strip()]


def _embed_and_index(chunks: list[str], model_name: str):
    import faiss  # type: ignore[import]
    import numpy as np
    from sentence_transformers import SentenceTransformer  # type: ignore[import]

    print(f"  Loading embedding model '{model_name}' ...")
    model = SentenceTransformer(model_name)

    print(f"  Embedding {len(chunks)} chunks ...")
    embeddings = model.encode(chunks, show_progress_bar=True, convert_to_numpy=True)
    embeddings = embeddings.astype("float32")

    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)
    return index, dim


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not os.path.exists(PDF_PATH):
        print(f"ERROR: ORS manual PDF not found at:\n  {PDF_PATH}")
        print("Drop the file there and re-run this script.")
        sys.exit(1)

    _check_deps()

    # Step 1: Extract text from PDF
    print(f"\nExtracting text from '{os.path.basename(PDF_PATH)}' ...")
    text = _extract_text(PDF_PATH)
    print(f"  Extracted {len(text):,} characters across the document.")

    # Step 2: Chunk
    print(f"\nChunking (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}) ...")
    chunks = _chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
    print(f"  {len(chunks)} chunks created.")

    # Step 3: Embed + build FAISS index
    print("\nBuilding local FAISS vector index ...")
    index, dim = _embed_and_index(chunks, EMBED_MODEL)
    print(f"  Index built: {index.ntotal} vectors, dim={dim}")

    # Step 4: Save to disk
    import faiss  # type: ignore[import]
    faiss.write_index(index, INDEX_PATH)
    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        json.dump({"model": EMBED_MODEL, "chunks": chunks}, f, ensure_ascii=False, indent=2)

    print(f"\n  Saved index  -> {INDEX_PATH}")
    print(f"  Saved chunks -> {CHUNKS_PATH}")

    print("\n" + "=" * 60)
    print("Setup complete. The search_ors_manual tool will now use")
    print("local FAISS search — no ORS_VECTOR_INDEX_ID needed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
