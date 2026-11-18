"""平台层（suite 装载 / 适配器解析 / 跨系统看板）的自测。

重点守这条：**多个 suite 都叫 adapter.py 时，不能出现「用 A 的适配器跑 B 的用例」**。
这个 bug 真的发生过——直接 import_module 会命中 sys.modules 缓存。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evalkit  # noqa: E402
from evalkit import dashboard, runner, sut  # noqa: E402


def _make_suite(root, name, slug, answer, cases):
    d = root / slug
    d.mkdir(parents=True)
    (d / "suite.json").write_text(json.dumps({
        "name": name, "slug": slug, "protocol": "python", "callable": "adapter:run",
        "cases": "cases.json", "threshold": 80,
        "rubric": {"dimensions": {"result": {"weight": 1.0, "children": {}}}},
    }, ensure_ascii=False), encoding="utf-8")
    (d / "cases.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    # 两个 suite 故意用同一个模块名 adapter.py
    (d / "adapter.py").write_text(
        f'def run(turns, case=None):\n    return {{"answer": {answer!r}, "tool_calls": [], "data": {{}}}}\n',
        encoding="utf-8")
    return d


CASES = [{"id": "X01", "category": "正向", "turns": ["hi"],
          "checks": [{"id": "c", "dim": "result", "type": "contains_any", "params": {"any": ["甲"]}}]}]


def test_two_suites_with_same_module_name_are_isolated(tmp_path):
    a = _make_suite(tmp_path, "系统A", "a", "甲系统回答", CASES)
    b = _make_suite(tmp_path, "系统B", "b", "乙系统回答", CASES)
    runner.run_suite(str(a), out_path=str(tmp_path / "a.jsonl"), verbose=False)
    s2 = runner.run_suite(str(b), out_path=str(tmp_path / "b.jsonl"), verbose=False)

    rec_a = evalkit.load_jsonl(str(tmp_path / "a.jsonl"))[0]
    rec_b = evalkit.load_jsonl(str(tmp_path / "b.jsonl"))[0]
    assert rec_a["answer"] == "甲系统回答" and rec_a["rule_pass"] is True
    assert rec_b["answer"] == "乙系统回答" and rec_b["rule_pass"] is False   # 断言只要「甲」
    assert s2["rule_pass_rate"] == 0.0


def test_missing_env_skips_suite(tmp_path):
    d = tmp_path / "need_env"
    d.mkdir()
    (d / "suite.json").write_text(json.dumps({
        "name": "需要服务的系统", "slug": "need", "protocol": "http",
        "url_env": "NO_SUCH_SERVICE_URL", "cases": "cases.json"}), encoding="utf-8")
    (d / "cases.json").write_text(json.dumps(CASES, ensure_ascii=False), encoding="utf-8")
    s = runner.run_suite(str(d), out_path=str(tmp_path / "n.jsonl"), verbose=False)
    assert s["skipped"] is True and "NO_SUCH_SERVICE_URL" in s["reason"]


def test_http_error_is_recorded_not_raised(tmp_path, monkeypatch):
    d = tmp_path / "svc"
    d.mkdir()
    (d / "suite.json").write_text(json.dumps({
        "name": "服务型系统", "slug": "svc", "protocol": "http",
        "url_env": "FAKE_URL", "cases": "cases.json"}), encoding="utf-8")
    (d / "cases.json").write_text(json.dumps(CASES, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("FAKE_URL", "http://127.0.0.1:9")      # 必然连不上
    s = runner.run_suite(str(d), out_path=str(tmp_path / "svc.jsonl"), verbose=False)
    rec = evalkit.load_jsonl(str(tmp_path / "svc.jsonl"))[0]
    assert rec["rule_pass"] is False and "连不上" in (rec["error"] or "")
    assert s["rule_pass_rate"] == 0.0


def test_normalize_variants():
    assert sut.normalize("纯文本")["answer"] == "纯文本"
    n = sut.normalize({"output": "文本", "stdout": "out", "tool_calls": "search"})
    assert n["answer"] == "文本" and n["data"]["stdout"] == "out"
    assert n["tool_calls"] == [{"name": "search"}]
    with pytest.raises(sut.SUTError):
        sut.normalize(123)


def test_dashboard_aggregates_multiple_suites(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    rows = [("系统A", "A1", True), ("系统A", "A2", False), ("系统B", "B1", True)]
    for suite, cid, ok in rows:
        evalkit.append_jsonl(str(runs / f"{suite}.jsonl"), {
            "id": cid, "suite": suite, "category": "正向", "rule_pass": ok,
            "rule_score": 100.0 if ok else 40.0, "judge_pass": ok, "t_sut": 1.0,
            "dim_scores": {"result": 10.0 if ok else 4.0}})
    md = dashboard.markdown(dashboard.build(str(runs)))
    assert "接入 **2** 个被测系统" in md and "共 **3** 条用例" in md
    assert "系统A" in md and "50.0% (1/2)" in md
