"""前端产物（HTML 看板 / 报告页 / Web 接口）的自测：不启服务，直接调函数。"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evalkit  # noqa: E402
from evalkit import report_html, web  # noqa: E402


def _seed(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    recs = [
        {"id": "S-01", "category": "正向", "suite": "系统甲", "rule_score": 100.0, "rule_pass": True,
         "judge_pass": True, "judge_score": 95.0, "t_sut": 1.2, "dim_scores": {"result": 10.0},
         "checks": [{"check": "c1", "dim": "result", "type": "contains_any", "result": True}],
         "turns": ["你好"], "answer": "回答一"},
        {"id": "S-02", "category": "边界", "suite": "系统甲", "rule_score": 60.0, "rule_pass": False,
         "judge_pass": False, "judge_score": 55.0, "t_sut": 2.4, "dim_scores": {"result": 6.0},
         "checks": [{"check": "c2", "dim": "result", "type": "rows_eq", "result": False}],
         "turns": ["再来"], "answer": "回答二", "judge": {"reason": "行数不符"}},
    ]
    p = runs / "sys_a.jsonl"
    for r in recs:
        evalkit.append_jsonl(str(p), r)
    return str(runs)


def test_static_html_dashboard(tmp_path):
    runs = _seed(tmp_path)
    out, info = web.build_html(runs, str(tmp_path / "d.html"))
    html = open(out, encoding="utf-8").read()
    assert info["systems"] == 1 and info["cases"] == 2
    assert "系统甲" in html and "S-02" in html
    assert "50.0%" in html          # 1/2 通过


def test_report_html_editorial(tmp_path):
    runs = _seed(tmp_path)
    out, info = report_html.build("sys_a", runs, str(tmp_path / "r.html"))
    html = open(out, encoding="utf-8").read()
    assert info["cases"] == 2 and info["bad"] == 1 and info["agreement"] == 100.0
    assert "用例达标" in html and "S-02" in html and "行数不符" in html
    assert "%.1f" not in html       # 格式化结果落进去，别把模板串留下来
    assert "60.0" in html


def test_web_overview_reads_runs_dir(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="Web 控制台是可选依赖：pip install 'agent-eval-kit[web]'")
    runs = _seed(tmp_path)
    monkeypatch.setenv("EVALKIT_RUNS", runs)
    import importlib
    from evalkit import server
    importlib.reload(server)                       # 让模块级 RUNS_DIR 读到新 env
    d = server.overview()
    assert d["totals"]["systems"] == 1
    assert d["suites"][0]["cases"] == 2
    # 两条里一条 judge 通过 → 50%；没有 Judge 的系统应为 None（前端显示“—”）而不是 0%
    assert d["suites"][0]["judge_rate"] == 50.0
    cases = server.suite("sys_a")["cases"]
    assert len(cases) == 2 and cases[1]["checks"][0]["check"] == "c2"
