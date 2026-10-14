import argparse
import asyncio
import json
from backend.config import settings, DATA
from backend.knowledge import Knowledge
from backend.storage import Store
from backend.agent import Agent, friendly_error


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--online",action="store_true")
    args=parser.parse_args()
    cfg=settings()
    knowledge=Knowledge()
    knowledge.initialize()
    report={"api_configured":bool(cfg["api_key"]),"model":cfg["model"],"retrieval_ready":knowledge.collection is not None,
            "retrieval_error":knowledge.error,"stats":knowledge.stats()}
    if knowledge.collection is not None:
        report["retrieval_probe"]=[r["chunk_id"] for r in knowledge.retrieve("RAG 是什么？")]
    if args.online:
        trace={}
        try:
            await Agent(Store(DATA/"workspace.sqlite3"),knowledge).completion("只回复连接正常。","连接检查",trace)
            report["online_ok"]=True
            report["model_calls"]=trace["model_calls"]
        except Exception as exc:
            report["online_ok"]=False
            report["error"]=friendly_error(exc)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["retrieval_ready"] and (not args.online or report.get("online_ok")) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
