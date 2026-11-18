"""Suite 执行器：一个目录 = 一个被测系统，跑完落 JSONL。

suite.json 结构：

    {
      "name": "GIS 数据处理 Agent",
      "protocol": "http",                  # python / http
      "url_env": "GIS_AGENT_URL",          # http 用：服务地址在哪个环境变量
      "endpoint": "/api/eval/chat",
      "callable": "adapter:run",           # python 用：模块:函数
      "env": ["BABYAGI_HOME"],
      "cases": "cases.json",
      "threshold": 80,
      "rubric": {"dimensions": {...}}
    }

一个 case 至少要有 id / category / turns（或 input）/ checks。
"""
import json
import os
import time

from . import checks as checks_mod
from . import judge as judge_mod
from . import scoring, sut
from .metrics import pct
from .store import append_jsonl


def load_suite(suite_dir):
    path = os.path.join(suite_dir, "suite.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"{suite_dir} 下没有 suite.json")
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    cases_path = os.path.join(suite_dir, spec.get("cases", "cases.json"))
    with open(cases_path, encoding="utf-8") as f:
        cases = json.load(f)
    spec.setdefault("threshold", 80)
    spec.setdefault("rubric", {"dimensions": {}})
    return spec, cases


def hit_at(case, data, k):
    """golden.source 是否出现在 top-k 检索结果里（按文档名比较）。"""
    want = (case.get("golden") or {}).get("source")
    if not want:
        return None
    doc = want.split("::")[0]
    src = (data or {})
    if "hits" not in src and "retrieved" not in src:
        return None                     # 不是检索类系统，不参与 Hit@k
    hits = src.get("hits") or src.get("retrieved") or []
    names = [h.get("source") if isinstance(h, dict) else str(h) for h in hits[:k]]
    return any(doc in (n or "") for n in names)


def run_suite(suite_dir, out_path=None, do_judge=False, only=None, verbose=True, judge_model=None):
    spec, cases = load_suite(suite_dir)
    name = spec.get("name") or os.path.basename(suite_dir.rstrip("/\\"))
    missing = sut.missing_env(spec)
    slug = spec.get("slug") or "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    out_path = out_path or os.path.join("runs", f"{slug}.jsonl")

    if missing:
        return {"name": name, "skipped": True, "reason": f"缺少环境变量 {missing}", "records": []}

    if os.path.exists(out_path):
        os.remove(out_path)

    only_set = {x.strip() for x in (only or "").split(",") if x.strip()}
    records, hit1 = [], 0
    hit_n = 0

    for case in cases:
        if only_set and case["id"] not in only_set:
            continue
        turns = case.get("turns") or [case.get("request") or case.get("input") or ""]
        t0 = time.time()
        try:
            res = sut.call(spec, turns, case, suite_dir)
            err = None
        except Exception as e:                      # SUT 挂了也要留记录，别整批丢
            res = {"answer": "", "tool_calls": [], "data": {"error": f"{type(e).__name__}: {e}"}, "t_sut": 0}
            err = res["data"]["error"]

        ctx = {"answer": res["answer"], "tool_calls": res["tool_calls"], "data": res["data"],
               "stdout": (res["data"].get("stdout") or ""), "stderr": (res["data"].get("stderr") or "")}
        rec_checks, dim_hits = scoring.run_checks(case, ctx, checks_mod.check)
        scored = scoring.score_case(dim_hits, threshold=spec["threshold"])

        h1 = hit_at(case, res["data"], 1)
        if h1 is not None:
            hit_n += 1
            hit1 += 1 if h1 else 0

        rec = {"id": case["id"], "category": case.get("category", "未分类"), "suite": name,
               "turns": turns, "answer": res["answer"], "tool_calls": res["tool_calls"],
               "retrieved": [h.get("source") if isinstance(h, dict) else h
                             for h in (res["data"].get("hits") or [])[:3]],
               "hit1": h1, "checks": rec_checks, "dim_scores": scored["dim_scores"],
               "rule_score": scored["score"], "rule_pass": scored["pass"],
               "risk_fail": scored["risk_fail"], "error": err,
               "t_total": round(time.time() - t0, 3), "t_sut": res["t_sut"], "judge_pass": None}

        if do_judge:
            try:
                j = judge_mod.judge_case(spec["rubric"], case, res["answer"],
                                         {"checks": rec_checks, "rule_score": scored["score"]},
                                         model=judge_model)
                rec.update({"judge": j, "judge_score": j.get("score"), "judge_pass": j.get("_verdict")})
            except Exception as e:
                rec["judge"] = {"error": str(e)}

        append_jsonl(out_path, rec)
        records.append(rec)
        if verbose:
            print(f"[{case['id']}] rule={rec['rule_score']} pass={rec['rule_pass']} "
                  f"sut={rec['t_sut']}s judge={rec.get('judge_score')}"
                  + (f" ERR={err[:60]}" if err else ""), flush=True)

    n = len(records)
    judged = [r for r in records if r.get("judge_pass") is not None]
    return {
        "name": name, "slug": spec.get("slug") or name, "skipped": False,
        "cases": n, "out": out_path,
        "rule_pass": sum(1 for r in records if r["rule_pass"]),
        "rule_pass_rate": pct(sum(1 for r in records if r["rule_pass"]), n),
        "judge_cases": len(judged),
        "judge_pass_rate": pct(sum(1 for r in judged if r["judge_pass"]), len(judged)),
        "risk_fail": sum(1 for r in records if r.get("risk_fail")),
        "hit1": pct(hit1, hit_n) if hit_n else None,
        "hit_n": hit_n,
        "avg_score": round(sum(r["rule_score"] for r in records if r["rule_score"] is not None) / max(n, 1), 1),
        "times": sorted(r["t_sut"] for r in records),
        "badcases": [r["id"] for r in records if not r["rule_pass"]],
        "records": records,
    }
