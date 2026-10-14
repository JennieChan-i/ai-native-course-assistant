import asyncio
import csv
import io
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .config import DATA, ROOT, EVAL_QUESTIONS, settings
from .storage import Store, uid, now
from .knowledge import Knowledge
from .agent import Agent, friendly_error, bounded_context, public_answer
from .boundary_cases import CASES
from .badcase_examples import examples as badcase_examples


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    skill: Literal["course_qa", "learning_path", "interview_practice", "prd_review", "resume_optimize"] | None = None


class FeedbackIn(BaseModel):
    message_id: str
    rating: Literal["positive", "negative"]
    category: Literal["retrieval_issue", "source_mismatch", "hallucination", "low_helpfulness", "answer_error", "other"] = "other"
    note: str = Field(default="", max_length=3000)


class FeedbackUpdate(BaseModel):
    status: Literal["pending", "analyzing", "resolved"]
    analysis: str = Field(default="", max_length=5000)
    fix_note: str = Field(default="", max_length=5000)
    retest: str = Field(default="", max_length=5000)


class EvaluationIn(BaseModel):
    kind: Literal["retrieval", "boundary"] = "retrieval"
    top_k: int = Field(default=5, ge=1, le=10)


def retrieval_questions():
    with EVAL_QUESTIONS.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def create_app(store_path=None, warm_model=True):
    store = Store(store_path or DATA / "workspace.sqlite3")
    knowledge = Knowledge()
    agent = Agent(store, knowledge)
    tasks, active = set(), set()

    def spawn(coro):
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return task

    @asynccontextmanager
    async def lifespan(app):
        for row in store.query("SELECT id,payload FROM executions WHERE status='running'"):
            obj = json.loads(row["payload"])
            obj.update(status="error", error_message="上次运行被中断。", error_type="Interrupted")
            store.save_execution(obj)
        for row in store.query("SELECT id,payload FROM evaluations WHERE status='running'"):
            obj = json.loads(row["payload"])
            obj.update(status="error", error="上次评测被中断，可重新运行。")
            store.save_json("evaluations", row["id"], obj)
        if warm_model:
            spawn(asyncio.to_thread(knowledge.initialize))
        yield
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*list(tasks), return_exceptions=True)

    app = FastAPI(title="AI Native 课程智能学习助手", lifespan=lifespan)
    app.state.store, app.state.knowledge, app.state.agent = store, knowledge, agent

    def session_or_404(ident):
        if not store.one("SELECT id FROM sessions WHERE id=?", (ident,)):
            raise HTTPException(404, "会话不存在，请新建会话。")

    @app.get("/api/health")
    def health():
        cfg = settings()
        return {"api_configured": bool(cfg["api_key"]), "model": cfg["model"],
                "retrieval_ready": knowledge.collection is not None, "loading": knowledge.loading,
                "retrieval_error": knowledge.error, "database_ready": True, "stats": knowledge.stats(),
                "env_file": ".env"}

    @app.post("/api/health/model")
    async def check_model():
        trace = {}
        try:
            await agent.completion("只回答：连接正常。", "连接检查", trace)
            return {"ok": True, "model": settings()["model"], "calls": trace["model_calls"]}
        except Exception as exc:
            raise HTTPException(503, friendly_error(exc))

    @app.post("/api/sessions")
    def create_session():
        return store.create_session()

    @app.get("/api/sessions")
    def sessions():
        return store.query("SELECT * FROM sessions WHERE title NOT LIKE '边界评测%' ORDER BY rowid DESC")

    @app.get("/api/sessions/{ident}/messages")
    def messages(ident: str):
        session_or_404(ident)
        rows = store.messages(ident)
        for row in rows:
            if row["role"] == "assistant":
                row["content"] = public_answer(row["content"])
        return rows

    @app.get("/api/sessions/{ident}/export")
    def export_session(ident: str):
        session_or_404(ident)
        text = "# 学习对话\n\n"+"\n\n".join(f"## {'用户' if m['role']=='user' else '助手'}\n\n{public_answer(m['content']) if m['role']=='assistant' else m['content']}" for m in store.messages(ident))
        return Response(text, media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="conversation.md"'})

    @app.post("/api/sessions/{ident}/chat")
    async def chat(ident: str, body: MessageIn):
        session_or_404(ident)
        if not body.content.strip():
            raise HTTPException(422, "请输入问题。")
        if ident in active:
            raise HTTPException(409, "该会话已有任务执行中，请等待完成。")
        active.add(ident)
        queue = asyncio.Queue()

        async def emit(event, data):
            await queue.put((event, data))

        async def work():
            try:
                await agent.run(ident, body.content.strip(), emit, selected_intent=body.skill)
            except Exception as exc:
                await emit("error", {"message": friendly_error(exc)})
            finally:
                active.discard(ident)
                await queue.put(None)

        spawn(work())

        async def events():
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if item is None:
                    break
                event, data = item
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/courses")
    def courses():
        return {"courses": knowledge.courses(), "stats": knowledge.stats()}

    @app.get("/api/chunks")
    def chunks(doc_id: str = "", topic: str = "", q: str = "", offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
        rows = [r for r in knowledge.rows if (not doc_id or r["doc_id"] == doc_id) and
                (not topic or r["topic"] == topic) and (not q or q.casefold() in (r["chunk_text"]+r["subtopic"]).casefold())]
        return {"total": len(rows), "items": rows[offset:offset+limit]}

    @app.get("/api/chunks/{ident}")
    def chunk(ident: str):
        if ident not in knowledge.by_id:
            raise HTTPException(404, "课程切片不存在。")
        return knowledge.by_id[ident]

    @app.get("/api/search")
    async def search(q: str = Query(min_length=1, max_length=2000), top_k: int = Query(5, ge=1, le=10), doc_id: str = ""):
        try:
            start = time.perf_counter()
            rows = await asyncio.to_thread(knowledge.retrieve, q, top_k, doc_id or None)
            return {"query": q, "items": rows, "duration_ms": round((time.perf_counter()-start)*1000)}
        except Exception as exc:
            raise HTTPException(503, friendly_error(exc))

    @app.post("/api/feedback")
    def feedback(body: FeedbackIn):
        message = store.one("SELECT * FROM messages WHERE id=? AND role='assistant'", (body.message_id,))
        if not message:
            raise HTTPException(404, "回答不存在。")
        ident = uid()
        stamp = now()
        store.execute("INSERT INTO feedback VALUES(?,?,?,?,?,?,?,?,?,?,?)", (ident, body.message_id, body.rating, body.category,
                      body.note, "pending" if body.rating=="negative" else "resolved", "", "", "", stamp, stamp))
        return {"id": ident, "message": "已记录反馈"}

    @app.get("/api/feedback")
    def feedback_list(q: str = "", status: str = "", category: str = ""):
        return store.query("""SELECT f.*,m.content AS answer,m.session_id,e.user_input,e.payload AS execution_payload
        FROM feedback f JOIN messages m ON f.message_id=m.id JOIN sessions s ON s.id=m.session_id LEFT JOIN executions e ON m.execution_id=e.id
        WHERE f.rating='negative' AND s.title NOT LIKE '边界评测%' AND (?='' OR f.status=?) AND (?='' OR f.category=?)
        AND (?='' OR f.note LIKE ? OR e.user_input LIKE ?) ORDER BY f.rowid DESC""",
        (status,status,category,category,q,f"%{q}%",f"%{q}%"))

    @app.get("/api/badcase-examples")
    def example_cases():
        return badcase_examples(knowledge)

    @app.patch("/api/feedback/{ident}")
    def update_feedback(ident: str, body: FeedbackUpdate):
        if not store.one("SELECT id FROM feedback WHERE id=?", (ident,)):
            raise HTTPException(404, "反馈不存在。")
        if body.status == "resolved" and (not body.fix_note.strip() or not body.retest.strip()):
            raise HTTPException(422, "标记已解决前请填写修复说明和复测记录。")
        store.execute("UPDATE feedback SET status=?,analysis=?,fix_note=?,retest=?,updated_at=? WHERE id=?", (
            body.status,body.analysis,body.fix_note,body.retest,now(),ident))
        return {"ok": True}

    def logs_data(intent="", status="", since="", until=""):
        return store.query("SELECT * FROM executions WHERE is_eval=0 AND (?='' OR intent=?) AND (?='' OR status=?) AND (?='' OR created_at>=?) AND (?='' OR created_at<=?) ORDER BY rowid DESC LIMIT 1000", (intent,intent,status,status,since,since,until,until))

    @app.get("/api/logs")
    def logs(intent: str="", status: str="", since: str="", until: str=""):
        return [{**r, "payload": json.loads(r["payload"])} for r in logs_data(intent,status,since,until)]

    @app.get("/api/logs/export")
    def export_logs(intent: str="", status: str="", since: str="", until: str=""):
        rows = logs_data(intent,status,since,until)
        output = io.StringIO()
        fields = ["id","created_at","user_input","intent","status","duration_ms","has_sources","session_id"]
        writer = csv.DictWriter(output, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return Response("\ufeff"+output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="agent_logs.csv"'})

    @app.get("/api/dashboard")
    def dashboard():
        rows = store.query("SELECT intent,status,duration_ms,has_sources FROM executions WHERE is_eval=0")
        finished = [r for r in rows if r["status"] in {"success","error","need_clarification"}]
        successful = [r for r in finished if r["status"]=="success"]
        qa = [r for r in successful if r["intent"]=="course_qa"]
        durations = sorted(r["duration_ms"] for r in finished)
        def groups(field):
            values = sorted({r[field] for r in rows})
            return [{"name": v, "value": sum(r[field]==v for r in rows)} for v in values]
        return {"total": len(rows), "finished": len(finished), "success": len(successful),
                "success_rate": len(successful)/len(finished) if finished else None,
                "qa_cited": sum(r["has_sources"] for r in qa), "qa_total": len(qa),
                "p50_ms": durations[len(durations)//2] if durations else None,
                "p95_ms": durations[min(len(durations)-1, int(len(durations)*.95))] if durations else None,
                "intents": groups("intent"), "statuses": groups("status"),
                "feedback": store.query("SELECT f.category AS name,COUNT(*) AS value FROM feedback f JOIN messages m ON m.id=f.message_id JOIN sessions s ON s.id=m.session_id WHERE f.rating='negative' AND s.title NOT LIKE '边界评测%' GROUP BY f.category"),
                "notice": "技术成功表示流程完成，不等于回答正确。评测调用与历史日志不计入当前运行统计。"}

    @app.get("/api/evaluations/historical")
    def historical():
        return knowledge.historical_evaluation()

    @app.get("/api/evaluations/boundaries")
    def boundaries():
        return CASES

    @app.get("/api/evaluations")
    def evaluations():
        return [json.loads(r["payload"]) for r in store.query("SELECT payload FROM evaluations ORDER BY rowid DESC")]

    @app.get("/api/evaluations/{ident}")
    def evaluation(ident: str):
        obj = store.load_json("evaluations",ident)
        if not obj:
            raise HTTPException(404,"评测不存在。")
        return obj

    async def run_evaluation(obj):
        try:
            if obj["kind"]=="retrieval":
                questions=retrieval_questions()
                for q in questions:
                    hits=await asyncio.to_thread(knowledge.retrieve,q["test_question"],obj["top_k"])
                    obj["results"].append({"question_id":q["question_id"],"question":q["test_question"],
                        "expected_doc_id":q["expected_doc_id"],"expected_topic":q["expected_topic"],
                        "doc_hit":any(h["doc_id"]==q["expected_doc_id"] for h in hits),
                        "topic_hit":any(h["topic"]==q["expected_topic"] for h in hits),
                        "source_chunk_hit":any(h["chunk_id"]==q["source_chunk_id"] for h in hits),"results":hits})
                    obj["progress"]=len(obj["results"])
                    store.save_json("evaluations",obj["id"],obj)
                n=len(obj["results"])
                obj["metrics"]={f"{k}_rate":sum(r[k] for r in obj["results"])/n for k in ("doc_hit","topic_hit","source_chunk_hit")}
            else:
                async def ignore(event,data):
                    pass
                for case in CASES:
                    ses=store.create_session("边界评测 · "+case["id"])
                    for previous in case.get("history",[]):
                        store.add_message(ses["id"],"assistant",previous)
                    result=await agent.run(ses["id"],case["input"],ignore,is_eval=True)
                    obj["results"].append({**case,"execution":result,"quality_status":"待人工评审"})
                    obj["progress"]=len(obj["results"])
                    store.save_json("evaluations",obj["id"],obj)
            obj["status"]="complete"
        except Exception as exc:
            obj.update(status="error",error=friendly_error(exc))
        finally:
            obj["finished_at"]=now()
            store.save_json("evaluations",obj["id"],obj)

    @app.post("/api/evaluations")
    async def new_evaluation(body: EvaluationIn):
        if store.one("SELECT id FROM evaluations WHERE status='running'"):
            raise HTTPException(409,"已有评测运行中，请等待完成。")
        if body.kind=="boundary" and not settings()["api_key"]:
            raise HTTPException(422,"边界测试会真实调用模型，请先配置 API Key。")
        if knowledge.collection is None:
            raise HTTPException(503,"Embedding 模型或向量库尚未就绪。")
        obj={"id":uid(),"kind":body.kind,"top_k":body.top_k,"created_at":now(),"status":"running",
             "progress":0,"total":len(retrieval_questions()) if body.kind=="retrieval" else len(CASES),"results":[],
             "data_version":knowledge.version,"embedding_model":"BAAI/bge-small-zh-v1.5","llm_model":settings()["model"] if body.kind=="boundary" else None}
        store.save_json("evaluations",obj["id"],obj)
        spawn(run_evaluation(obj))
        return obj

    dist=ROOT/"frontend/dist"
    if (dist/"assets").exists():
        app.mount("/assets",StaticFiles(directory=dist/"assets"),name="assets")

    @app.get("/")
    def index():
        if not (dist/"index.html").exists():
            return Response("前端尚未构建，请运行首次安装脚本。",status_code=503)
        return FileResponse(dist/"index.html")
    return app


app=create_app()
