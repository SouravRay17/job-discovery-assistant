"""
indexer.py — Embedding generation & BM25 indexing for normalized jobs.

Responsibilities:
  - Vector Store: Generates & caches embeddings for search_text in vector_store/
  - BM25 Store: Builds tokenized BM25 index in bm25_index/
  - Incremental Indexing: Only processes new/modified jobs (indexed_at IS NULL).
"""

import json
import os
import pickle
import re
from datetime import datetime, timezone
import numpy as np

from config import load_config
from db import get_connection, init_db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VECTOR_STORE_DIR = os.path.join(BASE_DIR, "vector_store")
BM25_INDEX_DIR = os.path.join(BASE_DIR, "bm25_index")

EMBEDDING_FILE = os.path.join(VECTOR_STORE_DIR, "embeddings.npz")
JOB_MAP_FILE = os.path.join(VECTOR_STORE_DIR, "job_map.json")
BM25_FILE = os.path.join(BM25_INDEX_DIR, "bm25_data.pkl")

DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"
_model_instance = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_embedding_model():
    """Lazy load sentence transformer embedding model."""
    global _model_instance
    if _model_instance is None:
        try:
            from sentence_transformers import SentenceTransformer
            print(f"  [*] Loading embedding model: {DEFAULT_EMBED_MODEL}...")
            _model_instance = SentenceTransformer(DEFAULT_EMBED_MODEL)
        except Exception as e:
            print(f"  [!] Failed to load SentenceTransformer ({e}). Using fallback embedding.")
            _model_instance = None
    return _model_instance


def compute_embeddings(texts: list[str]) -> np.ndarray:
    """Generate dense embeddings for a list of text strings."""
    model = get_embedding_model()
    if model is not None:
        embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return np.array(embeddings, dtype=np.float32)

    # Deterministic fallback hashing embedding (384 dimensions)
    vectors = []
    for text in texts:
        vec = np.zeros(384, dtype=np.float32)
        words = re.findall(r"\w+", text.lower())
        for word in words:
            h = hash(word) % 384
            vec[h] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        vectors.append(vec)
    return np.array(vectors, dtype=np.float32)


def tokenize_for_bm25(text: str) -> list[str]:
    """Tokenize and clean text for BM25 matching."""
    if not text:
        return []
    words = re.findall(r"[a-zA-Z0-9_\+#\.]+", text.lower())
    stop_words = {
        "and", "or", "the", "a", "an", "of", "in", "for", "to", "with", "at", "by", "from",
        "is", "are", "be", "this", "that", "it", "as", "on", "we", "you", "our", "your"
    }
    return [w for w in words if w not in stop_words and len(w) > 1]


def build_bm25_document(job: dict) -> list[str]:
    """Construct weighted token stream for BM25 indexing."""
    title = job.get("title") or ""
    req_skills = " ".join(json.loads(job.get("required_skills") or "[]"))
    pref_skills = " ".join(json.loads(job.get("preferred_skills") or "[]"))
    role_family = job.get("role_family") or ""
    domain = job.get("domain") or ""
    search_text = job.get("search_text") or ""

    # Title & Required skills repeated for higher BM25 term frequency weighting
    weighted_text = f"{title} {title} {title} {req_skills} {req_skills} {role_family} {role_family} {domain} {pref_skills} {search_text}"
    return tokenize_for_bm25(weighted_text)


def index_jobs():
    """Incrementally compute embeddings and update BM25 index for normalized jobs."""
    init_db()
    os.makedirs(VECTOR_STORE_DIR, exist_ok=True)
    os.makedirs(BM25_INDEX_DIR, exist_ok=True)

    conn = get_connection()
    try:
        # Load all normalized jobs
        cursor = conn.execute(
            "SELECT source, id, title, company, location, role_family, domain, "
            "required_skills, preferred_skills, search_text, indexed_at "
            "FROM jobs WHERE normalized_at IS NOT NULL"
        )
        all_jobs = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not all_jobs:
        print("[*] No normalized jobs available for indexing. Run normalizer.py first.")
        return

    unindexed_jobs = [j for j in all_jobs if j.get("indexed_at") is None]
    print(f"\n{'='*60}\nJob Indexer -- Total Jobs: {len(all_jobs)} | New to Index: {len(unindexed_jobs)}\n{'='*60}")

    # 1. Update Vector Store
    existing_vectors = {}
    if os.path.exists(EMBEDDING_FILE) and os.path.exists(JOB_MAP_FILE):
        try:
            data = np.load(EMBEDDING_FILE)
            with open(JOB_MAP_FILE, "r", encoding="utf-8") as f:
                key_map = json.load(f)
            matrix = data["embeddings"]
            for idx, key in enumerate(key_map):
                existing_vectors[key] = matrix[idx]
        except Exception as e:
            print(f"  [!] Re-building vector cache due to load error: {e}")
            existing_vectors = {}

    # Embed unindexed jobs
    if unindexed_jobs:
        keys_to_embed = [f"{j['source']}::{j['id']}" for j in unindexed_jobs]
        texts_to_embed = [j["search_text"] or j["title"] for j in unindexed_jobs]
        print(f"  --> Computing dense embeddings for {len(texts_to_embed)} new jobs...")
        new_matrix = compute_embeddings(texts_to_embed)
        for key, vec in zip(keys_to_embed, new_matrix):
            existing_vectors[key] = vec

    # Save combined vector store
    all_keys = [f"{j['source']}::{j['id']}" for j in all_jobs if f"{j['source']}::{j['id']}" in existing_vectors]
    if all_keys:
        all_matrix = np.array([existing_vectors[k] for k in all_keys], dtype=np.float32)
        np.savez_compressed(EMBEDDING_FILE, embeddings=all_matrix)
        with open(JOB_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(all_keys, f)
        print(f"  [OK] Vector index saved with {len(all_keys)} embeddings.")

    # 2. Build & Save BM25 Index
    try:
        from rank_bm25 import BM25Okapi
        bm25_corpus = [build_bm25_document(j) for j in all_jobs]
        bm25_model = BM25Okapi(bm25_corpus)
        bm25_data = {
            "model": bm25_model,
            "keys": [f"{j['source']}::{j['id']}" for j in all_jobs],
            "corpus_size": len(all_jobs),
            "updated_at": now_iso()
        }
        with open(BM25_FILE, "wb") as f:
            pickle.dump(bm25_data, f)
        print(f"  [OK] BM25 keyword index saved with {len(all_jobs)} documents.")
    except Exception as e:
        print(f"  [!] BM25 indexing error: {e}")

    # 3. Mark newly indexed jobs in DB
    if unindexed_jobs:
        conn = get_connection()
        try:
            now_str = now_iso()
            for j in unindexed_jobs:
                conn.execute(
                    "UPDATE jobs SET indexed_at = ? WHERE source = ? AND id = ?",
                    (now_str, j["source"], j["id"])
                )
            conn.commit()
        finally:
            conn.close()
        print(f"  [OK] Marked {len(unindexed_jobs)} jobs as indexed in jobs.db.\n")


if __name__ == "__main__":
    index_jobs()
