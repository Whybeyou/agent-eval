"""评测平台的 Web 服务：给前端提供数据接口，顺便把「跑批」也做成可点的按钮。

    python -m evalkit.cli serve --port 8030      # 打开 http://127.0.0.1:8030

接口：
  GET  /api/overview          总览 + 各系统摘要（前端首屏只要这一个）
  GET  /api/suite/{slug}      某系统的逐条记录（含断言与回答）
  POST /api/run/{slug}        后台跑一次（不跑 Judge，可重复点）
  GET  /api/status            跑批状态（前端轮询）
  GET  /                      前端静态页
"""
import glob
import json
import os
import subprocess
import sys
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .dashboard import summarize_file
from .store import load_jsonl

HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(HERE, "ui")
REPO = os.path.dirname(HERE)

app = FastAPI(title="AgentEval", version="0.2.0")

RUNS_DIR = os.environ.get("EVALKIT_RUNS", os.path.join(REPO, "runs"))
SUITES_DIR = os.environ.get("EVALKIT_SUITES", os.path.join(REPO, "suites"))

_LOCK = threading.Lock()
STATE = {"running": {}, "last": None, "log": {}}


def _suite_files():
    return sorted(glob.glob(os.path.join(RUNS_DIR, "*.jsonl")))


def _records(slug):
    path = os.path.join(RUNS_DIR, f"{slug}.jsonl")
    if not os.path.exists(path):
        raise HTTPException(404, f"没有 {slug} 的结果")
    return load_jsonl(path)


def _time_dist(records):
    """SUT 耗时分布（给前端画 sparkline）：只取被测系统自己的耗时。"""
    return [r.get("t_sut") for r in records if r.get("t_sut") is not None]


def _suite_summary(path):
    s = summarize_file(path)
    if not s:
        return None
    recs = load_jsonl(path)
    slug = os.path.splitext(os.path.basename(path))[0]
    dims = {}
    for r in recs:
        for d, v in (r.get("dim_scores") or {}).items():
            if v != "NA":
                dims.setdefault(d, []).append(v)
    return {
        "slug": slug, "suite": s["suite"], "cases": s["cases"], "pass": s["pass"],
        "rate": s["pass_rate"], "judge_n": s["judge_n"],
        "judge_rate": (s["judge_rate"] if s["judge_n"] else None),
        "kappa": s["kappa"], "risk_fail": s["risk_fail"], "hit1": s["hit1"],
        "p50": s["p50"], "p90": s["p90"], "badcases": s["badcases"],
        "dims": {d: round(sum(v) / len(v), 1) for d, v in dims.items()},
        "times": _time_dist(recs),
        "categories": sorted({r.get("category") for r in recs if r.get("category")}),
    }


@app.get("/api/overview")
def overview():
    rows = [s for s in (_suite_summary(p) for p in _suite_files()) if s]
    cases = sum(r["cases"] for r in rows)
    passed = sum(r["pass"] for r in rows)
    judge_n = sum(r["judge_n"] for r in rows)
    judge_ok = sum(round(r["judge_rate"] * r["judge_n"] / 100) for r in rows if r["judge_n"])
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runs_dir": RUNS_DIR,
        "totals": {
            "systems": len(rows), "cases": cases, "pass": passed,
            "rate": round(100.0 * passed / cases, 1) if cases else 0.0,
            "judge_n": judge_n,
            "judge_rate": round(100.0 * judge_ok / judge_n, 1) if judge_n else None,
            "badcases": sum(len(r["badcases"]) for r in rows),
            "risk_fail": sum(r["risk_fail"] for r in rows),
        },
        "suites": rows,
    }


@app.get("/api/suite/{slug}")
def suite(slug: str):
    recs = _records(slug)
    out = []
    for r in recs:
        out.append({
            "id": r.get("id"), "category": r.get("category"), "turns": r.get("turns"),
            "answer": r.get("answer"), "rule_score": r.get("rule_score"),
            "rule_pass": r.get("rule_pass"), "judge_score": r.get("judge_score"),
            "risk_fail": r.get("risk_fail"), "t_sut": r.get("t_sut"),
            "checks": r.get("checks") or [], "dim_scores": r.get("dim_scores") or {},
            "judge_reason": (r.get("judge") or {}).get("reason"),
            "error": r.get("error"), "retrieved": r.get("retrieved") or [],
        })
    return {"slug": slug, "cases": out}


@app.post("/api/run/{slug}")
def run_suite(slug: str):
    suite_dir = os.path.join(SUITES_DIR, slug)
    if not os.path.isdir(suite_dir):
        raise HTTPException(404, f"没有 suite 目录 {suite_dir}")
    with _LOCK:
        st = STATE["running"].get(slug)
        if st and st.get("state") == "running":
            return {"started": False, "reason": "已经在跑了", "since": st["since"]}

        def worker():
            STATE["running"][slug] = {"state": "running", "since": time.strftime("%H:%M:%S")}
            try:
                p = subprocess.run(
                    [sys.executable, "-m", "evalkit.cli", "run", suite_dir,
                     "--runs", RUNS_DIR, "--reports", os.path.join(REPO, "reports")],
                    cwd=REPO, capture_output=True, text=True, timeout=3600)
                STATE["log"][slug] = (p.stdout or "")[-4000:] + (p.stderr or "")[-2000:]
                STATE["running"][slug] = {"state": "done" if p.returncode == 0 else "failed",
                                          "since": time.strftime("%H:%M:%S")}
            except Exception as e:
                STATE["log"][slug] = f"{type(e).__name__}: {e}"
                STATE["running"][slug] = {"state": "failed", "since": time.strftime("%H:%M:%S")}
            STATE["last"] = slug

        threading.Thread(target=worker, daemon=True).start()
    return {"started": True}


@app.get("/api/status")
def status():
    return {"running": STATE["running"], "last": STATE["last"],
            "log": {k: v[-1500:] for k, v in STATE["log"].items()}}


@app.get("/api/export")
def export():
    """整包数据（前端可下载，离线复现同一份看板）。"""
    return JSONResponse(overview())


if os.path.isdir(UI_DIR):
    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")


@app.get("/")
def index():
    path = os.path.join(UI_DIR, "index.html")
    if not os.path.exists(path):
        raise HTTPException(404, "缺少前端文件 evalkit/ui/index.html")
    return FileResponse(path)
