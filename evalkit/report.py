"""一键汇总：读 JSONL → 通过率 / 分类 / 维度 / 一致率 / badcase → Markdown 报告。

用法（在示例目录里）：
    python -m evalkit.report results/toy_results.jsonl --name "玩具客服 Agent"
"""
import argparse
import json

from .metrics import pct
from .store import badcases, load_jsonl, markdown, summarize


def build(records, name="agent", tr_field="t_total"):
    s = summarize(records, name=name, tr_field=tr_field)
    return {"summary": s, "badcases": badcases(records), "markdown": markdown(s)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="汇总评测结果")
    ap.add_argument("jsonl")
    ap.add_argument("--name", default="agent")
    ap.add_argument("--out", default=None, help="把汇总 JSON 写到这个路径")
    args = ap.parse_args(argv)

    res = build(load_jsonl(args.jsonl), name=args.name)
    print(res["markdown"])
    if res["badcases"]:
        print("\nBadcase：")
        for b in res["badcases"]:
            print(f"  - {b['id']} [{b['category']}] rule={b['rule_score']} "
                  f"judge={b['judge_score']} 失败断言={b['failed_checks']} {b['judge_reason'][:80]}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"\n已写入 {args.out}")


if __name__ == "__main__":
    main()
