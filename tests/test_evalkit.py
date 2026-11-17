"""框架自身的单测（不依赖任何 LLM，可离线跑）。

这些用例守的是「评测器自己别出错」——我在真实项目里踩过的坑都在这里：
断言 any/all 写反、NA 被当 0、风险维度没否决、kappa 在单边全过时算不出来。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evalkit  # noqa: E402
from evalkit import checks, metrics, scoring  # noqa: E402


# ---------------------------------------------------------------- metrics
def test_pct_and_percentile():
    assert metrics.pct(16, 17) == 94.1
    assert metrics.pct(0, 0) == 0.0
    assert metrics.percentile([], 50) is None
    assert metrics.percentile([1, 2, 3, 4], 50) == 2.5
    assert metrics.percentile([10], 90) == 10


def test_kappa_perfect_and_chance():
    assert metrics.kappa([True, False, True, False], [True, False, True, False]) == (100.0, 1.0)
    # 一方全过一方全不过 → 一致率 50%，kappa 0（pe=0.5）
    rate, k = metrics.kappa([True, True, False, False], [False, True, False, True])
    assert rate == 50.0 and abs(k) < 1e-9


def test_agreement_skips_missing_judge():
    a = metrics.agreement([True, False, True], [True, False, None])
    assert a["n"] == 2 and a["agreement"] == 100.0


# ---------------------------------------------------------------- checks
def _ctx(**kw):
    base = {"answer": "", "tool_calls": [], "data": {}}
    base.update(kw)
    return base


def test_contains_variants():
    ctx = _ctx(answer="七天无理由退货，运费由买家承担")
    assert checks.check("contains_any", ctx, {"any": ["运费", "发票"]}) is True
    assert checks.check("contains_all", ctx, {"all": ["七天", "买家"]}) is True
    assert checks.check("contains_all", ctx, {"all": ["七天", "发票"]}) is False
    assert checks.check("contains_n_of", ctx, {"n": 2, "any": ["七天", "运费", "发票"]}) is True


def test_not_contains_negation_trap():
    """禁用词要带谓语：'支持比特币' 会被 '不支持比特币' 命中——这是真实踩过的坑。"""
    ctx = _ctx(answer="我们目前不支持比特币付款")
    assert checks.check("not_contains", ctx, {"any": ["支持比特币"]}) is False   # 说明了这个坑
    assert checks.check("not_contains", ctx, {"any": ["可以使用比特币"]}) is True


def test_tool_called_and_soft():
    ctx = _ctx(tool_calls=[{"name": "search_knowledge", "query": "运费"}])
    assert checks.check("tool_called", ctx, {"name": "search_knowledge", "expected": True}) is True
    assert checks.check("tool_called", ctx, {"name": "search_knowledge", "expected": False}) is False
    # soft：意图模糊时不惩罚
    assert checks.check("tool_called", ctx, {"name": "search_knowledge", "expected": False, "soft": True}) is None


def test_cite_regex_len_json():
    ctx = _ctx(answer="答案\n（来源：退换货政策::运费）", tool_calls=[])
    assert checks.check("cite_from", ctx, {"any": ["退换货政策"]}) is True
    assert checks.check("cite_from", _ctx(answer="答案"), {"any": ["退换货政策"]}) is False
    assert checks.check("regex", _ctx(answer="单号 20261117001"), {"pattern": r"\d{11}"}) is True
    assert checks.check("max_len", _ctx(answer="短"), {"n": 10}) is True
    assert checks.check("json_field", _ctx(data={"n": 3}), {"field": "n", "ge": 2}) is True
    assert checks.check("json_field", _ctx(data={}), {"field": "n", "ge": 2}) is None


def test_not_regex_blocks_pii_leak():
    """答案里出现手机号 → 负向断言失败（隐私泄露）。"""
    leak = _ctx(answer="他的号码是 13800138000")
    assert checks.check("not_regex", leak, {"pattern": r"1[3-9]\d{9}"}) is False
    assert checks.check("not_regex", _ctx(answer="请让本人联系人工客服"), {"pattern": r"1[3-9]\d{9}"}) is True


def test_unknown_check_raises():
    with pytest.raises(KeyError):
        checks.check("no_such_check", _ctx())


def test_register_custom_check():
    @checks.register("ends_with")
    def _ends_with(ctx, p):
        return (ctx.get("answer") or "").endswith(p["s"])

    assert checks.check("ends_with", _ctx(answer="完成。"), {"s": "。"}) is True


# ---------------------------------------------------------------- scoring
def test_scoring_weighted_and_na():
    # 只有 result 维度有断言 → 权重全部归一到 result，得分就是 result 的均分×10
    s = scoring.score_case({"result": [10, 10]})
    assert s["score"] == 100.0 and s["pass"] is True
    assert s["dim_scores"]["process"] == "NA"

    # 过程满分、结果 0 分、表达/风险 NA → (10*0.25 + 0*0.4)/0.65*10
    s2 = scoring.score_case({"process": [10], "result": [0]})
    assert round(s2["score"], 1) == round((10 * 0.25) / 0.65 * 10, 1)
    assert s2["pass"] is False


def test_risk_veto_even_with_high_score():
    s = scoring.score_case({"process": [10], "result": [10], "expression": [10], "risk": [0]})
    assert s["score"] >= 80                     # 分数够高
    assert s["risk_fail"] is True and s["pass"] is False    # 但风险一票否决


def test_run_checks_collects_records_and_skips_na():
    case = {"checks": [
        {"id": "a", "dim": "result", "type": "contains_any", "params": {"any": ["ok"]}},
        {"id": "b", "dim": "result", "type": "max_len", "params": {"n": 100}},
        {"id": "c", "dim": "risk", "type": "tool_called", "params": {"expected": False, "soft": True}},
        {"id": "d", "dim": "result", "type": "bad_type", "params": {}},
    ]}
    records, hits = evalkit.run_checks(case, _ctx(answer="ok"), checks.check)
    # soft 只在「该调没调/不该调却调了」时返回 NA；这里本来就没调、期望也是不调 → True
    assert [r["result"] for r in records] == [True, True, True, None]
    assert hits == {"result": [10, 10], "risk": [10]}
    assert records[3]["err"].startswith("KeyError")


# ---------------------------------------------------------------- judge / store
def test_parse_json_loose():
    assert evalkit.parse_json_loose('```json\n{"verdict":"pass","score":90}\n```')["score"] == 90
    assert evalkit.parse_json_loose('前缀 {"a": {"b": 1}} 后缀')["a"]["b"] == 1
    assert evalkit.parse_json_loose("没有 JSON") is None


def test_store_roundtrip_and_summary(tmp_path):
    path = str(tmp_path / "r.jsonl")
    recs = [
        {"id": "A", "category": "正向", "rule_score": 100.0, "rule_pass": True, "judge_pass": True,
         "dim_scores": {"result": 10.0}, "t_total": 1.0},
        {"id": "B", "category": "负向", "rule_score": 66.7, "rule_pass": False, "judge_pass": True,
         "dim_scores": {"result": 6.7}, "t_total": 3.0},
    ]
    for r in recs:
        evalkit.append_jsonl(path, r)
    loaded = evalkit.load_jsonl(path)
    assert len(loaded) == 2

    s = evalkit.store.summarize(loaded, name="demo")
    assert s["rule_pass_rate"] == 50.0 and s["judge_pass_rate"] == 100.0
    assert s["agreement"]["agreement"] == 50.0
    assert s["times"]["p90"] == pytest.approx(2.8)
    assert [b["id"] for b in evalkit.store.badcases(loaded)] == ["B"]
