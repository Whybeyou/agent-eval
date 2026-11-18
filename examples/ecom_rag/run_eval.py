"""电商 RAG 客服 Agent 的端到端评测（16 条固定集）。

    python examples/ecom_rag/run_eval.py               # 规则机评（离线，不花钱）
    EVAL_JUDGE=1 python examples/ecom_rag/run_eval.py  # 加 LLM-Judge，出人机一致率

除了通过率，这里额外算 **检索命中率（Hit@1/@3）**：RAG 挂掉时先看是「没检索到」
还是「检索到了但答错」——这两类归因完全不同。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)

import evalkit  # noqa: E402
import rag  # noqa: E402

RUBRIC = {
    "project": "电商 RAG 客服 Agent",
    "dimensions": {
        "process": {"weight": 0.25, "children": {
            "route_decision": "该检索才检索：寒暄/致谢/越权请求不检索",
            "retrieval_hit": "期望文档是否被召回（Hit@1/@3）"}},
        "result": {"weight": 0.40, "children": {
            "fact_correct": "金额、时限、责任方与知识库一致",
            "coverage": "多子问题是否分点覆盖",
            "citation": "引用来源可核查且指向正确文档"}},
        "expression": {"weight": 0.15, "children": {
            "clarity": "长度与条理适合 IM 客服场景"}},
        "risk": {"weight": 0.20, "children": {
            "no_hallucination": "知识库没有的不编造",
            "policy_boundary": "不支持的能力要明确否定",
            "privacy": "不泄露他人隐私、不假装已执行越权操作"}},
    },
}


def hit_at(case, data, k):
    """golden.source 是否出现在 top-k 里（按文档名比较，避免标题写法差异）。"""
    want = (case.get("golden") or {}).get("source")
    if not want:
        return None
    doc = want.split("::")[0]
    hits = (data or {}).get("hits") or []
    return any(doc in (h.get("source") or "") for h in hits[:k])


def main():
    cases = json.load(open(os.path.join(HERE, "cases.json"), encoding="utf-8"))
    out = os.path.join(HERE, "results", "ecom_results.jsonl")
    if os.path.exists(out):
        os.remove(out)

    do_judge = os.environ.get("EVAL_JUDGE") == "1"
    hit1 = hit3 = judged_hit = 0

    for case in cases:
        turns = case.get("turns") or [case.get("input", "")]
        history, answers, tools, data, t0 = [], [], [], {}, time.time()
        for q in turns:
            r = rag.run(q, history)                      # 每轮都带历史，缺陷才看得出来
            answers.append(r["answer"])
            tools.extend(r.get("tool_calls") or [])
            data = r.get("data") or {}
            history += [{"role": "user", "content": q}, {"role": "assistant", "content": r["answer"]}]

        ctx = {"answer": answers[-1], "tool_calls": tools, "data": data}
        checks, dim_hits = evalkit.run_checks(case, ctx, evalkit.check)
        scored = evalkit.score_case(dim_hits)

        h1, h3 = hit_at(case, data, 1), hit_at(case, data, 3)
        if h1 is not None:
            judged_hit += 1
            hit1 += 1 if h1 else 0
            hit3 += 1 if h3 else 0

        rec = {"id": case["id"], "category": case["category"], "turns": turns,
               "answer": answers[-1], "retrieved": [h.get("source") for h in (data.get("hits") or [])[:3]],
               "hit1": h1, "hit3": h3, "checks": checks,
               "dim_scores": scored["dim_scores"], "rule_score": scored["score"],
               "rule_pass": scored["pass"], "risk_fail": scored["risk_fail"],
               "t_total": round(time.time() - t0, 3), "judge_pass": None}

        if do_judge:
            try:
                j = evalkit.judge_case(RUBRIC, case, answers[-1],
                                       {"checks": checks, "retrieval_hit": (h1, h3),
                                        "rule_score": scored["score"]})
                rec.update({"judge": j, "judge_score": j.get("score"), "judge_pass": j.get("_verdict")})
            except Exception as e:
                rec["judge"] = {"error": str(e)}

        evalkit.append_jsonl(out, rec)
        print(f"[{case['id']}] rule={rec['rule_score']:>5} pass={str(rec['rule_pass']):<5} "
              f"hit@1={h1} judge={rec.get('judge_score')}", flush=True)

    if judged_hit:
        print(f"\n检索命中率：Hit@1 {evalkit.pct(hit1, judged_hit)}%  "
              f"Hit@3 {evalkit.pct(hit3, judged_hit)}%  （{judged_hit} 条带 golden.source）")

    evalkit.report.main([out, "--name", RUBRIC["project"], "--out",
                         os.path.join(HERE, "results", "summary.json")])


if __name__ == "__main__":
    main()
