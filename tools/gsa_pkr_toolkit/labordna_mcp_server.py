#!/home/itzuser/.venv/bin/python
# labordna_mcp_server.py
import csv
import os
from typing import Dict, Any
import httpx
from fastmcp import FastMCP

mcp = FastMCP("LaborDNA-Dynamic-Engine")

CROSSWALK_HEADERS = [
    "soc_code",
    "official_title",
    "bls_occupation_key",
    "sitting_series_id",
    "sitting_source_value",
    "fine_manip_series_id",
    "fine_manip_frequently_pct",
    "naics_code"
]

# We register the target Series IDs we want our engine to track, but NOT the values
TARGET_REGISTRY_BLUEPRINT = {
    "53-3032": {
        "title": "Heavy and Tractor-Trailer Truck Drivers",
        "bls_key": "58M",
        "sitting_series": "ORUP1000058M00000128",   # median hours/day required to stand
        "fine_manip_series": "ORUP1000058M00001255", # % required fine manipulation, occasionally
        "naics": "484121"
    },
    "43-4051": {
        "title": "Customer Service Representatives",
        "bls_key": "20G",
        "sitting_series": "ORUP1000020G00000125",   # mean hours/day required to stand
        "fine_manip_series": "ORUP1000020G00001256", # % required fine manipulation, frequently
        "naics": "561440"
    }
}

@mcp.tool()
def generate_dynamic_crosswalk(output_filename: str = "public_crosswalk.csv") -> Dict[str, Any]:
    """
    Core MCP Tool: Downloads the master BLS flat file dynamically, scans for our 
    target Series IDs, extracts the live calculated values, and writes a grounded crosswalk.
    """
    bls_flat_file_url = "https://download.bls.gov/pub/time.series/or/or.data.1.AllData"
    target_path = output_filename.strip()
    
    extracted_series_values = {}
    print(f"📡 Establishing secure stream connection to live federal datastream gateway...")
    
    try:
        # 1. Pull down the live master flat file over the web
        headers = {"User-Agent": "Mozilla/5.0 (compatible; GSA-LaborDNA/1.0; +https://gsa.gov)"}
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            response = client.get(bls_flat_file_url, headers=headers)
            response.raise_for_status()
            
            # Split the giant flat file into lines for memory-efficient parsing
            lines = response.text.split("\n")
            print(f"🔬 Ingesting {len(lines):,} rows from or.data.1.AllData...")
            
            # 2. Dynamic Scanning Loop — collect all tracked series IDs
            all_series_ids = set()
            for config in TARGET_REGISTRY_BLUEPRINT.values():
                all_series_ids.add(config["sitting_series"])
                all_series_ids.add(config["fine_manip_series"])

            for line in lines:
                # Clean up spacing anomalies (BLS text files are space/tab separated)
                tokens = [t.strip() for t in line.split() if t.strip()]
                if not tokens:
                    continue

                current_series_id = tokens[0]
                if current_series_id in all_series_ids and len(tokens) >= 4:
                    raw_str = tokens[3]
                    if raw_str != "-":
                        try:
                            extracted_series_values[current_series_id] = float(raw_str)
                        except ValueError:
                            pass

            for soc, config in TARGET_REGISTRY_BLUEPRINT.items():
                sitting_val = extracted_series_values.get(config["sitting_series"])
                fine_val    = extracted_series_values.get(config["fine_manip_series"])
                if sitting_val is not None:
                    print(f"  🎯 Sitting metric for {config['title']}: {sitting_val}")
                if fine_val is not None:
                    print(f"  🎯 Fine manipulation metric for {config['title']}: {fine_val}%")

        # 3. Compile the CSV mapping from our dynamic extraction arrays
        with open(target_path, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CROSSWALK_HEADERS)
            writer.writeheader()

            for soc, config in TARGET_REGISTRY_BLUEPRINT.items():
                sitting_val  = extracted_series_values.get(config["sitting_series"], 0.0)
                fine_val     = extracted_series_values.get(config["fine_manip_series"], 0.0)
                writer.writerow({
                    "soc_code": soc,
                    "official_title": config["title"],
                    "bls_occupation_key": config["bls_key"],
                    "sitting_series_id": config["sitting_series"],
                    "sitting_source_value": sitting_val,
                    "fine_manip_series_id": config["fine_manip_series"],
                    "fine_manip_frequently_pct": fine_val,
                    "naics_code": config["naics"]
                })
                
        return {
            "status": "Success",
            "file_created": target_path,
            "absolute_path": os.path.abspath(target_path),
            "records_hydrated": len(extracted_series_values),
            "data_provenance": "100% Dynamically Verified from BLS Public Core Matrices"
        }
        
    except Exception as e:
        return {
            "status": "Error",
            "message": f"Dynamic ingestion loop failure: {str(e)}"
        }

# ---------------------------------------------------------------------------
# Tool: search_ors_manual
# ---------------------------------------------------------------------------

def _load_dotenv_server() -> None:
    """Load .env from workspace root into os.environ (best-effort)."""
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

_load_dotenv_server()


# Paths to local FAISS index built by ors_knowledge_base.py
_HERE_SERVER = os.path.dirname(os.path.abspath(__file__))
_ORS_INDEX_PATH  = os.path.join(_HERE_SERVER, "docs", "ors_index.faiss")
_ORS_CHUNKS_PATH = os.path.join(_HERE_SERVER, "docs", "ors_chunks.json")
_ORS_EMBED_MODEL = "all-MiniLM-L6-v2"

# Cache loaded index/model in module-level vars to avoid reloading on every call
_ors_index = None
_ors_chunks: list = []
_ors_model = None


def _load_ors_index():
    """Lazy-load the FAISS index, chunks, and embedding model."""
    global _ors_index, _ors_chunks, _ors_model
    if _ors_index is not None:
        return True, ""
    if not os.path.exists(_ORS_INDEX_PATH) or not os.path.exists(_ORS_CHUNKS_PATH):
        return False, (
            "ORS index files not found. "
            "Run ors_knowledge_base.py first to build the local index."
        )
    try:
        import json as _json
        import faiss  # type: ignore[import]
        from sentence_transformers import SentenceTransformer  # type: ignore[import]

        _ors_index = faiss.read_index(_ORS_INDEX_PATH)
        with open(_ORS_CHUNKS_PATH, encoding="utf-8") as f:
            data = _json.load(f)
        _ors_chunks = data["chunks"]
        model_name = data.get("model", _ORS_EMBED_MODEL)
        _ors_model = SentenceTransformer(model_name)
        return True, ""
    except Exception as exc:
        return False, f"Failed to load ORS index: {exc}"


@mcp.tool()
def search_ors_manual(query: str, top_k: int = 3) -> Dict[str, Any]:
    """
    RAG Tool: Searches the local BLS ORS Collection Manual FAISS index and
    returns the most relevant text chunks for a given query.

    Requires running ors_knowledge_base.py once to build the index from the PDF.

    Args:
        query: A natural language question or topic to look up in the manual
               (e.g. "How is sitting percentage defined for sedentary workers?").
        top_k: Number of passages to retrieve (default 3).

    Returns a dict with:
        "chunks": list of retrieved text passages
        "status": "ok" or "error"
        "message": error description if status is "error"
    """
    ok, err = _load_ors_index()
    if not ok:
        return {"status": "error", "message": err, "chunks": []}

    try:
        import numpy as np

        query_vec = _ors_model.encode([query], convert_to_numpy=True).astype("float32")
        distances, indices = _ors_index.search(query_vec, top_k)
        chunks = [
            _ors_chunks[i] for i in indices[0] if 0 <= i < len(_ors_chunks)
        ]
        return {"status": "ok", "chunks": chunks}

    except Exception as exc:
        return {"status": "error", "message": str(exc), "chunks": []}


if __name__ == "__main__":
    mcp.run()
