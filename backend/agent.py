import asyncio
import json
import re
import time
import hashlib
from pathlib import Path
from openai import AsyncOpenAI, AuthenticationError, RateLimitError, APITimeoutError, APIConnectionError
from .config import settings
from .prompts import INTENTS, ROUTER, REWRITE, SYSTEM, SKILLS
from .storage import now, uid


def friendly_error(exc):
    if isinstance(exc, AuthenticationError):
        return "百炼鉴权失败，请检查本机 .env 中的 API Key 和服务地址。"
    if isinstance(exc, RateLimitError):
        return "模型服务限流或额度不足，请检查百炼额度后重试。"
    if isinstance(exc, APITimeoutError):
        return "模型请求超时，请检查网络后重试。"
    if isinstance(exc, APIConnectionError):
        return "无法连接百炼服务，请检查网络和服务地址。"
    if isinstance(exc, (ValueError, RuntimeError)):
        return str(exc)[:300]
    return "执行失败，请在日志中查看错误类型，并检查环境后重试。"


def parse_json(content):
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError("模型结构化结果必须为对象。")
    return result


def bounded_context(messages, budget=10000):
    parts = []
    remaining = budget
    for m in reversed(messages[-12:]):
        content = (public_answer(m["content"]) if m["role"] == "assistant" else m["content"])[:5000]
        text = f"{m['role']}: {content}"
        if len(text) > remaining:
            text = text[:remaining]
        parts.append(text)
        remaining -= len(text)
        if remaining <= 0:
            break
    return "\n".join(reversed(parts))


def citations(answer, sources):
    # References are metadata-backed and must actually appear in the answer.
    return [s for s in sources if f"[{s['chunk_id']}]" in answer]


def validate_citations(answer, sources):
    allowed = {s["chunk_id"] for s in sources}
    answer = re.sub(r"\[chunk_id\s*:\s*([A-Z][A-Z0-9_]+_\d+)\]", r"[\1]", answer)
    # Normalize comma-grouped references into separately verifiable/clickable sources.
    group = r"\[((?:[A-Z][A-Z0-9_]+_\d+)(?:\s*[,，]\s*[A-Z][A-Z0-9_]+_\d+)+)\]"
    answer = re.sub(group, lambda m: "".join(f"[{p.strip()}]" for p in re.split(r"[,，]", m.group(1))), answer)
    pattern = r"\[([A-Z][A-Z0-9_]+_\d+)\]"
    unknown = sorted({m for m in re.findall(pattern, answer) if m not in allowed})
    cleaned = re.sub(pattern, lambda m: m.group(0) if m.group(1) in allowed else "[引用未验证]", answer)
    return cleaned, unknown


def public_answer(answer):
    """Keep internal source identifiers and dataset labels out of user-facing prose."""
    answer = re.sub(r"[（(]\s*(?:[A-Z][A-Z0-9_]*_\d+\s*[,，、]?\s*)+[）)]", "", answer)
    answer = re.sub(r"\[(?:chunk_id\s*:\s*)?[A-Z][A-Z0-9_]*_\d+\]", "", answer)
    answer = answer.replace("[引用未验证]", "")
    answer = re.sub(r"\b[A-Z][A-Z0-9_]*_\d+\b", "", answer)
    answer = re.sub(r"由于当前知识库仅为公开演示片段", "现有课程资料的覆盖范围有限", answer)
    answer = re.sub(r"本计划仅基于当前检索到的\d+个知识片段制定，?\s*不代表完整课程体系", "现有课程资料可能无法覆盖全部内容，建议根据学习进度调整计划", answer)
    answer = re.sub(r"当前(?:提供的|检索到的)?\s*\d*\s*个?公开演示片段", "现有课程资料", answer)
    answer = re.sub(r"当前检索到的\d+个知识片段", "现有课程资料", answer)
    answer = answer.replace("公开演示片段", "课程资料").replace("公开示例知识库", "课程资料")
    answer = answer.replace("公开示例：", "")
    answer = re.sub(r"本计划仅基于现有课程资料制定，?\s*\*{0,2}不代表完整课程体系\*{0,2}", "可根据你的基础和学习进度调整计划", answer)
    answer = answer.replace("验收标准严格依据片段中的方法论定义", "每周通过实操任务检查学习效果")
    answer = re.sub(r"[（(]\s*[,，、\s]+[）)]", "", answer)
    answer = re.sub(r"[ \t]+([，。；：、,.!?！？])", r"\1", answer)
    answer = re.sub(r"[ \t]{2,}", " ", answer)
    return re.sub(r"\n{3,}", "\n\n", answer).strip()


class AnswerStream:
    """Release completed, cleaned clauses while retaining unfinished model output."""

    boundaries = "。！？；\n"

    def __init__(self):
        self.raw = ""
        self.visible = ""

    def push(self, delta, final=False):
        self.raw += delta
        if final:
            candidate = public_answer(self.raw)
        else:
            end = max(self.raw.rfind(mark) for mark in self.boundaries)
            if end < 0:
                return ""
            candidate = public_answer(self.raw[:end + 1])
        if not candidate.startswith(self.visible):
            return ""
        update = candidate[len(self.visible):]
        self.visible = candidate
        return update


def feedback_type(text):
    rules = [("retrieval_issue", ["检索", "召回", "不相关"]), ("source_mismatch", ["资料", "来源"]),
             ("hallucination", ["胡编", "幻觉", "编造"]), ("low_helpfulness", ["没帮助", "不满意"])]
    return next((name for name, terms in rules if any(t in text for t in terms)), "answer_error")


class Agent:
    def __init__(self, store, knowledge):
        self.store, self.knowledge = store, knowledge

    def model_options(self, cfg):
        if cfg["model"].startswith("qwen3") and "thinking" not in cfg["model"]:
            return {"extra_body": {"enable_thinking": cfg["enable_thinking"], "preserve_thinking": False}}
        return {}

    async def completion(self, system, prompt, trace, json_mode=False):
        cfg = settings()
        if not cfg["api_key"]:
            raise RuntimeError("尚未配置百炼 API Key。请在本仓库 .env 中填写 DASHSCOPE_API_KEY，保存后重试。")
        start = time.perf_counter()
        async with AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"], timeout=60, max_retries=1) as client:
            kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
            result = await client.chat.completions.create(model=cfg["model"], messages=[
                {"role": "system", "content": system}, {"role": "user", "content": prompt}],
                temperature=0.1 if json_mode else 0.3, max_tokens=3500, **kwargs, **self.model_options(cfg))
        trace.setdefault("model_calls", []).append({"model": cfg["model"], "duration_ms": round((time.perf_counter()-start)*1000),
            "usage": result.usage.model_dump() if result.usage else None})
        text = result.choices[0].message.content or ""
        if not text.strip():
            raise ValueError("模型返回空内容，请重试。")
        return parse_json(text) if json_mode else text

    async def generate(self, prompt, trace, emit):
        cfg = settings()
        if not cfg["api_key"]:
            raise RuntimeError("尚未配置百炼 API Key，请在本机 .env 填写后重试。")
        start = time.perf_counter()
        answer, usage = "", None
        visible_stream = AnswerStream()
        async with AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"], timeout=60, max_retries=1) as client:
            stream = await client.chat.completions.create(model=cfg["model"], messages=[
                {"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=4000, stream=True, stream_options={"include_usage": True}, **self.model_options(cfg))
            async for part in stream:
                if part.usage:
                    usage = part.usage.model_dump()
                if part.choices:
                    delta = part.choices[0].delta.content or ""
                    answer += delta
                    visible = visible_stream.push(delta)
                    if visible:
                        await emit("delta", {"text": visible})
        trace.setdefault("model_calls", []).append({"model": cfg["model"], "duration_ms": round((time.perf_counter()-start)*1000), "usage": usage})
        if not answer.strip():
            raise ValueError("模型返回空内容，请重试。")
        tail = visible_stream.push("", final=True)
        if tail:
            await emit("delta", {"text": tail})
        return answer

    async def run(self, session_id, user_input, emit, is_eval=False, selected_intent=None):
        start = time.perf_counter()
        history = self.store.messages(session_id)
        context = bounded_context(history)
        trace = {"id": uid(), "session_id": session_id, "user_input": user_input, "created_at": now(),
                 "status": "running", "stages": [], "sources": [], "cited_sources": [], "model_calls": [], "is_eval": is_eval,
                 "data_version": self.knowledge.version, "data_kind": self.knowledge.data_kind, "requested_skill": selected_intent,
                 "prompt_version": hashlib.sha256(Path(__file__).with_name("prompts.py").read_bytes()).hexdigest()[:12]}
        self.store.add_message(session_id, "user", user_input)
        self.store.execute("UPDATE sessions SET title=? WHERE id=? AND title='新对话'", (user_input[:36], session_id))
        self.store.save_execution(trace)

        async def stage(name, detail=""):
            item = {"name": name, "detail": detail, "elapsed_ms": round((time.perf_counter()-start)*1000)}
            trace["stages"].append(item)
            await emit("stage", item)

        try:
            if selected_intent is not None:
                if selected_intent not in SKILLS:
                    raise ValueError("请选择支持的工作流标签。")
                await stage("选择工作流", "用户标签指定 · "+INTENTS[selected_intent])
                route = {"intent": selected_intent, "reason": "用户通过功能标签指定工作流："+INTENTS[selected_intent], "mode": "manual"}
            else:
                await stage("意图识别", "结合当前问题与会话上下文")
                try:
                    route = await self.completion(ROUTER, json.dumps({"history": context, "input": user_input}, ensure_ascii=False), trace, True)
                except (ValueError, json.JSONDecodeError):
                    route = {"intent": "unknown", "confidence": 0, "reason": "模型意图结构无法解析，请补充任务目标。"}
            intent = route.get("intent", "unknown")
            if intent not in INTENTS:
                intent = "unknown"
            trace["intent"] = intent
            try:
                confidence = min(1, max(0, float(route.get("confidence", 0))))
            except (ValueError, TypeError):
                confidence = 0.0
            trace["route"] = {"intent": intent, "skill": intent+"_skill", "reason": str(route.get("reason", "")),
                              "mode": "manual" if selected_intent else "semantic", "confidence": None if selected_intent else confidence}
            await emit("route", trace["route"])
            if intent == "unknown":
                answer = "请补充你的目标：是课程知识问答、学习计划、面试练习、PRD 点评，还是简历优化？"
                trace["status"] = "need_clarification"
                await emit("delta", {"text": answer})
            elif intent == "badcase_feedback":
                last = next((m for m in reversed(history) if m["role"] == "assistant"), None)
                if not last:
                    answer = "你希望反馈哪条回答？请先完成一次问答，或在历史回答下点击「有问题」。"
                    trace["status"] = "need_clarification"
                else:
                    ident = uid()
                    self.store.execute("INSERT INTO feedback VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                        ident, last["id"], "negative", feedback_type(user_input), user_input, "pending", "", "", "", now(), now()))
                    answer = "已记录这条回答的反馈。请到「反馈与 Badcase」查看分析与处理进度。"
                    trace["feedback_id"] = ident
                    trace["status"] = "success"
                await emit("delta", {"text": answer})
            else:
                await stage("Query 改写", "保守纠错与指代补全")
                if intent == "course_qa":
                    rewrite = await self.completion(REWRITE, json.dumps({"history": context, "input": user_input}, ensure_ascii=False), trace, True)
                else:
                    # Document review, planning and resume input may be incomplete on purpose.
                    # Retrieve supporting concepts without turning missing business details into a blocking question.
                    rewrite = {"query": user_input[:1500], "needs_clarification": False}
                trace["rewritten_query"] = str(rewrite.get("query", user_input))
                if rewrite.get("needs_clarification"):
                    answer = str(rewrite.get("reason") or "请确认你所指的术语或上下文。")
                    trace["status"] = "need_clarification"
                    await emit("delta", {"text": answer})
                else:
                    await stage("课程检索", "本地 bge-small-zh-v1.5 → Chroma · Top-5")
                    sources = await asyncio.to_thread(self.knowledge.retrieve, trace["rewritten_query"], 5)
                    trace["sources"] = sources
                    await emit("sources", {"sources": sources, "rewritten_query": trace["rewritten_query"]})
                    await stage("回答生成", INTENTS[intent]+" · "+settings()["model"])
                    task = SKILLS[intent]
                    if self.knowledge.data_kind == "public_sample":
                        task += "\n只依据当前可用课程资料回答；资料不支持的内容须说明边界。不要宣称资料覆盖全部课程，也不要套用其它数据版本的评测数字。回答直接面向学习者，不介绍资料来源的内部分类。"
                    if selected_intent:
                        task += "\n用户已通过标签明确选择此工作流，输入文本作为该工作流的素材。不要改为其它任务；如果素材不足，按当前工作流提出具体补充问题。"
                    prompt = json.dumps({"task": task, "workflow": intent, "route_mode": trace["route"]["mode"], "history": context, "input": user_input,
                                         "query": trace["rewritten_query"], "course_evidence": sources}, ensure_ascii=False)
                    answer = await self.generate(prompt, trace, emit)
                    verified_answer, trace["unverified_citations"] = validate_citations(answer, sources)
                    trace["cited_sources"] = citations(verified_answer, sources)
                    answer = public_answer(verified_answer)
                    trace["status"] = "success"
            trace["answer"] = answer
        except Exception as exc:
            trace["status"] = "error"
            trace["error_type"] = type(exc).__name__
            trace["error_message"] = friendly_error(exc)
            trace["answer"] = trace["error_message"]
            await emit("error", {"message": trace["error_message"]})
        trace["duration_ms"] = round((time.perf_counter()-start)*1000)
        message = self.store.add_message(session_id, "assistant", trace["answer"], trace["id"])
        trace["message_id"] = message["id"]
        self.store.save_execution(trace)
        await emit("done", {"message": {**message, "execution": trace}})
        return trace
