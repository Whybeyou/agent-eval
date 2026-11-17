"""示例：给玩具客服 Agent 跑 10 条固定集。

    python examples/toy_agent/run_eval.py               # 只用规则机评（离线可跑）
    EVAL_JUDGE=1 python examples/toy_agent/run_eval.py  # 同时跑 LLM-Judge（需 DEEPSEEK_API_KEY）

看三件事：规则通过率、Judge 通过率、两者一致率——一致率低说明「标准本身有歧义」，
而不是模型不行；这类分歧要人工看几条再改 Rubric。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))     # 仓库根
sys.path.insert(0, HERE)

import agent as toy  # noqa: E402
import evalkit  # noqa: E402

RUBRIC = {
    "project": "玩具客服 Agent",
    "dimensions": {
        "process": {"weight": 0.25, "children": {
            "route_decision": "该检索才检索、寒暄不检索",
            "multiturn": "多轮上下文承接"}},
        "result": {"weight": 0.40, "children": {
            "fact_correct": "金额/时限/条件与知识库一致",
            "citation": "引用来源可核查"}},
        "expression": {"weight": 0.15, "children": {
            "clarity": "长度与条理适合 IM 场景"}},
        "risk": {"weight": 0.20, "children": {
            "no_hallucination": "知识库没有的不编造",
            "no_overpromise": "不承诺无权限的操作"}},
    },
}


def main():
    cases = json.load(open(os.path.join(HERE, "cases.json"), encoding="utf-8"))
    out = os.path.join(HERE, "results", "toy_results.jsonl")
    if os.path.exists(out):
        os.remove(out)

    do_judge = os.environ.get("EVAL_JUDGE") == "1"
    for case in cases:
        turns = case.get("turns") or [case.get("input", "")]
        history, answers, tools, t0 = [], [], [], time.time()
        for q in turns:
            r = toy.run(q, history)
            answers.append(r["answer"])
            tools.extend(r.get("tool_calls") or [])
            history += [{"role": "user", "content": q}, {"role": "assistant", "content": r["answer"]}]

        ctx = {"answer": answers[-1], "tool_calls": tools, "data": r.get("data") or {}}
        checks, dim_hits = evalkit.run_checks(case, ctx, evalkit.check)
        scored = evalkit.score_case(dim_hits)

        rec = {"id": case["id"], "category": case["category"], "turns": turns,
               "answer": answers[-1], "tool_calls": tools, "checks": checks,
               "dim_scores": scored["dim_scores"], "rule_score": scored["score"],
               "rule_pass": scored["pass"], "risk_fail": scored["risk_fail"],
               "t_total": round(time.time() - t0, 3), "judge_pass": None}

        if do_judge:
            try:
                j = evalkit.judge_case(RUBRIC, case, answers[-1],
                                       {"checks": checks, "rule_score": scored["score"]})
                rec["judge"] = j
                rec["judge_score"] = j.get("score")
                rec["judge_pass"] = j.get("_verdict")
            except Exception as e:                        # judge 失败不影响规则结论
                rec["judge"] = {"error": str(e)}

        evalkit.append_jsonl(out, rec)
        print(f"[{case['id']}] rule={rec['rule_score']} pass={rec['rule_pass']} "
              f"judge={rec.get('judge_score')}", flush=True)

    evalkit.report.main([out, "--name", RUBRIC["project"], "--out",
                         os.path.join(HERE, "results", "summary.json")])


if __name__ == "__main__":
    main()
