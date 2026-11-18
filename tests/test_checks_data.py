"""数据类断言（reject_breakdown / metric_close / idempotent / http_status / lineage_has …）自测。

这些断言服务的是"数据管道"型系统：判的是数据事实，不是自然语言。
写错的代价很高——比如把 metric_close 的容差写成绝对值，0.0044 和 0.0094 都能"通过"。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evalkit  # noqa: E402


def _ctx(**data):
    return {"answer": "", "tool_calls": [], "data": data}


def test_reject_breakdown_exact_counts():
    ctx = _ctx(reject_by_rule={"unique:parcel_id": 1, "geom_valid": 1, "range:area_m2": 1})
    assert evalkit.check("reject_breakdown", ctx,
                         {"expect": {"unique:parcel_id": 1, "geom_valid": 1}}) is True
    assert evalkit.check("reject_breakdown", ctx,
                         {"expect": {"unique:parcel_id": 2}}) is False


def test_metric_close_uses_relative_tolerance():
    ctx = _ctx(metrics={"parcels_total_area_km2": 0.0044})
    assert evalkit.check("metric_close", ctx, {"name": "parcels_total_area_km2",
                                               "expect": 0.0044, "tol": 1e-3}) is True
    # 差一倍必须判失败（容差是相对的，不是绝对）
    assert evalkit.check("metric_close", ctx, {"name": "parcels_total_area_km2",
                                               "expect": 0.0088, "tol": 1e-3}) is False
    # 指标不存在 → NA，不参与打分
    assert evalkit.check("metric_close", ctx, {"name": "not_there", "expect": 1}) is None


def test_metric_keys_and_idempotent():
    ctx = _ctx(metric_groups={"parcels_by_landuse": {"住宅": 1, "商业": 1, "绿地": 1}},
               dwd_rows=3, rerun_dwd_rows=3)
    assert evalkit.check("metric_keys", ctx, {"name": "parcels_by_landuse",
                                              "has": ["住宅", "绿地"]}) is True
    assert evalkit.check("idempotent", ctx, {}) is True
    ctx2 = _ctx(dwd_rows=3, rerun_dwd_rows=5)
    assert evalkit.check("idempotent", ctx2, {}) is False


def test_http_status_and_shape_and_lineage():
    ctx = _ctx(http_status=403, api_response={"metric": None, "count": 4, "items": []},
               lineage={"fields": [{"layer": "dwd_parcels", "field": "area_m2"}]})
    assert evalkit.check("http_status", ctx, {"in": [401, 403]}) is True
    assert evalkit.check("http_status", ctx, {"in": [200]}) is False
    assert evalkit.check("api_shape", ctx, {"keys": ["metric", "count"]}) is True
    assert evalkit.check("lineage_has", ctx, {"fields": ["dwd_parcels.area_m2"]}) is True
    assert evalkit.check("lineage_has", ctx, {"fields": ["dwd_cities.pop_wan"]}) is False


def test_no_metric_on_failed_batch():
    assert evalkit.check("no_metric", _ctx(metrics={"shops_sales_by_city": 1}), {"prefix": "shops_"}) is False
    assert evalkit.check("no_metric", _ctx(metrics={}), {"prefix": "shops_"}) is True
