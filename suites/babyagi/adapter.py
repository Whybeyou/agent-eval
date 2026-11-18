"""BabyAGI 自主 Agent 的评测适配器（python 协议，进程内 + stdout 采集）。

这个系统的可观测面很窄：没有 HTTP 接口，只在终端打印「第 N 轮」「🔧 调工具 X」。
所以适配器做两件事：把 stdout 抓下来解析成结构化证据（轮数、工具调用），
再把产物目录（agent_output/）里的文件内容带进 data——断言据此判断「真做了」还是「说了」。

换别的本地 Agent 时，只要 adapter.run(turns, case) 归一成
{"answer", "tool_calls", "data": {"rounds", "files", "file_contents"}} 即可复用同一批断言。
"""
import contextlib
import importlib.util
import io
import os
import re
import sys

HOME = os.environ.get("BABYAGI_HOME", "").rstrip("/\\")
if not HOME:
    raise RuntimeError("需要设置 BABYAGI_HOME 指向 babyagi-mini 目录")

_MOD = None


def _module():
    global _MOD
    if _MOD is None:
        path = os.path.join(HOME, "babyagi_pro.py")
        spec = importlib.util.spec_from_file_location("babyagi_pro", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["babyagi_pro"] = mod
        spec.loader.exec_module(mod)
        _MOD = mod
    return _MOD


def run(turns, case=None):
    case = case or {}
    objective = (turns or [""])[0]
    max_steps = int(case.get("max_steps") or 1)
    _module()                                   # 先导入，避免把导入日志算进 stdout

    cwd = os.getcwd()
    buf = io.StringIO()
    os.chdir(HOME)                              # 记忆文件与产物目录都在项目下
    try:
        with contextlib.redirect_stdout(buf):
            _module().run(objective=objective, first_task=objective, max_steps=max_steps)
    finally:
        os.chdir(cwd)
    out = buf.getvalue()

    rounds = len(re.findall(r"=== 第 \d+ 轮", out))
    error_count = len(re.findall(r"(Traceback \(most recent|FileNotFoundError|PermissionError|KeyError)", out))
    tools = [{"name": m.strip()} for m in re.findall(r"🔧 调工具 ([A-Za-z_][\w]*)", out)]

    out_dir = os.path.join(HOME, "agent_output")
    files, contents = [], {}
    for name in sorted(os.listdir(out_dir)) if os.path.isdir(out_dir) else []:
        p = os.path.join(out_dir, name)
        if not os.path.isfile(p):
            continue
        files.append(name)
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                contents[name] = f.read()[:4000]
        except OSError:
            pass

    artifacts = "\n".join(f"[产物 {n}]\n{t}" for n, t in contents.items())
    return {
        "answer": (out[-2000:] + "\n\n" + artifacts)[:6000],
        "tool_calls": tools,
        "data": {"stdout": out[-4000:], "rounds": rounds, "files": files,
                 "file_contents": contents, "max_steps": max_steps,
                 "error_count": error_count, "steps_exceeded": rounds > max_steps},
    }
