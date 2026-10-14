import csv
import hashlib
import json
import threading
from pathlib import Path
from .config import DATA, SAMPLE_CSV, EVAL_QUESTIONS, HISTORICAL_SUMMARY, settings


class Knowledge:
    def __init__(self):
        self.csv_path = DATA / "course_chunks.csv"
        source = self.csv_path if self.csv_path.exists() else SAMPLE_CSV
        self.rows = list(csv.DictReader(source.open(encoding="utf-8-sig", newline="")))
        self.by_id = {r["chunk_id"]: r for r in self.rows}
        self.version = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        self.data_kind = "public_sample" if source.read_bytes() == SAMPLE_CSV.read_bytes() else "private_full"
        self.model = None
        self.collection = None
        self.error = None
        self.loading = False
        self.lock = threading.RLock()

    def initialize(self):
        with self.lock:
            if self.model is not None and self.collection is not None:
                return
            self.loading = True
            try:
                import chromadb
                from sentence_transformers import SentenceTransformer
                path = settings()["embedding_path"]
                if not (path / "config.json").exists():
                    raise RuntimeError("本地 Embedding 模型尚未下载，请运行首次安装脚本。")
                self.model = SentenceTransformer(str(path), local_files_only=True)
                self.client = chromadb.PersistentClient(path=str(DATA / "chroma_db"))
                self.collection = self.client.get_collection("ai_pm_course_chunks")
                if self.collection.count() != len(self.rows):
                    raise RuntimeError("向量库条数与课程 CSV 不一致，请运行准备数据脚本。")
                self.error = None
            except Exception as exc:
                self.error = str(exc)
                self.model = None
                self.collection = None
            finally:
                self.loading = False

    def retrieve(self, query, top_k=5, doc_id=None):
        # A request arriving during cold start waits for the same cached initializer.
        # All callers invoke retrieval in worker threads, so the API loop stays responsive.
        if self.collection is None and (self.loading or self.error is None):
            self.initialize()
        if self.collection is None:
            raise RuntimeError(self.error or "课程模型正在加载，请稍候重试。")
        with self.lock:
            emb = self.model.encode(query, normalize_embeddings=True).tolist()
            kwargs = {"where": {"doc_id": doc_id}} if doc_id else {}
            result = self.collection.query(query_embeddings=[emb], n_results=top_k,
                                           include=["documents", "metadatas", "distances"], **kwargs)
        out = []
        for ident, text, meta, distance in zip(result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]):
            out.append({"chunk_id": ident, "chunk_text": text, **meta,
                        "distance": round(float(distance), 5), "similarity": round(1-float(distance), 5)})
        return out

    def stats(self):
        return {"courses": len({r["doc_id"] for r in self.rows}), "chunks": len(self.rows),
                "body_characters": sum(len(r["chunk_text"]) for r in self.rows),
                "data_kind": self.data_kind,
                "data_version": self.version, "embedding_model": "BAAI/bge-small-zh-v1.5",
                "dimension": 512, "distance": "cosine"}

    def courses(self):
        docs = {}
        for r in self.rows:
            d = docs.setdefault(r["doc_id"], {"doc_id": r["doc_id"], "doc_name": r["doc_name"], "count": 0, "topics": set()})
            d["count"] += 1
            d["topics"].add(r["topic"])
        return [{**d, "topics": sorted(d["topics"])} for d in docs.values()]

    def historical_evaluation(self):
        result = json.loads(HISTORICAL_SUMMARY.read_text(encoding="utf-8"))
        with EVAL_QUESTIONS.open(encoding="utf-8-sig", newline="") as file:
            result["current_test_count"] = sum(1 for _ in csv.DictReader(file))
        return result
