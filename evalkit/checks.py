"""声明式断言：按名字注册，case 里只写 {"type": ..., "params": ...}。

内置断言都是「语义明确、不会误判」的那一类；领域断言请用 register 扩展，例如：

    from evalkit import register
    from evalkit.checks import CheckResult   # 返回 True / False / None(NA)

    @register("crs_family")
    def _crs_family(ctx, params):
        gdf = ctx.get("gdf")
        return None if gdf is None else str(gdf.crs) .startswith(params["family"])

返回约定：True=通过 / False=不通过 / None=不适用（NA，不计分）。
"""
import re

REGISTRY = {}

NOT_PROVIDED = object()


def register(name):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco


def check(name, ctx, params=None):
    """按名字执行断言；未注册的断言抛错（防止 case 里写了拼错的名字被静默跳过）。"""
    if name not in REGISTRY:
        raise KeyError(f"未注册的断言类型：{name}（已注册：{sorted(REGISTRY)}）")
    return REGISTRY[name](ctx, params or {})


# ------------------------------------------------------------------ 内置断言
def _text(ctx):
    return "\n".join(str(ctx.get(k) or "") for k in ("answer", "stdout", "stderr", "analysis"))


@register("contains_any")
def _contains_any(ctx, p):
    text = _text(ctx)
    return any(s in text for s in p["any"])


@register("contains_all")
def _contains_all(ctx, p):
    text = _text(ctx)
    return all(s in text for s in p["all"])


@register("contains_n_of")
def _contains_n_of(ctx, p):
    text = _text(ctx)
    return sum(1 for s in p["any"] if s in text) >= p["n"]


@register("not_contains")
def _not_contains(ctx, p):
    """禁用词。注意：写完整谓语（"可以使用比特币"），否则会被 "不支持比特币" 命中。"""
    text = _text(ctx)
    return not any(s in text for s in p["any"])


@register("regex")
def _regex(ctx, p):
    return re.search(p["pattern"], _text(ctx), re.S | re.I) is not None


@register("not_regex")
def _not_regex(ctx, p):
    """负向正则：命中即失败（例如答案里不许出现手机号）。"""
    return re.search(p["pattern"], _text(ctx), re.S | re.I) is None


@register("max_len")
def _max_len(ctx, p):
    return len(ctx.get("answer") or "") <= p["n"]


@register("min_len")
def _min_len(ctx, p):
    return len(ctx.get("answer") or "") >= p["n"]


@register("tool_called")
def _tool_called(ctx, p):
    """检索/工具路由：expected=True 必须调用，False 必须不调用；soft=True 时放宽为 NA。"""
    called = [t for t in (ctx.get("tool_calls") or []) if not p.get("name") or t.get("name") == p["name"]]
    got = bool(called)
    if p.get("soft") and got != p["expected"]:
        return None
    return got == p["expected"]


@register("cite_from")
def _cite_from(ctx, p):
    """引用必须来自给定来源之一（子串匹配），且答案里出现「来源」字样。"""
    answer = ctx.get("answer") or ""
    if p.get("require_label", True) and "来源" not in answer:
        return False
    return any(s in answer for s in p["any"])


@register("json_field")
def _json_field(ctx, p):
    """从 ctx['data'] 里取字段比较；字段缺失返回 NA。"""
    data = ctx.get("data")
    if not isinstance(data, dict) or p["field"] not in data:
        return None
    value = data[p["field"]]
    if "equals" in p:
        return value == p["equals"]
    if "ge" in p:
        return value >= p["ge"]
    return None
