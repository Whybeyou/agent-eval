"""性能探针：模型层 TTFT / TPOT（流式）+ Agent 层端到端（从跑批记录聚合）。

为什么要分开：业务接口大多非流式，只能量到「整包耗时」；TTFT/TPOT 得用同模型、
同规模输入的流式请求单独补测，两个口径分开报，别混着说。
"""
import json
import time
import urllib.request

from .llm import DEFAULT_BASE_URL, DEFAULT_MODEL, api_key
from .metrics import percentile


def stream_probe(prompt, model=None, max_tokens=400, runs=3, base_url=None, timeout=180):
    """返回 {ttft_p50, tpot_p50, total_p50, runs:[…]}；TTFT=首个内容 chunk，TPOT=chunk 间隔均值。"""
    model = model or DEFAULT_MODEL
    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
    out = []
    for _ in range(runs):
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
                   "max_tokens": max_tokens, "temperature": 0.2, "stream": True}
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key()}"},
        )
        t0, ttft, chunks, last = time.time(), None, 0, None
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    delta = (json.loads(body).get("choices") or [{}])[0].get("delta") or {}
                except json.JSONDecodeError:
                    continue
                if delta.get("content") or delta.get("reasoning_content"):
                    ttft = ttft or (time.time() - t0)
                    chunks += 1
                    last = time.time()
        total = time.time() - t0
        tpot = (last - t0 - ttft) / max(chunks - 1, 1) if ttft else None
        out.append({"ttft": round(ttft, 3) if ttft else None,
                    "tpot": round(tpot, 4) if tpot else None,
                    "total": round(total, 3), "chunks": chunks})
    ok = [o for o in out if o["ttft"]]
    return {"runs": out,
            "ttft_p50": percentile([o["ttft"] for o in ok], 50),
            "tpot_p50": percentile([o["tpot"] for o in ok if o["tpot"]], 50),
            "total_p50": percentile([o["total"] for o in out], 50)}


def agent_layer(times):
    """Agent 端到端（从跑批记录的耗时聚合）。"""
    return {"n": len(times), "p50": percentile(times, 50),
            "p90": percentile(times, 90), "max": max(times) if times else None}
