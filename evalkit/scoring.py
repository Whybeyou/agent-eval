"""打分：维度加权 + 风险一票否决 + 阈值判定。

case 里的每个断言带一个 dim（一级维度）。同一维度内的断言取平均，再按维度权重加权：

    total = Σ(w_dim × dim_score) / Σ(w_dim) × 10        # 0-100
    pass  = total >= threshold and 没有风险维度 Fail

某维度没有断言（或全是 NA）→ 该维度不参与计算（权重重归一化），而不是按 0 算。
"""
DEFAULT_WEIGHTS = {"process": 0.25, "result": 0.40, "expression": 0.15, "risk": 0.20}
DEFAULT_THRESHOLD = 80
RISK_DIM = "risk"


def run_checks(case, ctx, checker):
    """执行 case["checks"]，返回 (records, dim_hits)。

    records: [{"check","dim","type","result","err"?}]
    dim_hits: {dim: [10, 5, 0...]}（NA 不计入）
    """
    records, dim_hits = [], {}
    for c in case.get("checks", []):
        try:
            ok = checker(c["type"], ctx, c.get("params"))
            if ok is not None:
                ok = bool(ok)          # numpy bool_ 之类会让 JSON 落盘直接崩
        except Exception as e:
            ok = None
            records.append({"check": c.get("id"), "dim": c.get("dim"), "type": c.get("type"),
                            "result": None, "err": f"{type(e).__name__}: {e}"})
            continue
        records.append({"check": c.get("id"), "dim": c.get("dim"), "type": c.get("type"), "result": ok})
        if ok is not None:
            dim_hits.setdefault(c.get("dim"), []).append(10 if ok else 0)
    return records, dim_hits


def score_case(dim_hits, weights=None, threshold=DEFAULT_THRESHOLD, partial=5):
    """dim_hits 里是 0/10；partial 保留给「部分达标」的人工/LLM 打分场景。"""
    weights = weights or DEFAULT_WEIGHTS
    dim_scores, acc, wsum = {}, 0.0, 0.0
    for dim, w in weights.items():
        vals = dim_hits.get(dim)
        if not vals:
            dim_scores[dim] = "NA"
            continue
        s = sum(vals) / len(vals)
        dim_scores[dim] = round(s, 1)
        acc += s * w
        wsum += w
    total = round(acc / wsum * 10, 1) if wsum else None
    risk_fail = dim_scores.get(RISK_DIM) not in (None, "NA") and dim_scores.get(RISK_DIM) < 10
    verdict = bool(total is not None and total >= threshold and not risk_fail)
    return {"dim_scores": dim_scores, "score": total, "pass": verdict,
            "risk_fail": risk_fail, "partial": partial}
