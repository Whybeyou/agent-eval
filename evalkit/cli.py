"""命令行入口：一套命令跑所有被测系统，再出一张跨系统看板。

    python -m evalkit.cli list                                  # 看有哪些 suite、各自要不要连服务
    python -m evalkit.cli run suites/toy_agent suites/ecom_rag   # 离线跑（不花钱）
    python -m evalkit.cli run suites/ --judge --env-file .env    # 全跑 + LLM-Judge
    python -m evalkit.cli report runs/                           # 出看板
"""
import argparse
import glob
import os
import sys

from . import dashboard, report_html, runner, web


def load_env_file(path):
    """极简 .env 读取（KEY=VALUE），不覆盖已有环境变量。"""
    if not path or not os.path.exists(path):
        return 0
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and not os.environ.get(k):
                os.environ[k] = v
                n += 1
    return n


def expand(paths):
    out = []
    for p in paths:
        if os.path.isdir(p) and os.path.exists(os.path.join(p, "suite.json")):
            out.append(p)
        elif os.path.isdir(p):
            out += sorted(d for d in glob.glob(os.path.join(p, "*"))
                          if os.path.exists(os.path.join(d, "suite.json")))
    return out


def cmd_list(args):
    for d in expand(args.suites):
        spec, _ = runner.load_suite(d)
        need = runner.sut.missing_env(spec)
        status = "就绪" if not need else f"待配置 {need}"
        print(f"{d:<32} {spec.get('protocol'):<7} {spec.get('name')}  [{status}]")


def cmd_run(args):
    if args.env_file:
        n = load_env_file(args.env_file)
        print(f"# 从 {args.env_file} 载入 {n} 个环境变量")
    summaries = []
    for d in expand(args.suites):
        spec, _ = runner.load_suite(d)
        print(f"\n=== {spec.get('name')} ({d}) ===", flush=True)
        s = runner.run_suite(d, out_path=None if not args.runs else
                             os.path.join(args.runs, f"{spec.get('slug', os.path.basename(d))}.jsonl"),
                             do_judge=args.judge, only=args.only)
        if s.get("skipped"):
            print(f"  跳过：{s['reason']}")
        else:
            print(f"  → 规则通过率 {s['rule_pass_rate']}% ({s['rule_pass']}/{s['cases']})"
                  + (f"，Judge 通过率 {s['judge_pass_rate']}%（{s['judge_cases']} 条）" if s["judge_cases"] else "")
                  + (f"，badcase {s['badcases']}" if s["badcases"] else ""))
        summaries.append(s)

    md, rows = dashboard.write(args.runs, os.path.join(args.reports, "dashboard.md"))
    print("\n" + md)
    html_path, info = web.build_html(args.runs, os.path.join(args.reports, "dashboard.html"))
    print(f"\n看板已写入 {os.path.join(args.reports, 'dashboard.md')}")
    print(f"可视化看板：{html_path}（{info['systems']} 个系统 / {info['cases']} 条 / {info['rate']}%）")

    if args.strict:
        failed = [r["suite"] for r in rows if r["badcases"] or r["errors"]]
        if failed:
            print(f"\n::error::仍有 badcase/连接异常：{failed}")
            return 1
    return 0


def cmd_report_html(args):
    """生成单系统「评测报告」页（编辑册页风，适合对外展示 / 归档）。"""
    slugs = args.suite or [os.path.splitext(os.path.basename(p))[0]
                           for p in sorted(glob.glob(os.path.join(args.runs, "*.jsonl")))]
    for slug in slugs:
        path, info = report_html.build(slug, args.runs, None if not args.out_dir
                                       else os.path.join(args.out_dir, f"report_{slug}.html"))
        print(f"{info['suite']}: {info['rate']}% ({info['cases']} 条, badcase {info['bad']}, "
              f"一致率 {info['agreement']}) -> {path}")
    return 0


def cmd_serve(args):
    """起 Web 控制台：前端 + 数据接口 + 跑批按钮。"""
    import uvicorn
    from .server import app
    print(f"AgentEval 控制台 → http://{args.host}:{args.port}  (runs: {os.environ.get('EVALKIT_RUNS', 'runs')})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_web(args):
    if getattr(args, "console", False):
        path, info = web.export_console(args.runs, args.out)
        print(f"{path}（单文件控制台：{info['systems']} 个系统 / {info['cases']} 条 / "
              f"{info['rate']}% / {info['size_kb']}KB，双击即可打开）")
        return 0
    path, info = web.build_html(args.runs, args.out)
    print(f"{path}\n接入 {info['systems']} 个系统，{info['cases']} 条用例，"
          f"规则通过率 {info['rate']}%，badcase {info['badcases']} 条")
    return 0


def cmd_report(args):
    md, rows = dashboard.write(args.runs, args.out)
    print(md)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="evalkit", description="Agent 评测平台：多系统统一跑批 + 看板")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出 suite 与它们的依赖状态")
    p_list.add_argument("suites", nargs="*", default=["suites"])
    p_list.set_defaults(func=cmd_list)

    p_run = sub.add_parser("run", help="跑一个或多个 suite")
    p_run.add_argument("suites", nargs="+")
    p_run.add_argument("--judge", action="store_true", help="同时跑 LLM-Judge（需 EVAL_KEY_ENV/API key）")
    p_run.add_argument("--only", default="", help="只跑指定 id，逗号分隔")
    p_run.add_argument("--runs", default="runs", help="结果 JSONL 目录")
    p_run.add_argument("--reports", default="reports", help="看板输出目录")
    p_run.add_argument("--env-file", default=None, help="从 .env 读取环境变量（如服务地址、API key）")
    p_run.add_argument("--strict", action="store_true", help="有 badcase/异常则退出码 1")
    p_run.set_defaults(func=cmd_run)

    p_rep = sub.add_parser("report", help="只根据已有 JSONL 出看板")
    p_rep.add_argument("runs", nargs="?", default="runs")
    p_rep.add_argument("--out", default="reports/dashboard.md")
    p_rep.set_defaults(func=cmd_report)

    p_rh = sub.add_parser("report-html", help="生成单系统评测报告页（可多选）")
    p_rh.add_argument("--suite", action="append", default=[], help="slug，可重复；省略=全部")
    p_rh.add_argument("--runs", default="runs")
    p_rh.add_argument("--out-dir", default="reports")
    p_rh.set_defaults(func=cmd_report_html)

    p_serve = sub.add_parser("serve", help="起 Web 控制台（前端 + API）")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8030)
    p_serve.set_defaults(func=cmd_serve)

    p_web = sub.add_parser("web", help="生成自包含 HTML 看板（离线可开）")
    p_web.add_argument("runs", nargs="?", default="runs")
    p_web.add_argument("--out", default="reports/dashboard.html")
    p_web.add_argument("--console", action="store_true", help="导出单文件控制台（内联数据，file:// 可开）")
    p_web.set_defaults(func=cmd_web)

    args = ap.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
