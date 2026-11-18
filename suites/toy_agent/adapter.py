"""玩具客服 Agent 的评测适配器（python 协议）。"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agent  # noqa: E402


def run(turns, case=None):
    """多轮：逐轮调用并把历史带上（与真实接入方式一致）。"""
    history, answer, tools, data = [], "", [], {}
    for q in turns or [""]:
        r = agent.run(q, history)
        answer = r.get("answer", "")
        tools.extend(r.get("tool_calls") or [])
        data = r.get("data") or {}
        history += [{"role": "user", "content": q},
                    {"role": "assistant", "content": answer}]
    return {"answer": answer, "tool_calls": tools, "data": data}
