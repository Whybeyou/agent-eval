"""数据类断言（给数据中台 / 管道类系统用）。

和"客服类"断言的区别：这里判的都是**数据事实**，没有自然语言可评——
行列数、主键唯一、指标数值、幂等、血缘、接口契约、越权拒绝。
LLM-Judge 在这类系统上作用很小（这也说明评测维度是按系统类型选的）。
"""
from .checks import register


def _data(ctx):
    return ctx.get("data") or {}


@register("reject_breakdown")
def _reject_breakdown(ctx, p):
    """按规则看拒绝分布：params={"expect": {"unique:parcel_id": 1, ...}}"""
    got = _data(ctx).get("reject_by_rule") or {}
    expect = p.get("expect") or {}
    return all(int(got.get(k, 0)) == int(v) for k, v in expect.items())


@register("metric_close")
def _metric_close(ctx, p):
    """指标数值比较（相对容差）：params={"name": "...", "expect": 0.0094, "tol": 1e-3}"""
    metrics = _data(ctx).get("metrics") or {}
    if p["name"] not in metrics:
        return None
    got = float(metrics[p["name"]])
    exp = float(p["expect"])
    if exp == 0:
        return abs(got) <= p.get("tol", 1e-6)
    return abs(got - exp) / abs(exp) <= p.get("tol", 1e-3)


@register("metric_keys")
def _metric_keys(ctx, p):
    """指标的分组键集合（如 by_landuse 的分组名）。"""
    groups = _data(ctx).get("metric_groups") or {}
    keys = set((groups.get(p["name"]) or {}).keys())
    return set(p.get("has", [])).issubset(keys)


@register("idempotent")
def _idempotent(ctx, p):
    """重跑后 dwd 行数不变。"""
    d = _data(ctx)
    if d.get("rerun_dwd_rows") is None:
        return None
    return int(d["rerun_dwd_rows"]) == int(d.get("dwd_rows") or 0)


@register("http_status")
def _http_status(ctx, p):
    """接口状态码断言（用于「越权必须被拒」）。"""
    d = _data(ctx)
    if d.get("http_status") is None:
        return None
    return int(d["http_status"]) in [int(x) for x in p["in"]]


@register("api_shape")
def _api_shape(ctx, p):
    """接口返回必须包含某些字段（契约稳定）。"""
    body = _data(ctx).get("api_response")
    if not isinstance(body, dict):
        return None
    return all(k in body for k in p["keys"])


@register("lineage_has")
def _lineage_has(ctx, p):
    """血缘可追溯：指标血缘里必须出现这些字段。"""
    lin = _data(ctx).get("lineage") or {}
    fields = {(f.get("layer"), f.get("field")) for f in (lin.get("fields") or [])}
    want = {(x.split(".")[0], x.split(".")[1]) for x in p["fields"]}
    return want.issubset(fields)


@register("no_metric")
def _no_metric(ctx, p):
    """失败批次不该产出指标。"""
    metrics = _data(ctx).get("metrics") or {}
    return not any(k.startswith(p["prefix"]) for k in metrics)
