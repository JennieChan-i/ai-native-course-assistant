import json
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.agent import parse_json, bounded_context, citations, validate_citations, public_answer, AnswerStream


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path/"test.sqlite3", warm_model=False)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def test_knowledge_is_real(client):
    data=client.get("/api/courses").json()
    assert data["stats"]["chunks"]==17
    assert data["stats"]["courses"]==14
    assert data["stats"]["data_kind"]=="public_sample"
    assert data["stats"]["body_characters"]>1000
    rows=client.get("/api/chunks?doc_id=03&limit=2").json()
    assert len(rows["items"])==2
    ident=rows["items"][0]["chunk_id"]
    assert client.get(f"/api/chunks/{ident}").json()["chunk_text"]
    assert client.get("/api/chunks/NOT_REAL").status_code==404


def test_citations_only_verified():
    sources=[{"chunk_id":"RAG_03_001"}]
    answer, invalid=validate_citations("解释 [RAG_03_001] 和 [FAKE_03_999]",sources)
    assert invalid==["FAKE_03_999"]
    assert validate_citations("[chunk_id: RAG_03_001]",sources)[0]=="[RAG_03_001]"
    assert "FAKE" not in answer
    assert citations(answer,sources)==sources
    assert citations("没有引用",sources)==[]
    grouped, invalid=validate_citations("[RAG_03_001, FAKE_03_999]",sources)
    assert grouped=="[RAG_03_001][引用未验证]"
    assert invalid==["FAKE_03_999"]


def test_public_answer_hides_internal_source_labels():
    raw="结合当前提供的公开演示片段（SAMPLE_AIPM_001, SAMPLE_MCP_001），先学习需求拆解 [SAMPLE_AIPM_001]。"
    answer=public_answer(raw)
    assert answer=="结合现有课程资料，先学习需求拆解。"
    assert public_answer("由于当前知识库仅为公开演示片段，建议先说明学习目标。") == "现有课程资料的覆盖范围有限，建议先说明学习目标。"


def test_answer_stream_releases_clean_text_before_completion():
    raw="先理解 RAG。[SAMPLE_RAG_001]\n再做一次课程问答。[SAMPLE_MCP_001]"
    stream=AnswerStream()
    updates=[]
    for char in raw:
        update=stream.push(char)
        if update:
            updates.append(update)
            assert "SAMPLE_" not in "".join(updates)
    updates.append(stream.push("", final=True))
    assert len([part for part in updates if part])>=2
    assert "".join(updates)==public_answer(raw)


def test_context_budget():
    history=[{"role":"user","content":"旧话题"},{"role":"assistant","content":"RAG"*2000}]
    result=bounded_context(history,100)
    assert len(result)<=100
    assert "旧话题" not in result
    assert "RAG" in result


def test_json_validation():
    assert parse_json('```json\n{"intent":"course_qa"}\n```')["intent"]=="course_qa"
    with pytest.raises(ValueError):
        parse_json("[]")


def test_sse_context_feedback_and_persistence(app,client,monkeypatch):
    captured=[]
    async def completion(system,prompt,trace,json_mode=False):
        data=json.loads(prompt)
        captured.append(data)
        if "intent、confidence" in system:
            return {"intent":"course_qa","confidence":.9,"reason":"课程问题"}
        return {"query":"RAG 与微调的区别","needs_clarification":False}
    source={"chunk_id":"RAG_03_001","chunk_text":"真实来源测试契约","doc_id":"03","doc_name":"RAG","topic":"RAG","subtopic":"概念","similarity":.8}
    async def generate(prompt,trace,emit):
        await emit("delta",{"text":"RAG 根据外部资料回答 [RAG_03_001]"})
        return "RAG 根据外部资料回答 [RAG_03_001]"
    monkeypatch.setattr(app.state.agent,"completion",completion)
    monkeypatch.setattr(app.state.agent,"generate",generate)
    monkeypatch.setattr(app.state.knowledge,"retrieve",lambda *a:[source])
    first=client.post("/api/sessions").json()["id"]
    second=client.post("/api/sessions").json()["id"]
    res=client.post(f"/api/sessions/{first}/chat",json={"content":"RAG 是什么"})
    assert "event: done" in res.text
    assert "event: delta" in res.text
    client.post(f"/api/sessions/{first}/chat",json={"content":"它和微调有什么区别"})
    assert "RAG 是什么" in captured[-2]["history"]
    assert client.get(f"/api/sessions/{second}/messages").json()==[]
    messages=client.get(f"/api/sessions/{first}/messages").json()
    assert len(messages)==4
    ex=messages[-1]["execution"]
    assert ex["route"]["mode"]=="semantic"
    assert ex["status"]=="success" and len(ex["cited_sources"])==1
    feedback=client.post("/api/feedback",json={"message_id":messages[-1]["id"],"rating":"negative","category":"answer_error","note":"遗漏点"}).json()
    assert client.get("/api/feedback").json()[0]["user_input"]=="它和微调有什么区别"
    assert client.patch(f"/api/feedback/{feedback['id']}",json={"status":"resolved"}).status_code==422
    assert client.patch(f"/api/feedback/{feedback['id']}",json={"status":"resolved","fix_note":"已修改","retest":"已验证"}).status_code==200
    assert client.get("/api/dashboard").json()["success"]==2
    assert "RAG" in client.get(f"/api/sessions/{first}/export").text


def test_config_failure_is_logged(app,client,monkeypatch):
    async def fail(*args,**kwargs):
        raise RuntimeError("尚未配置百炼 API Key")
    monkeypatch.setattr(app.state.agent,"completion",fail)
    session=client.post("/api/sessions").json()["id"]
    res=client.post(f"/api/sessions/{session}/chat",json={"content":"RAG 是什么"})
    assert "event: error" in res.text
    log=client.get("/api/logs").json()[0]
    assert log["status"]=="error"
    assert log["payload"]["error_type"]=="RuntimeError"
    assert client.post(f"/api/sessions/{session}/chat",json={"content":"   "}).status_code==422


def test_invalid_router_clarifies(app,client,monkeypatch):
    async def bad(*args,**kwargs):
        raise ValueError("Invalid JSON")
    monkeypatch.setattr(app.state.agent,"completion",bad)
    session=client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{session}/chat",json={"content":"不明确的问题"})
    assert client.get("/api/logs").json()[0]["status"]=="need_clarification"


def test_historical_numbers_computed(client):
    result=client.get("/api/evaluations/historical").json()
    assert result["count"]==100
    assert result["doc_hit_rate"]==.91
    assert result["topic_hit_rate"]==.92
    assert len(client.get("/api/evaluations/boundaries").json())==12


@pytest.mark.parametrize("skill",["course_qa","learning_path","interview_practice","prd_review","resume_optimize"])
def test_manual_workflow_overrides_semantic_routing(app,client,monkeypatch,skill):
    async def completion(system,prompt,trace,json_mode=False):
        assert "intent、confidence" not in system, "Manual routing must skip the semantic classifier"
        return {"query":"RAG","needs_clarification":False}
    async def generate(prompt,trace,emit):
        data=json.loads(prompt)
        assert data["workflow"]==skill and data["route_mode"]=="manual"
        return "选定工作流完成"
    monkeypatch.setattr(app.state.agent,"completion",completion)
    monkeypatch.setattr(app.state.agent,"generate",generate)
    monkeypatch.setattr(app.state.knowledge,"retrieve",lambda *a:[])
    session=client.post("/api/sessions").json()["id"]
    response=client.post(f"/api/sessions/{session}/chat",json={"content":"帮我规划学习时间","skill":skill})
    assert "event: done" in response.text
    result=client.get(f"/api/sessions/{session}/messages").json()[-1]["execution"]
    assert result["status"]=="success"
    assert result["intent"]==skill
    assert result["requested_skill"]==skill
    assert result["route"]["mode"]=="manual" and result["route"]["confidence"] is None
    assert result["stages"][0]["name"]=="选择工作流"


def test_invalid_manual_workflow_rejected(client):
    session=client.post("/api/sessions").json()["id"]
    assert client.post(f"/api/sessions/{session}/chat",json={"content":"RAG","skill":"badcase_feedback"}).status_code==422


def test_badcase_examples_are_complete_and_not_real_feedback(client):
    before=client.get('/api/dashboard').json()
    samples=client.get('/api/badcase-examples').json()
    assert len(samples)==6
    for case in samples:
        assert case['is_simulated'] is True
        assert case['wrong_answer'] and case['cause'] and case['expected_answer']
        assert len(case['fix'])>=3 and len(case['regression'])>=3
        assert len(case['sources'])==len(case['evidence_ids'])
        for source in case['sources']:
            assert client.get('/api/chunks/'+source['chunk_id']).status_code==200
    assert client.get('/api/dashboard').json()==before
    assert client.get('/api/feedback').json()==[]
