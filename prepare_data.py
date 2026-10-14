"""Prepare either the public example corpus or an explicitly provided local corpus."""
import csv
import hashlib
import json
import shutil
from pathlib import Path
from backend.config import DATA, SAMPLE_CSV, settings


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    csv_target = DATA / "course_chunks.csv"
    if not csv_target.exists():
        shutil.copy2(SAMPLE_CSV, csv_target)
    rows = list(csv.DictReader(csv_target.open(encoding="utf-8-sig", newline="")))
    required = {"chunk_id", "chunk_text", "doc_id", "doc_name", "topic", "subtopic", "content_type", "suitable_questions", "chunk_order"}
    if not rows or not required.issubset(rows[0]):
        raise RuntimeError("Course CSV is empty or missing required metadata columns.")
    if len({r["chunk_id"] for r in rows}) != len(rows) or any(not r["chunk_id"] or not r["chunk_text"] for r in rows):
        raise RuntimeError("Course CSV contains duplicate IDs or empty texts.")
    model_path = settings()["embedding_path"]
    if not (model_path / "config.json").exists():
        from huggingface_hub import snapshot_download
        print("Downloading local BAAI/bge-small-zh-v1.5 model...")
        snapshot_download("BAAI/bge-small-zh-v1.5", local_dir=str(model_path),
                          allow_patterns=["*.json", "*.txt", "*.safetensors", "1_Pooling/*"])
    import chromadb
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(str(model_path), local_files_only=True)
    target = DATA / "chroma_db"
    client = chromadb.PersistentClient(path=str(target))
    valid = False
    try:
        coll = client.get_collection("ai_pm_course_chunks")
        ids = set(coll.get(include=[]) ["ids"])
        probe = coll.query(query_embeddings=[model.encode("RAG 是什么", normalize_embeddings=True).tolist()], n_results=1)
        valid = ids == {r["chunk_id"] for r in rows} and bool(probe["ids"][0])
    except Exception as exc:
        print("Copied index requires rebuild:", type(exc).__name__)
    if not valid:
        # A new versioned collection is built before replacing the incompatible new-app collection.
        name = "courses_rebuild_" + hashlib.sha256(csv_target.read_bytes()).hexdigest()[:12]
        try:
            coll = client.get_collection(name)
        except Exception:
            coll = client.create_collection(name, metadata={"hnsw:space": "cosine"})
        for start in range(0, len(rows), 32):
            batch = rows[start:start+32]
            vectors = model.encode([r["chunk_text"] for r in batch], normalize_embeddings=True, show_progress_bar=False).tolist()
            coll.upsert(ids=[r["chunk_id"] for r in batch], documents=[r["chunk_text"] for r in batch],
                        metadatas=[{k:v for k,v in r.items() if k not in {"chunk_id","chunk_text"}} for r in batch], embeddings=vectors)
            print(f"Built {min(start+32,len(rows))}/{len(rows)}")
        # Deletes only the copied collection in this application, never the original course DB.
        try:
            old = client.get_collection("ai_pm_course_chunks")
            old.modify(name="legacy_backup_"+hashlib.sha256(csv_target.read_bytes()).hexdigest()[:8])
        except Exception:
            pass
        coll.modify(name="ai_pm_course_chunks")
    print("Verified chunks:", coll.count(), "Courses:",len({r['doc_id'] for r in rows}))
    manifest={"chunks":len(rows),"courses":len({r['doc_id'] for r in rows}),"model":"BAAI/bge-small-zh-v1.5","dimension":512,"distance":"cosine",
              "data_kind":"public_sample" if hashlib.sha256(csv_target.read_bytes()).digest()==hashlib.sha256(SAMPLE_CSV.read_bytes()).digest() else "private_full",
              "csv_sha256":hashlib.sha256(csv_target.read_bytes()).hexdigest()}
    (DATA / "manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__ == "__main__":
    main()
