# -*- coding: utf-8 -*-
"""生成 GIS Agent 评测用的固定数据集（一次性脚本，py39 运行）。

产物写入 ./fixtures/，覆盖：
  正向：规范矢量 / 栅格 / CSV / 大数据量
  边界：空几何+重复ID+缺字段、无 CRS 数据
  负向：0 字节损坏文件、不支持格式
"""
import os
import json
import random

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point, Polygon
import rasterio
from rasterio.transform import from_bounds

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
os.makedirs(FIX, exist_ok=True)
random.seed(42)
np.random.seed(42)

# ---------- 1. 正向：全国城市点（WGS84） ----------
names = ["南昌", "北京", "上海", "广州", "成都", "西安", "武汉", "杭州", "南京", "重庆",
         "长沙", "郑州", "济南", "沈阳", "哈尔滨", "福州", "昆明", "贵阳", "兰州", "西宁",
         "银川", "乌鲁木齐", "拉萨", "呼和浩特", "太原", "石家庄", "合肥", "海口", "南宁", "天津",
         "青岛", "大连", "厦门", "苏州", "无锡", "宁波", "温州", "佛山", "东莞", "珠海",
         "长春", "徐州", "洛阳", "潍坊", "烟台", "常州", "南通", "泉州", "嘉兴", "惠州"]
rows = []
for i, n in enumerate(names):
    rows.append({
        "city_id": f"C{i+1:03d}",
        "name": n,
        "pop_wan": round(random.uniform(50, 2200), 1),
        "area_km2": round(random.uniform(300, 12000), 1),
        "geom_pt": Point(round(random.uniform(75, 133), 5), round(random.uniform(20, 50), 5)),
    })
cities = gpd.GeoDataFrame(rows, geometry="geom_pt", crs="EPSG:4326")
cities.to_file(os.path.join(FIX, "cities.geojson"), driver="GeoJSON")

# ---------- 2. 正向：南昌地块面（CGCS2000 / EPSG:4490） ----------
polys, recs = [], []
for i in range(20):
    x0 = random.uniform(115.80, 115.95)
    y0 = random.uniform(28.60, 28.70)
    d = random.uniform(0.002, 0.004)
    p = Polygon([(x0, y0), (x0 + d, y0), (x0 + d, y0 + d), (x0, y0 + d)])
    polys.append(p)
    recs.append({"parcel_id": f"P{i+1:03d}", "landuse": random.choice(["住宅", "商业", "工业", "绿地"])})
parcels = gpd.GeoDataFrame(recs, geometry=polys, crs="EPSG:4490")
# 近似面积（度→米，1 度 ≈ 111km）
parcels["area_m2"] = (parcels.to_crs(3857).area).round(1)
parcels.to_file(os.path.join(FIX, "parcels_cgcs2000.shp"), encoding="utf-8")

# ---------- 3. 正向：栅格（1 波段，0-255） ----------
arr = np.random.randint(0, 256, size=(1, 120, 120)).astype("uint8")
with rasterio.open(
    os.path.join(FIX, "landuse.tif"), "w", driver="GTiff",
    height=120, width=120, count=1, dtype="uint8", crs="EPSG:4326",
    transform=from_bounds(115.80, 28.60, 116.00, 28.80, 120, 120),
) as dst:
    dst.write(arr)
with rasterio.open(os.path.join(FIX, "landuse.tif")) as src:
    assert src.count == 1 and src.width == 120

# ---------- 4. 正向：CSV（经纬度表格，需转点） ----------
csv_rows = [{
    "shop_id": f"S{i+1:03d}",
    "shop_name": f"门店{i+1}",
    "lng": round(random.uniform(115.80, 116.00), 6),
    "lat": round(random.uniform(28.60, 28.80), 6),
    "monthly_sales": random.randint(1000, 90000),
} for i in range(30)]
pd.DataFrame(csv_rows).to_csv(os.path.join(FIX, "shops.csv"), index=False, encoding="utf-8-sig")

# ---------- 5. 边界：脏数据（空几何 / 重复 ID / 缺字段） ----------
dirty = []
for i in range(12):
    rec = {"road_id": "R001" if i in (3, 7) else f"R{i+1:03d}",
           "width_m": round(random.uniform(3, 30), 1)}
    if i in (5, 9):
        rec["geom_pt"] = None            # 空几何
    else:
        rec["geom_pt"] = Point(round(115.8 + i * 0.01, 5), round(28.6 + i * 0.01, 5))
    if i != 0:
        rec["length_m"] = round(random.uniform(100, 5000), 1)   # 第 0 行缺字段
    dirty.append(rec)
gpd.GeoDataFrame(dirty, geometry="geom_pt", crs="EPSG:4326").to_file(
    os.path.join(FIX, "roads_dirty.geojson"), driver="GeoJSON")

# ---------- 6. 边界：无 CRS 数据 ----------
nocrs = gpd.GeoDataFrame(
    {"fid": [1, 2, 3], "val": [10, 20, 30]},
    geometry=[Point(500000 + i * 100, 3000000 + i * 100) for i in range(3)],
    crs=None,
)
nocrs.to_file(os.path.join(FIX, "no_crs.geojson"), driver="GeoJSON")

# 同一份数据再出一个「丢了 .prj 的 Shapefile」：写出来之后把 .prj 删掉，
# 这样 CI 上重跑也能稳定复现「无 CRS 的 Shapefile」这个场景（否则只剩本地手工文件）。
shp_base = os.path.join(FIX, "no_crs")
nocrs.to_file(shp_base + ".shp", driver="ESRI Shapefile")
prj = shp_base + ".prj"
if os.path.exists(prj):
    os.remove(prj)

# ---------- 7. 性能：2 万点 ----------
big = gpd.GeoDataFrame(
    {"pid": range(20000),
     "score": np.random.randint(0, 100, 20000)},
    geometry=[Point(round(random.uniform(73, 135), 4), round(random.uniform(18, 54), 4)) for _ in range(20000)],
    crs="EPSG:4326",
)
big.to_file(os.path.join(FIX, "big_points.geojson"), driver="GeoJSON")

# ---------- 8. 负向：损坏文件 / 不支持格式 ----------
open(os.path.join(FIX, "broken.geojson"), "wb").close()
with open(os.path.join(FIX, "notes.txt"), "w", encoding="utf-8") as f:
    f.write("这是一份普通文本说明，不是地理数据。\n")

manifest = {
    "cities.geojson": {"rows": int(len(cities)), "crs": "EPSG:4326", "geom": "Point"},
    "parcels_cgcs2000.shp": {"rows": int(len(parcels)), "crs": "EPSG:4490", "geom": "Polygon"},
    "landuse.tif": {"w": 120, "h": 120, "bands": 1, "crs": "EPSG:4326"},
    "shops.csv": {"rows": 30},
    "roads_dirty.geojson": {"rows": 12, "null_geom": 2, "dup_id": 1, "missing_field_row": 1},
    "no_crs.geojson": {"rows": 3, "crs": None},
    "big_points.geojson": {"rows": 20000},
    "broken.geojson": {"size": 0},
    "notes.txt": {"unsupported": True},
}
with open(os.path.join(FIX, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

print(json.dumps(manifest, ensure_ascii=False, indent=2))
print("fixtures written to", FIX)
