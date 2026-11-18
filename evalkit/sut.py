"""被测系统（SUT）适配层：把「怎么调一个 Agent」收敛成两种协议。

设计目标：**同一套用例与指标，能同时评本地脚本和线上服务**，切换成本只有一行配置。

    # suite.json 里的两种写法
    {"protocol": "python", "callable": "adapter:run", "env": ["BABYAGI_HOME"]}
    {"protocol": "http",   "url_env": "GIS_AGENT_URL", "endpoint": "/api/eval/chat"}

统一返回（任一协议都必须归一成这个形状，缺字段按空处理）：

    {"answer": str, "tool_calls": [{"name":..., "args":...}], "data": {...}}

HTTP 协议（服务侧实现 /api/eval/chat）：
    请求  {"turns": ["第一句", "追问"], "case": {"id": "GIS-P01", "file": "cities.geojson"}}
    响应  {"answer": "...", "tool_calls": [...], "data": {"hits": [...], "stdout": "..."}}
    —— 服务自己决定内部怎么走（上传→生成代码→沙箱），评测器只认这个出口。
"""
import importlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


class SUTError(Exception):
    pass


def missing_env(spec):
    return [k for k in (spec.get("env") or []) + ([spec["url_env"]] if spec.get("url_env") else [])
            if not os.environ.get(k)]


def normalize(raw: Any, elapsed: float = 0.0) -> dict:
    """把各种返回形状归一成 {answer, tool_calls, data, t_sut}。"""
    if raw is None:
        raise SUTError("SUT 返回空")
    if isinstance(raw, str):
        raw = {"answer": raw}
    if not isinstance(raw, dict):
        raise SUTError(f"SUT 返回类型不支持：{type(raw).__name__}")

    answer = raw.get("answer") or raw.get("output") or raw.get("text") or ""
    data: dict[str, Any] = dict(raw.get("data") or {})
    for k in ("stdout", "stderr", "hits", "retrieved", "files", "steps", "security", "error"):
        if k in raw and k not in data:
            data[k] = raw[k]
    tools = raw.get("tool_calls") or []
    if isinstance(tools, str):
        tools = [{"name": tools}]
    return {"answer": str(answer), "tool_calls": tools, "data": data, "t_sut": round(elapsed, 3)}


# ------------------------------------------------------------------ python 协议
def load_callable(spec, suite_dir):
    """spec["callable"] = "module:function"，模块在 suite 目录下解析。

    注意：不能直接 import_module——多个 suite 都有 `adapter.py`，同名模块会命中
    sys.modules 缓存，导致「用 A 的适配器跑 B 的用例」。这里按文件路径加载，
    并给模块一个带 suite 名的唯一名字。
    """
    target = spec.get("callable") or ""
    if ":" not in target:
        raise SUTError(f"callable 需要写成 module:function，收到 {target!r}")
    mod_name, fn_name = target.split(":", 1)
    path = os.path.join(suite_dir, mod_name.replace(".", os.sep) + ".py")
    if not os.path.exists(path):
        raise SUTError(f"{suite_dir} 下找不到 {mod_name}.py")

    import hashlib
    import importlib.util

    uniq = f"sut_{hashlib.md5(os.path.abspath(path).encode()).hexdigest()[:8]}_{mod_name.split('.')[-1]}"
    if uniq in sys.modules:                       # 同一进程内复用已经加载的模块
        mod = sys.modules[uniq]
    else:
        if suite_dir not in sys.path:
            sys.path.insert(0, suite_dir)
        spec_obj = importlib.util.spec_from_file_location(uniq, path)
        if spec_obj is None or spec_obj.loader is None:
            raise SUTError(f"无法加载 {path}")
        mod = importlib.util.module_from_spec(spec_obj)
        sys.modules[uniq] = mod
        spec_obj.loader.exec_module(mod)

    fn = getattr(mod, fn_name, None)
    if not callable(fn):
        raise SUTError(f"{path} 里没有可调用的 {fn_name}")
    return fn


def call_python(fn, turns, case, suite_dir):
    t0 = time.time()
    raw = fn(turns, case)
    return normalize(raw, time.time() - t0)


# ------------------------------------------------------------------ http 协议
def call_http(spec, turns, case):
    base = os.environ.get(spec["url_env"], "").rstrip("/")
    if not base:
        raise SUTError(f"未设置 {spec['url_env']}，无法连接 {spec.get('name', '')}")
    endpoint = spec.get("endpoint") or "/api/eval/chat"
    payload = {"turns": turns, "case": {"id": case.get("id"), "file": case.get("file"),
                                        "category": case.get("category")}}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{base}{endpoint}", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=spec.get("timeout", 180)) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:500]
        raise SUTError(f"HTTP {e.code}：{detail}")
    except urllib.error.URLError as e:
        raise SUTError(f"连不上 {base}：{e.reason}")
    return normalize(raw, time.time() - t0)


def call(spec, turns, case, suite_dir):
    if spec.get("protocol") == "http":
        return call_http(spec, turns, case)
    if spec.get("protocol") == "python":
        return call_python(load_callable(spec, suite_dir), turns, case, suite_dir)
    raise SUTError(f"未知协议：{spec.get('protocol')!r}（只支持 python / http）")
