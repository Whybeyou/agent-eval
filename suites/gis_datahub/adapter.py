"""GIS 空间数据中台的评测适配器（python 协议）。

为什么每个 case 都建一个临时库：中台是**有状态**系统，用例之间会互相污染
（上一批的 dwd 行数、指标值都会被下一批读到）。所以适配器负责「造环境 → 跑场景 → 收事实」，
让每条 case 从干净状态开始、可独立复现。

平台侧因此不需要支持"多步骤 case"：编排留在领域适配器里，框架保持无状态。
"""
import os
import shutil
import sys
import tempfile

HOME = os.environ.get("GIS_DATAHUB_HOME", "").rstrip("/\\")
if not HOME:
    raise RuntimeError("需要设置 GIS_DATAHUB_HOME 指向 gis-datahub 仓库")
if HOME not in sys.path:
    sys.path.insert(0, HOME)

from hub import config, metrics, pipeline, quality, sampledata, store  # noqa: E402

SCENARIOS = {}


def scenario(fn):
    SCENARIOS[fn.__name__] = fn
    return fn


class Env:
    """一个干净的沙箱环境：独立的 raw 目录 + 独立 sqlite。"""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="datahub_eval_")
        self.raw = os.path.join(self.dir, "raw")
        self.db = os.path.join(self.dir, "hub.sqlite3")
        sampledata.write_all(self.raw)

    def path(self, name):
        return os.path.join(self.raw, name)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _summary(env, res):
    """把一次批次结果里能断言的事实抽出来。"""
    conn = store.connect(env.db)
    counts = store.counts(conn, res["dataset"])
    rows = conn.execute("SELECT __rule, COUNT(*) FROM reject_%s WHERE batch_id = ? GROUP BY __rule"
                        % res["dataset"], (res["batch_id"],)).fetchall()
    conn.close()
    return {"reject_by_rule": {r[0]: r[1] for r in rows}, **counts}


def _metrics_dict(env, metric=None):
    conn = store.connect(env.db)
    rows = metrics.summary(conn, metric)
    conn.close()
    out = {}
    for r in rows:
        if r["key"] == "__all__":
            out[r["metric"]] = r["value"]
    return out


def _metric_groups(env):
    conn = store.connect(env.db)
    rows = metrics.summary(conn)
    conn.close()
    groups = {}
    for r in rows:
        if r["key"] != "__all__":
            groups.setdefault(r["metric"], {})[r["key"]] = r["value"]
    return groups


# ------------------------------------------------------------------ 场景
@scenario
def full_batch():
    """正常批次：两个数据集各跑一次。"""
    env = Env()
    try:
        res = pipeline.run_file(env.path("parcels.geojson"), db=env.db)
        facts = _summary(env, res)
        facts["metrics"] = _metrics_dict(env)
        facts["metric_groups"] = _metric_groups(env)
        for k in ("rows_in", "rows_good", "rows_rejected", "quality_status", "reasons", "load_ok"):
            facts[k] = res[k]
        return {"answer": f"摄取 {res['file']}：行 {res['rows_in']} → 入库 {res['rows_good']}，"
                          f"拒绝 {res['rows_rejected']}（{res['quality_status']}）；"
                          f"原因：{'；'.join(res['reasons'])}",
                "data": facts}
    finally:
        env.close()


@scenario
def rerun_idempotent():
    """同一份文件跑两次：第二次应被幂等跳过，dwd 不增长。"""
    env = Env()
    try:
        first = pipeline.run_file(env.path("parcels.geojson"), db=env.db)
        f1 = _summary(env, first)
        second = pipeline.run_file(env.path("parcels.geojson"), db=env.db)
        f2 = _summary(env, second)
        return {"answer": f"第一次入库 {f1['dwd']} 行；第二次 skipped={second.get('skipped')}，"
                          f"dwd={f2['dwd']} 行",
                "data": {"dwd_rows": f1["dwd"], "rerun_dwd_rows": f2["dwd"],
                         "rerun_skipped": bool(second.get("skipped")),
                         "rows_in": first["rows_in"], "rows_good": first["rows_good"],
                         "rows_rejected": first["rows_rejected"],
                         "quality_status": first["quality_status"], "reasons": first["reasons"]}}
    finally:
        env.close()


@scenario
def incremental_upsert():
    """增量批次：只新增 2 条，主键冲突不产生重复行。"""
    env = Env()
    try:
        pipeline.run_file(env.path("parcels.geojson"), db=env.db)
        res = pipeline.run_file(env.path("parcels_inc.geojson"), db=env.db)
        facts = _summary(env, res)
        facts["metrics"] = _metrics_dict(env)
        return {"answer": f"增量批次入库后 dwd {facts['dwd']} 行（本批 {res['rows_good']} 行）",
                "data": {**facts, "rows_in": res["rows_in"], "rows_good": res["rows_good"],
                         "rows_rejected": res["rows_rejected"], "quality_status": res["quality_status"],
                         "reasons": res["reasons"]}}
    finally:
        env.close()


@scenario
def crs_governance():
    """缺 .prj 的 Shapefile：拒绝入库，而不是默认 WGS84。"""
    env = Env()
    try:
        pipeline.run_file(env.path("parcels.geojson"), db=env.db)
        before = store.counts(store.connect(env.db), "parcels")
        res = pipeline.run_file(env.path("parcels_nocrs.shp"), db=env.db)
        after = store.counts(store.connect(env.db), "parcels")
        return {"answer": f"无 CRS 批次 status={res['quality_status']}，原因：{res['reasons']}",
                "data": {"quality_status": res["quality_status"], "reasons": res["reasons"],
                         "load_ok": res["load_ok"], "crs": res["crs"], "crs_source": res["crs_source"],
                         "dwd_rows": after["dwd"], "dwd_rows_before": before["dwd"],
                         "rows_in": res["rows_in"], "rows_good": res["rows_good"],
                         "rows_rejected": res["rows_rejected"]}}
    finally:
        env.close()


@scenario
def metric_value():
    """指标口径可复算：面积合计 = dwd 中 area_m2 之和 / 1e6。"""
    env = Env()
    try:
        res = pipeline.run_file(env.path("parcels.geojson"), db=env.db)
        facts = _summary(env, res)
        facts["metrics"] = _metrics_dict(env)
        facts["metric_groups"] = _metric_groups(env)
        return {"answer": f"parcels_total_area_km2={facts['metrics'].get('parcels_total_area_km2')} km²",
                "data": {**facts, "rows_in": res["rows_in"], "rows_good": res["rows_good"],
                         "rows_rejected": res["rows_rejected"], "quality_status": res["quality_status"],
                         "reasons": res["reasons"]}}
    finally:
        env.close()


@scenario
def lineage():
    """血缘：指标能追到 dwd 字段、字段能追到源文件。"""
    env = Env()
    try:
        res = pipeline.run_file(env.path("parcels.geojson"), db=env.db)
        conn = store.connect(env.db)
        tree = metrics.lineage_tree(conn, "parcels_total_area_km2")
        fields = conn.execute("SELECT layer, field FROM field_lineage WHERE dataset='parcels' "
                              "LIMIT 10").fetchall()
        conn.close()
        tree["fields"] = tree.get("fields") or []
        tree["fields"] += [{"layer": r[0], "field": r[1]} for r in fields]
        facts = _summary(env, res)
        return {"answer": f"血缘：{len(tree['fields'])} 个字段可追溯",
                "data": {**facts, "lineage": tree, "metrics": _metrics_dict(env),
                         "rows_in": res["rows_in"], "rows_good": res["rows_good"],
                         "rows_rejected": res["rows_rejected"], "quality_status": res["quality_status"],
                         "reasons": res["reasons"]}}
    finally:
        env.close()


@scenario
def empty_batch():
    """空文件：明确 fail，不产出指标。"""
    env = Env()
    try:
        res = pipeline.run_file(env.path("shops_empty.csv"), db=env.db)
        return {"answer": f"空批次 status={res['quality_status']}，原因 {res['reasons']}",
                "data": {"quality_status": res["quality_status"], "reasons": res["reasons"],
                         "load_ok": res["load_ok"], "rows_in": res["rows_in"],
                         "rows_good": res["rows_good"], "rows_rejected": res["rows_rejected"],
                         "metrics": _metrics_dict(env)}}
    finally:
        env.close()


@scenario
def api_contract():
    """服务契约：指标接口字段齐全、可返回数据。"""
    from fastapi.testclient import TestClient

    import hub.api as api_mod

    env = Env()
    try:
        pipeline.run_file(env.path("parcels.geojson"), db=env.db)
        old = os.environ.get("HUB_DB")
        os.environ["HUB_DB"] = env.db
        try:
            client = TestClient(api_mod.app)
            r = client.get("/metrics/summary")
            body = r.json()
            health = client.get("/health").json()
        finally:
            if old is None:
                os.environ.pop("HUB_DB", None)
            else:
                os.environ["HUB_DB"] = old
        return {"answer": f"/metrics/summary 返回 {body.get('count')} 条指标",
                "data": {"api_response": body, "health": health, "http_status": r.status_code}}
    finally:
        env.close()


@scenario
def api_denied():
    """越权：任意 SQL 必须被拒。"""
    from fastapi.testclient import TestClient

    import hub.api as api_mod

    env = Env()
    try:
        pipeline.run_file(env.path("parcels.geojson"), db=env.db)
        old = os.environ.get("HUB_DB")
        os.environ["HUB_DB"] = env.db
        try:
            client = TestClient(api_mod.app)
            r = client.post("/query", json={"sql": "select * from dwd_parcels"})
        finally:
            if old is None:
                os.environ.pop("HUB_DB", None)
            else:
                os.environ["HUB_DB"] = old
        return {"answer": f"任意 SQL 请求返回 {r.status_code}：{r.json().get('detail', '')[:60]}",
                "data": {"http_status": r.status_code, "api_response": r.json()}}
    finally:
        env.close()


@scenario
def unknown_dataset():
    """未知数据集：明确报错，不静默成功。"""
    env = Env()
    try:
        try:
            pipeline.run_file(env.path("cities.geojson").replace("cities", "nonsense"), db=env.db)
            err = None
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        return {"answer": f"未知数据集 -> {err}", "data": {"error": err, "quality_status": "fail"}}
    finally:
        env.close()


def run(turns, case=None):
    case = case or {}
    name = case.get("scenario") or "full_batch"
    if name not in SCENARIOS:
        raise ValueError(f"未知 scenario：{name}")
    return SCENARIOS[name]()
