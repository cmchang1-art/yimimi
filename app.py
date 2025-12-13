# ==========================================================
# 3D 裝箱系統（穩定版 / Google Sheet 儲存 / 50-50 & 垂直切換）
# - 表格左側「選取」勾選刪除（移除最後一欄刪除）
# - 表格高度至少 8 行
# - Google Sheet 讀/寫：箱型模板、商品模板（透過 Apps Script WebApp）
# - 3D：Plotly 顯示 + 旋轉(6向) + 多策略排序挑最佳
# ==========================================================

import os
import json
import math
import datetime
from itertools import permutations
from typing import Dict, List, Tuple, Any, Optional

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# 盡量用 requests（Streamlit Cloud 通常都有）；沒有就 fallback urllib
try:
    import requests  # type: ignore
except Exception:
    requests = None  # type: ignore

from urllib import request as _urlreq
from urllib.error import URLError

# ==========================
# 基本設定
# ==========================
st.set_page_config(page_title="3D裝箱系統", page_icon="📦", layout="wide")

# ==========================
# Secrets（Streamlit Cloud → Settings → Secrets）
# ==========================
GS_WEBAPP_URL = st.secrets.get("GS_WEBAPP_URL", "").strip()
GS_TOKEN = st.secrets.get("GS_TOKEN", "").strip()

# ==========================
# UI / CSS（按鈕顏色用 aria-label 精準指定）
# ==========================
PRIMARY = "#2563EB"   # 藍
GREEN   = "#16A34A"   # 綠
RED     = "#DC2626"   # 紅
GRAY    = "#6B7280"   # 灰
PURPLE  = "#7C3AED"   # 紫

CSS = f"""
<style>
/* 全域 */
.block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1600px; }}
h1, h2, h3 {{ letter-spacing: -0.02em; }}
hr {{ border: none; border-top: 1px solid #E5E7EB; margin: 14px 0; }}

.section-title {{
  font-weight: 900;
  font-size: 1.05rem;
  margin: 2px 0 10px 0;
  padding-left: 10px;
  border-left: 4px solid #EF4444;
}}

.panel {{
  border: 1px solid #E5E7EB;
  background: #FFFFFF;
  border-radius: 16px;
  padding: 14px 14px 10px 14px;
  box-shadow: 0 6px 18px rgba(0,0,0,.04);
}}

.muted {{
  color: #6B7280;
  font-size: 0.92rem;
}}

.smallnote {{
  color:#6B7280;
  font-size:0.88rem;
  margin-top:-4px;
}}

.badge {{
  display:inline-block;
  padding:6px 10px;
  border-radius:999px;
  font-weight:900;
  font-size:0.9rem;
  border:1px solid #E5E7EB;
  background:#F9FAFB;
}}

/* ===== 按鈕顏色：用 aria-label 精準命中（你要的「確實照指定顏色」） ===== */
button[aria-label="🚀 開始計算與 3D 模擬"] {{
  background: {PRIMARY} !important;
  color: white !important;
  border: 1px solid {PRIMARY} !important;
}}

button[aria-label="💾 儲存商品模板"] {{
  background: {GREEN} !important;
  color: white !important;
  border: 1px solid {GREEN} !important;
}}
button[aria-label="⬇️ 載入商品模板"] {{
  background: {PRIMARY} !important;
  color: white !important;
  border: 1px solid {PRIMARY} !important;
}}
button[aria-label="🗑 刪除商品模板"] {{
  background: {RED} !important;
  color: white !important;
  border: 1px solid {RED} !important;
}}

button[aria-label="💾 儲存箱型模板"] {{
  background: {GREEN} !important;
  color: white !important;
  border: 1px solid {GREEN} !important;
}}
button[aria-label="⬇️ 載入箱型模板"] {{
  background: {PRIMARY} !important;
  color: white !important;
  border: 1px solid {PRIMARY} !important;
}}
button[aria-label="🗑 刪除箱型模板"] {{
  background: {RED} !important;
  color: white !important;
  border: 1px solid {RED} !important;
}}

button[aria-label="🧹 清除全部資料"] {{
  background: {GRAY} !important;
  color: white !important;
  border: 1px solid {GRAY} !important;
}}

button[aria-label="🗑 刪除勾選箱型"] {{
  background: {RED} !important;
  color: white !important;
  border: 1px solid {RED} !important;
}}
button[aria-label="🗑 刪除勾選商品"] {{
  background: {RED} !important;
  color: white !important;
  border: 1px solid {RED} !important;
}}

button[aria-label="✅ 套用變更（更新目前模板）"] {{
  background: {PURPLE} !important;
  color: white !important;
  border: 1px solid {PURPLE} !important;
}}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ==========================
# Google Sheet API（Apps Script WebApp）
# ==========================
def gs_call(action: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """POST JSON to Apps Script WebApp: {token, action, ...payload} -> {ok, data, message}"""
    if payload is None:
        payload = {}
    if not GS_WEBAPP_URL or not GS_TOKEN:
        return {"ok": False, "message": "尚未設定 GS_WEBAPP_URL / GS_TOKEN（請到 Secrets）"}

    body = {"token": GS_TOKEN, "action": action, **payload}
    data = json.dumps(body).encode("utf-8")

    try:
        if requests:
            r = requests.post(GS_WEBAPP_URL, json=body, timeout=20)
            return r.json()
        else:
            req = _urlreq.Request(
                GS_WEBAPP_URL,
                data=data,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with _urlreq.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
    except URLError as e:
        return {"ok": False, "message": f"連線失敗：{e}"}
    except Exception as e:
        return {"ok": False, "message": f"發生錯誤：{e}"}

# ==========================
# 工具
# ==========================
def _to_float(x, default=0.0) -> float:
    try:
        if x is None or x == "":
            return float(default)
        return float(x)
    except Exception:
        return float(default)

def _to_int(x, default=0) -> int:
    try:
        if x is None or x == "":
            return int(default)
        return int(float(x))
    except Exception:
        return int(default)

def _now_tw() -> datetime.datetime:
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)

def _norm_box_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["選取", "使用", "名稱", "長", "寬", "高", "數量", "空箱重量"]
    for c in cols:
        if c not in df.columns:
            df[c] = False if c in ["選取", "使用"] else ""
    df = df[cols].copy()
    # 型別修正
    df["選取"] = df["選取"].fillna(False).astype(bool)
    df["使用"] = df["使用"].fillna(False).astype(bool)
    df["名稱"] = df["名稱"].fillna("").astype(str)
    for c in ["長", "寬", "高", "空箱重量"]:
        df[c] = df[c].apply(lambda v: _to_float(v, 0.0))
    df["數量"] = df["數量"].apply(lambda v: max(0, _to_int(v, 0)))
    return df

def _norm_prod_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["選取", "啟用", "商品名稱", "長", "寬", "高", "重量(kg)", "數量"]
    for c in cols:
        if c not in df.columns:
            df[c] = False if c in ["選取", "啟用"] else ""
    df = df[cols].copy()
    df["選取"] = df["選取"].fillna(False).astype(bool)
    df["啟用"] = df["啟用"].fillna(True).astype(bool)
    df["商品名稱"] = df["商品名稱"].fillna("").astype(str)
    for c in ["長", "寬", "高", "重量(kg)"]:
        df[c] = df[c].apply(lambda v: _to_float(v, 0.0))
    df["數量"] = df["數量"].apply(lambda v: max(0, _to_int(v, 0)))
    return df

# ==========================
# Session 初始化（只做一次，避免「要按兩次 / 回復原狀」）
# ==========================
def init_state():
    if st.session_state.get("_inited"):
        return

    # 預設資料
    default_boxes = pd.DataFrame([
        {"選取": False, "使用": True, "名稱": "A款", "長": 45.0, "寬": 30.0, "高": 30.0, "數量": 1, "空箱重量": 0.50},
    ])
    default_products = pd.DataFrame([
        {"選取": False, "啟用": True, "商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.50, "數量": 5},
        {"選取": False, "啟用": True, "商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5},
    ])

    st.session_state.order_name = st.session_state.get("order_name", "訂單_20241208")

    st.session_state.manual_use = st.session_state.get("manual_use", True)
    st.session_state.manual_name = st.session_state.get("manual_name", "手動箱")
    st.session_state.manual_L = st.session_state.get("manual_L", 35.0)
    st.session_state.manual_W = st.session_state.get("manual_W", 25.0)
    st.session_state.manual_H = st.session_state.get("manual_H", 20.0)
    st.session_state.manual_qty = st.session_state.get("manual_qty", 1)
    st.session_state.manual_box_weight = st.session_state.get("manual_box_weight", 0.5)

    st.session_state.layout_mode = st.session_state.get("layout_mode", "左右 50% / 50%")

    # Google Sheet 讀取（失敗就用預設）
    box_df = None
    prod_df = None
    box_tpl_list = []
    prod_tpl_list = []

    # 讀模板清單
    r1 = gs_call("list_templates", {"kind": "box"})
    if r1.get("ok"):
        box_tpl_list = r1.get("templates", []) or r1.get("data", {}).get("templates", []) or []
    r2 = gs_call("list_templates", {"kind": "product"})
    if r2.get("ok"):
        prod_tpl_list = r2.get("templates", []) or r2.get("data", {}).get("templates", []) or []

    # 讀「目前資料」
    r3 = gs_call("get_current", {})
    if r3.get("ok"):
        data = r3.get("data", r3)
        # 允許多種回傳格式
        if "boxes" in data:
            try:
                box_df = pd.DataFrame(data["boxes"])
            except Exception:
                box_df = None
        if "products" in data:
            try:
                prod_df = pd.DataFrame(data["products"])
            except Exception:
                prod_df = None

        st.session_state._current_box_tpl = data.get("current_box_template", "")
        st.session_state._current_prod_tpl = data.get("current_product_template", "")

    st.session_state.box_df = _norm_box_df(box_df if box_df is not None and len(box_df) else default_boxes)
    st.session_state.prod_df = _norm_prod_df(prod_df if prod_df is not None and len(prod_df) else default_products)

    st.session_state.box_templates = sorted(list(set(box_tpl_list)))
    st.session_state.prod_templates = sorted(list(set(prod_tpl_list)))

    st.session_state._inited = True

init_state()

# ==========================
# 裝箱核心（6 向旋轉 + 多策略排序挑最佳）
# ==========================
def orientations(dx: float, dy: float, dz: float) -> List[Tuple[float, float, float]]:
    # 6 種方向
    perms = set(permutations([dx, dy, dz], 3))
    return [(float(a), float(b), float(c)) for a, b, c in perms]

def can_fit_in_bin(item_dim: Tuple[float, float, float], bin_dim: Tuple[float, float, float]) -> bool:
    a, b, c = item_dim
    L, W, H = bin_dim
    return a <= L + 1e-9 and b <= W + 1e-9 and c <= H + 1e-9

def pack_simple_heuristic(
    bin_dim: Tuple[float, float, float],
    items: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    簡化穩定的 3D 放置：
    - 以「候選點」(0,0,0) 開始
    - 每放一個物件，新增三個候選點 (x+dx,y,z), (x,y+dy,z), (x,y,z+dz)
    - 針對每個物件測 6 向旋轉，找最先能放且最靠近原點的位置（更容易填滿）
    """
    L, W, H = bin_dim
    placed: List[Dict[str, Any]] = []
    remaining: List[Dict[str, Any]] = []

    # 候選點
    points: List[Tuple[float, float, float]] = [(0.0, 0.0, 0.0)]

    def collide(p: Dict[str, Any], q: Dict[str, Any]) -> bool:
        # AABB 碰撞
        return not (
            p["x"] + p["dx"] <= q["x"] or q["x"] + q["dx"] <= p["x"] or
            p["y"] + p["dy"] <= q["y"] or q["y"] + q["dy"] <= p["y"] or
            p["z"] + p["dz"] <= q["z"] or q["z"] + q["dz"] <= p["z"]
        )

    for it in items:
        best = None

        # points 排序：先靠近(0,0,0)（更緊密），再 z（讓它優先「往上」堆疊）
        pts = sorted(points, key=lambda p: (p[0] + p[1] + p[2], p[2], p[1], p[0]))

        for (px, py, pz) in pts:
            for (dx, dy, dz) in orientations(it["dx"], it["dy"], it["dz"]):
                if px + dx > L + 1e-9 or py + dy > W + 1e-9 or pz + dz > H + 1e-9:
                    continue

                trial = {"name": it["name"], "weight": it["weight"], "x": px, "y": py, "z": pz, "dx": dx, "dy": dy, "dz": dz}
                ok = True
                for p0 in placed:
                    if collide(trial, p0):
                        ok = False
                        break
                if ok:
                    best = trial
                    break
            if best:
                break

        if best:
            placed.append(best)
            # 新候選點
            points.append((best["x"] + best["dx"], best["y"], best["z"]))
            points.append((best["x"], best["y"] + best["dy"], best["z"]))
            points.append((best["x"], best["y"], best["z"] + best["dz"]))

            # 去掉超界點
            points = [(x, y, z) for (x, y, z) in points if x <= L + 1e-9 and y <= W + 1e-9 and z <= H + 1e-9]
            # 去重（避免爆炸）
            points = list(dict.fromkeys([(round(x, 6), round(y, 6), round(z, 6)) for (x, y, z) in points]))
            points = [(float(x), float(y), float(z)) for (x, y, z) in points]
        else:
            remaining.append(it)

    return placed, remaining

def multi_strategy_pack(
    bin_dim: Tuple[float, float, float],
    items: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    你要求「能直放/橫放/平放更智慧」：
    - 同一批 items 用多種排序策略跑 pack_simple_heuristic
    - 取「遺漏最少」優先，其次「體積利用率最大」
    """
    def volume(it): return it["dx"] * it["dy"] * it["dz"]

    strategies = [
        ("vol_desc", sorted(items, key=volume, reverse=True)),
        ("max_edge_desc", sorted(items, key=lambda it: max(it["dx"], it["dy"], it["dz"]), reverse=True)),
        ("height_desc", sorted(items, key=lambda it: it["dz"], reverse=True)),
        ("weight_desc", sorted(items, key=lambda it: it["weight"], reverse=True)),
    ]

    best_placed, best_rem = [], items
    best_score = (-10**9, -10**9)  # (fitted_count, used_volume)

    for _, seq in strategies:
        placed, rem = pack_simple_heuristic(bin_dim, seq)
        fitted = len(placed)
        used_v = sum(p["dx"] * p["dy"] * p["dz"] for p in placed)

        score = (fitted, used_v)
        if score > best_score:
            best_score = score
            best_placed, best_rem = placed, rem

    return best_placed, best_rem

# ==========================
# Build items / bins
# ==========================
def build_candidate_bins() -> List[Dict[str, Any]]:
    bins: List[Dict[str, Any]] = []

    # 手動箱
    if st.session_state.manual_use and st.session_state.manual_qty > 0:
        bins.append({
            "名稱": st.session_state.manual_name,
            "長": float(st.session_state.manual_L),
            "寬": float(st.session_state.manual_W),
            "高": float(st.session_state.manual_H),
            "數量": int(st.session_state.manual_qty),
            "空箱重量": float(st.session_state.manual_box_weight),
        })

    # 預存箱
    dfb = _norm_box_df(st.session_state.box_df)
    for _, r in dfb.iterrows():
        if bool(r["使用"]) and int(r["數量"]) > 0:
            bins.append({
                "名稱": str(r["名稱"]),
                "長": float(r["長"]),
                "寬": float(r["寬"]),
                "高": float(r["高"]),
                "數量": int(r["數量"]),
                "空箱重量": float(r["空箱重量"]),
            })

    return bins

def build_items() -> Tuple[List[Dict[str, Any]], Dict[str, int], List[str], int]:
    dfp = _norm_prod_df(st.session_state.prod_df)
    items: List[Dict[str, Any]] = []
    req: Dict[str, int] = {}
    unique_names: List[str] = []
    total_qty = 0

    for _, r in dfp.iterrows():
        if not bool(r["啟用"]):
            continue
        name = str(r["商品名稱"]).strip()
        if not name:
            continue
        qty = int(r["數量"])
        if qty <= 0:
            continue

        dx, dy, dz = float(r["長"]), float(r["寬"]), float(r["高"])
        w = float(r["重量(kg)"])
        if dx <= 0 or dy <= 0 or dz <= 0:
            continue

        if name not in unique_names:
            unique_names.append(name)

        req[name] = req.get(name, 0) + qty
        total_qty += qty

        for _i in range(qty):
            items.append({"name": name, "dx": dx, "dy": dy, "dz": dz, "weight": w})

    return items, req, unique_names, total_qty

def expand_bins_inventory(bins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    inv: List[Dict[str, Any]] = []
    for b in bins:
        for _ in range(int(b["數量"])):
            inv.append({k: b[k] for k in b if k != "數量"})
    # 先用大箱（更容易一次裝完）
    inv.sort(key=lambda x: x["長"] * x["寬"] * x["高"], reverse=True)
    return inv

# ==========================
# Packing with inventory
# ==========================
def pack_with_inventory(items: List[Dict[str, Any]], bins: List[Dict[str, Any]]):
    inv = expand_bins_inventory(bins)
    remaining = items[:]
    all_bins_result: List[List[Dict[str, Any]]] = []
    used_bins: List[Dict[str, Any]] = []

    for b in inv:
        if not remaining:
            break
        bin_dim = (float(b["長"]), float(b["寬"]), float(b["高"]))
        placed, rem = multi_strategy_pack(bin_dim, remaining)
        if placed:
            all_bins_result.append(placed)
            used_bins.append(b)
            remaining = rem

    return all_bins_result, used_bins, remaining

# ==========================
# Plotly 3D
# ==========================
def build_figure(bins_used: List[Dict[str, Any]], bins_result: List[List[Dict[str, Any]]], unique_products: List[str]) -> go.Figure:
    fig = go.Figure()

    axis_config = dict(
        backgroundcolor="white", showbackground=True,
        zerolinecolor="#000000", gridcolor="#999999",
        linecolor="#000000", showgrid=True, showline=True,
        tickfont=dict(color="black", size=12, family="Arial Black"),
        title=dict(font=dict(color="black", size=14, family="Arial Black")),
    )

    fig.update_layout(
        template=None,
        paper_bgcolor="white",
        plot_bgcolor="white",
        font=dict(color="black"),
        autosize=True,
        scene=dict(
            bgcolor="white",
            xaxis={**axis_config, "title": "長 (L)"},
            yaxis={**axis_config, "title": "寬 (W)"},
            zaxis={**axis_config, "title": "高 (H)"},
            aspectmode="data",
            camera=dict(eye=dict(x=1.6, y=1.6, z=1.6)),
        ),
        margin=dict(t=25, b=0, l=0, r=0),
        height=640,
        legend=dict(
            x=0, y=1, xanchor="left", yanchor="top",
            font=dict(color="black", size=13),
            bgcolor="rgba(255,255,255,0.90)",
            bordercolor="#000000", borderwidth=1,
        ),
    )

    palette = ["#FF5733", "#33FF57", "#3357FF", "#F1C40F", "#8E44AD", "#00FFFF", "#FF00FF", "#E74C3C", "#2ECC71", "#3498DB"]
    product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

    def draw_box(offset_x, L, W, H, label):
        fig.add_trace(go.Scatter3d(
            x=[offset_x+0, offset_x+L, offset_x+L, offset_x+0, offset_x+0, offset_x+0, offset_x+L, offset_x+L, offset_x+0, offset_x+0, offset_x+0, offset_x+0, offset_x+L, offset_x+L, offset_x+L, offset_x+L],
            y=[0, 0, W, W, 0, 0, 0, W, W, 0, 0, W, W, 0, 0, W],
            z=[0, 0, 0, 0, 0, H, H, H, H, H, 0, H, H, H, 0, 0],
            mode="lines",
            line=dict(color="#000000", width=6),
            name=label
        ))

    offsets = []
    cur_x = 0.0
    gap = 8.0
    for b in bins_used:
        offsets.append(cur_x)
        cur_x += float(b["長"]) + gap

    for bi, placed in enumerate(bins_result):
        bdef = bins_used[bi]
        ox = offsets[bi]
        label = f'外箱_{bi+1} ({bdef["名稱"]})'
        draw_box(ox, bdef["長"], bdef["寬"], bdef["高"], label)

        for it in placed:
            name = it["name"]
            color = product_colors.get(name, "#888")
            x, y, z = it["x"], it["y"], it["z"]
            dx, dy, dz = it["dx"], it["dy"], it["dz"]

            fig.add_trace(go.Mesh3d(
                x=[ox+x, ox+x+dx, ox+x+dx, ox+x, ox+x, ox+x+dx, ox+x+dx, ox+x],
                y=[y, y, y+dy, y+dy, y, y, y+dy, y+dy],
                z=[z, z, z, z, z+dz, z+dz, z+dz, z+dz],
                i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
                j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
                k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                color=color, opacity=1, name=name, showlegend=True
            ))

            fig.add_trace(go.Scatter3d(
                x=[ox+x, ox+x+dx, ox+x+dx, ox+x, ox+x, ox+x, ox+x+dx, ox+x+dx, ox+x, ox+x, ox+x, ox+x, ox+x+dx, ox+x+dx, ox+x+dx, ox+x+dx],
                y=[y, y, y+dy, y+dy, y, y, y, y, y+dy, y+dy, y, y+dy, y+dy, y, y, y+dy],
                z=[z, z, z, z, z, z+dz, z+dz, z+dz, z+dz, z+dz, z, z+dz, z+dz, z+dz, z, z],
                mode="lines", line=dict(color="#000000", width=2),
                showlegend=False
            ))

    # legend 去重
    names = set()
    fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))
    return fig

# ==========================
# Header
# ==========================
st.markdown("## 📦 3D裝箱系統")

# ==========================
# Layout toggle（你要的「像以前那種切換」：左右/上下）
# ==========================
layout_mode = st.radio(
    "版面配置",
    ["左右 50% / 50%", "上下（垂直）"],
    horizontal=True,
    index=0 if st.session_state.layout_mode == "左右 50% / 50%" else 1,
    key="layout_mode",
)
st.session_state.layout_mode = layout_mode

# ==========================
# 操作列（清除）
# ==========================
colA, colB, colC = st.columns([2, 4, 2])
with colA:
    st.button("🧹 清除全部資料", key="btn_clear_all", use_container_width=True)

with colB:
    # 顯示目前套用模板提示
    cb = (st.session_state.get("_current_box_tpl") or "").strip()
    cp = (st.session_state.get("_current_prod_tpl") or "").strip()
    msg = "目前未套用模板"
    if cb or cp:
        msg = f"目前模板：箱型「{cb or '-'}」／商品「{cp or '-'}」"
    st.markdown(f'<span class="badge">{msg}</span>', unsafe_allow_html=True)

with colC:
    st.button("✅ 套用變更（更新目前模板）", key="btn_apply_update", use_container_width=True)

# 清除：回到預設空/基本值
if st.session_state.get("btn_clear_all"):
    st.session_state.box_df = _norm_box_df(pd.DataFrame([]))
    st.session_state.prod_df = _norm_prod_df(pd.DataFrame([]))
    st.session_state.order_name = "訂單_20241208"
    st.session_state._current_box_tpl = ""
    st.session_state._current_prod_tpl = ""
    # 同步到 Google Sheet（可選：也清空 current）
    gs_call("set_current", {"boxes": [], "products": [], "current_box_template": "", "current_product_template": ""})
    st.toast("已清除全部資料", icon="🧹")

# 套用變更：更新目前模板（若目前模板名稱存在）
if st.session_state.get("btn_apply_update"):
    cb = (st.session_state.get("_current_box_tpl") or "").strip()
    cp = (st.session_state.get("_current_prod_tpl") or "").strip()
    ok_any = False

    if cb:
        r = gs_call("save_template", {"kind": "box", "name": cb, "rows": st.session_state.box_df.to_dict(orient="records")})
        ok_any = ok_any or bool(r.get("ok"))
    if cp:
        r = gs_call("save_template", {"kind": "product", "name": cp, "rows": st.session_state.prod_df.to_dict(orient="records")})
        ok_any = ok_any or bool(r.get("ok"))

    # 同步 current
    gs_call("set_current", {
        "boxes": st.session_state.box_df.to_dict(orient="records"),
        "products": st.session_state.prod_df.to_dict(orient="records"),
        "current_box_template": cb,
        "current_product_template": cp,
    })

    st.toast("已套用變更並更新目前模板" if ok_any else "已套用變更", icon="✅")

# ==========================
# Section 1：訂單與外箱
# ==========================
def render_box_section():
    st.markdown('<div class="section-title">1. 訂單與外箱設定</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)

    st.text_input("訂單名稱", value=st.session_state.order_name, key="order_name")
    st.session_state.order_name = st.session_state.order_name

    st.caption("外箱尺寸 (cm) - 手動 Key in（可選擇是否參與裝箱）")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.number_input("長", value=float(st.session_state.manual_L), step=1.0, key="manual_L")
    with c2:
        st.number_input("寬", value=float(st.session_state.manual_W), step=1.0, key="manual_W")
    with c3:
        st.number_input("高", value=float(st.session_state.manual_H), step=1.0, key="manual_H")

    st.number_input("空箱重量 (kg)", value=float(st.session_state.manual_box_weight), step=0.1, key="manual_box_weight")

    c4, c5, c6 = st.columns([1, 1, 2])
    with c4:
        st.checkbox("使用手動箱", value=bool(st.session_state.manual_use), key="manual_use")
    with c5:
        st.number_input("手動箱數量", value=int(st.session_state.manual_qty), step=1, min_value=0, key="manual_qty")
    with c6:
        st.text_input("手動箱命名", value=st.session_state.manual_name, key="manual_name")

    st.markdown("<hr>", unsafe_allow_html=True)

    # 箱型模板區（按你要求：欄位 + 按鈕全部放一起）
    st.markdown("### 箱型模板（載入 / 儲存 / 刪除）")

    tpl_names = ["(無)"] + (st.session_state.box_templates or [])
    cL, cM, cR = st.columns([2, 2, 2], gap="large")

    with cL:
        st.selectbox("選擇模板", tpl_names, key="box_tpl_sel")
        st.text_input("另存為模板名稱", value=st.session_state.get("box_tpl_save_name", ""), placeholder="例如：常用箱型A", key="box_tpl_save_name")

    with cM:
        st.button("⬇️ 載入箱型模板", key="btn_box_tpl_load", use_container_width=True)
        st.button("💾 儲存箱型模板", key="btn_box_tpl_save", use_container_width=True)

    with cR:
        st.selectbox("要刪除的模板", tpl_names, key="box_tpl_del_sel")
        st.button("🗑 刪除箱型模板", key="btn_box_tpl_del", use_container_width=True)

    st.markdown("<div class='smallnote'>提示：載入會覆蓋目前箱型表格；儲存會寫入 Google Sheet。</div>", unsafe_allow_html=True)

    # 模板操作
    if st.session_state.get("btn_box_tpl_load"):
        nm = st.session_state.get("box_tpl_sel", "(無)")
        if nm == "(無)":
            st.warning("請先選擇要載入的箱型模板")
        else:
            r = gs_call("load_template", {"kind": "box", "name": nm})
            if r.get("ok"):
                rows = r.get("rows") or r.get("data", {}).get("rows") or []
                st.session_state.box_df = _norm_box_df(pd.DataFrame(rows))
                st.session_state._current_box_tpl = nm
                gs_call("set_current", {
                    "boxes": st.session_state.box_df.to_dict(orient="records"),
                    "products": st.session_state.prod_df.to_dict(orient="records"),
                    "current_box_template": nm,
                    "current_product_template": st.session_state.get("_current_prod_tpl", ""),
                })
                st.toast("已載入箱型模板", icon="⬇️")
            else:
                st.error(r.get("message", "載入失敗"))

    if st.session_state.get("btn_box_tpl_save"):
        nm = (st.session_state.get("box_tpl_save_name") or "").strip()
        if not nm:
            st.warning("請輸入『另存為模板名稱』再儲存")
        else:
            r = gs_call("save_template", {"kind": "box", "name": nm, "rows": st.session_state.box_df.to_dict(orient="records")})
            if r.get("ok"):
                st.session_state._current_box_tpl = nm
                # 刷新清單
                r2 = gs_call("list_templates", {"kind": "box"})
                if r2.get("ok"):
                    st.session_state.box_templates = sorted(list(set(r2.get("templates", []) or [])))
                gs_call("set_current", {
                    "boxes": st.session_state.box_df.to_dict(orient="records"),
                    "products": st.session_state.prod_df.to_dict(orient="records"),
                    "current_box_template": nm,
                    "current_product_template": st.session_state.get("_current_prod_tpl", ""),
                })
                st.toast("已儲存箱型模板", icon="💾")
            else:
                st.error(r.get("message", "儲存失敗"))

    if st.session_state.get("btn_box_tpl_del"):
        nm = st.session_state.get("box_tpl_del_sel", "(無)")
        if nm == "(無)":
            st.warning("請先選擇要刪除的箱型模板")
        else:
            r = gs_call("delete_template", {"kind": "box", "name": nm})
            if r.get("ok"):
                # 刷新清單
                r2 = gs_call("list_templates", {"kind": "box"})
                if r2.get("ok"):
                    st.session_state.box_templates = sorted(list(set(r2.get("templates", []) or [])))
                # 若刪的是目前模板，清空
                if (st.session_state.get("_current_box_tpl") or "") == nm:
                    st.session_state._current_box_tpl = ""
                st.toast("已刪除箱型模板", icon="🗑")
            else:
                st.error(r.get("message", "刪除失敗"))

    st.markdown("<hr>", unsafe_allow_html=True)

    st.markdown("### 箱型管理（新增 / 修改 / 勾選使用 / 勾選刪除）")
    st.markdown("<div class='muted'>左側勾選『選取』後可一鍵刪除；不需要最後一欄刪除。</div>", unsafe_allow_html=True)

    # 新增箱型（用 form，避免「按一次會回復」）
    with st.form("form_add_box", clear_on_submit=False):
        cc1, cc2, cc3, cc4 = st.columns([2, 1, 1, 1], gap="medium")
        with cc1:
            new_name = st.text_input("新箱型名稱", value=st.session_state.get("new_box_name", ""), placeholder="例如：B款", key="new_box_name")
        with cc2:
            newL = st.number_input("新箱_長", value=float(st.session_state.get("newL", 45.0)), step=1.0, min_value=0.0, key="newL")
        with cc3:
            newW = st.number_input("新箱_寬", value=float(st.session_state.get("newW", 30.0)), step=1.0, min_value=0.0, key="newW")
        with cc4:
            newH = st.number_input("新箱_高", value=float(st.session_state.get("newH", 30.0)), step=1.0, min_value=0.0, key="newH")

        cc5, cc6, cc7 = st.columns([1, 1, 2], gap="medium")
        with cc5:
            newQty = st.number_input("新箱_數量", value=int(st.session_state.get("newQty", 1)), step=1, min_value=0, key="newQty")
        with cc6:
            newBW = st.number_input("新箱_空箱重(kg)", value=float(st.session_state.get("newBW", 0.5)), step=0.1, min_value=0.0, key="newBW")
        with cc7:
            submitted = st.form_submit_button("➕ 新增箱型", use_container_width=True)

    if submitted:
        nm = (new_name or "").strip() or f"箱型_{len(st.session_state.box_df)+1}"
        row = {"選取": False, "使用": True, "名稱": nm, "長": float(newL), "寬": float(newW), "高": float(newH), "數量": int(newQty), "空箱重量": float(newBW)}
        st.session_state.box_df = _norm_box_df(pd.concat([st.session_state.box_df, pd.DataFrame([row])], ignore_index=True))
        gs_call("set_current", {
            "boxes": st.session_state.box_df.to_dict(orient="records"),
            "products": st.session_state.prod_df.to_dict(orient="records"),
            "current_box_template": st.session_state.get("_current_box_tpl", ""),
            "current_product_template": st.session_state.get("_current_prod_tpl", ""),
        })
        st.toast("已新增箱型", icon="➕")

    # 刪除勾選
    if st.button("🗑 刪除勾選箱型", key="btn_box_del_selected", use_container_width=True):
        df = _norm_box_df(st.session_state.box_df)
        before = len(df)
        df = df[df["選取"] != True].copy()
        df["選取"] = False
        st.session_state.box_df = _norm_box_df(df.reset_index(drop=True))
        removed = before - len(st.session_state.box_df)
        gs_call("set_current", {
            "boxes": st.session_state.box_df.to_dict(orient="records"),
            "products": st.session_state.prod_df.to_dict(orient="records"),
            "current_box_template": st.session_state.get("_current_box_tpl", ""),
            "current_product_template": st.session_state.get("_current_prod_tpl", ""),
        })
        st.toast(f"已刪除 {removed} 筆箱型", icon="🗑")

    # 箱型表格（至少 8 行高度）
    edited = st.data_editor(
        _norm_box_df(st.session_state.box_df),
        num_rows="dynamic",
        use_container_width=True,
        height=360,
        column_config={
            "選取": st.column_config.CheckboxColumn(width="small", help="勾選後可一鍵刪除"),
            "使用": st.column_config.CheckboxColumn(width="small", help="勾選才會參與裝箱"),
            "名稱": st.column_config.TextColumn(width="medium"),
            "長": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "寬": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "高": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "數量": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
            "空箱重量": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
        },
        key="box_editor",
    )
    st.session_state.box_df = _norm_box_df(edited)

    # 同步 current（避免你說的「第一次動作被回復」）
    gs_call("set_current", {
        "boxes": st.session_state.box_df.to_dict(orient="records"),
        "products": st.session_state.prod_df.to_dict(orient="records"),
        "current_box_template": st.session_state.get("_current_box_tpl", ""),
        "current_product_template": st.session_state.get("_current_prod_tpl", ""),
    })

    st.markdown("</div>", unsafe_allow_html=True)

# ==========================
# Section 2：商品清單
# ==========================
def render_product_section():
    st.markdown('<div class="section-title">2. 商品清單（直接編輯表格）</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)

    st.markdown("### 商品模板（載入 / 儲存 / 刪除）")

    tpl_names = ["(無)"] + (st.session_state.prod_templates or [])

    cL, cM, cR = st.columns([2, 2, 2], gap="large")
    with cL:
        st.selectbox("選擇模板", tpl_names, key="prod_tpl_sel")
        st.text_input("另存為模板名稱", value=st.session_state.get("prod_tpl_save_name", ""), placeholder="例如：常用商品組合A", key="prod_tpl_save_name")
    with cM:
        st.button("⬇️ 載入商品模板", key="btn_prod_tpl_load", use_container_width=True)
        st.button("💾 儲存商品模板", key="btn_prod_tpl_save", use_container_width=True)
    with cR:
        st.selectbox("要刪除的模板", tpl_names, key="prod_tpl_del_sel")
        st.button("🗑 刪除商品模板", key="btn_prod_tpl_del", use_container_width=True)

    st.markdown("<div class='smallnote'>提示：取消啟用或數量=0 就不會納入裝箱。</div>", unsafe_allow_html=True)

    if st.session_state.get("btn_prod_tpl_load"):
        nm = st.session_state.get("prod_tpl_sel", "(無)")
        if nm == "(無)":
            st.warning("請先選擇要載入的商品模板")
        else:
            r = gs_call("load_template", {"kind": "product", "name": nm})
            if r.get("ok"):
                rows = r.get("rows") or r.get("data", {}).get("rows") or []
                st.session_state.prod_df = _norm_prod_df(pd.DataFrame(rows))
                st.session_state._current_prod_tpl = nm
                gs_call("set_current", {
                    "boxes": st.session_state.box_df.to_dict(orient="records"),
                    "products": st.session_state.prod_df.to_dict(orient="records"),
                    "current_box_template": st.session_state.get("_current_box_tpl", ""),
                    "current_product_template": nm,
                })
                st.toast("已載入商品模板", icon="⬇️")
            else:
                st.error(r.get("message", "載入失敗"))

    if st.session_state.get("btn_prod_tpl_save"):
        nm = (st.session_state.get("prod_tpl_save_name") or "").strip()
        if not nm:
            st.warning("請輸入『另存為模板名稱』再儲存")
        else:
            r = gs_call("save_template", {"kind": "product", "name": nm, "rows": st.session_state.prod_df.to_dict(orient="records")})
            if r.get("ok"):
                st.session_state._current_prod_tpl = nm
                r2 = gs_call("list_templates", {"kind": "product"})
                if r2.get("ok"):
                    st.session_state.prod_templates = sorted(list(set(r2.get("templates", []) or [])))
                gs_call("set_current", {
                    "boxes": st.session_state.box_df.to_dict(orient="records"),
                    "products": st.session_state.prod_df.to_dict(orient="records"),
                    "current_box_template": st.session_state.get("_current_box_tpl", ""),
                    "current_product_template": nm,
                })
                st.toast("已儲存商品模板", icon="💾")
            else:
                st.error(r.get("message", "儲存失敗"))

    if st.session_state.get("btn_prod_tpl_del"):
        nm = st.session_state.get("prod_tpl_del_sel", "(無)")
        if nm == "(無)":
            st.warning("請先選擇要刪除的商品模板")
        else:
            r = gs_call("delete_template", {"kind": "product", "name": nm})
            if r.get("ok"):
                r2 = gs_call("list_templates", {"kind": "product"})
                if r2.get("ok"):
                    st.session_state.prod_templates = sorted(list(set(r2.get("templates", []) or [])))
                if (st.session_state.get("_current_prod_tpl") or "") == nm:
                    st.session_state._current_prod_tpl = ""
                st.toast("已刪除商品模板", icon="🗑")
            else:
                st.error(r.get("message", "刪除失敗"))

    st.markdown("<hr>", unsafe_allow_html=True)

    # 刪除勾選商品
    if st.button("🗑 刪除勾選商品", key="btn_prod_del_selected", use_container_width=True):
        df = _norm_prod_df(st.session_state.prod_df)
        before = len(df)
        df = df[df["選取"] != True].copy()
        df["選取"] = False
        st.session_state.prod_df = _norm_prod_df(df.reset_index(drop=True))
        removed = before - len(st.session_state.prod_df)
        gs_call("set_current", {
            "boxes": st.session_state.box_df.to_dict(orient="records"),
            "products": st.session_state.prod_df.to_dict(orient="records"),
            "current_box_template": st.session_state.get("_current_box_tpl", ""),
            "current_product_template": st.session_state.get("_current_prod_tpl", ""),
        })
        st.toast(f"已刪除 {removed} 筆商品列", icon="🗑")

    # 商品表格（至少 8 行高度）
    edited = st.data_editor(
        _norm_prod_df(st.session_state.prod_df),
        num_rows="dynamic",
        use_container_width=True,
        height=360,
        column_config={
            "選取": st.column_config.CheckboxColumn(width="small", help="勾選後可一鍵刪除"),
            "啟用": st.column_config.CheckboxColumn(width="small", help="取消啟用或數量=0 就不納入裝箱"),
            "商品名稱": st.column_config.TextColumn(width="large"),
            "長": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "寬": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "高": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "重量(kg)": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
            "數量": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
        },
        key="prod_editor",
    )
    st.session_state.prod_df = _norm_prod_df(edited)

    # 同步 current
    gs_call("set_current", {
        "boxes": st.session_state.box_df.to_dict(orient="records"),
        "products": st.session_state.prod_df.to_dict(orient="records"),
        "current_box_template": st.session_state.get("_current_box_tpl", ""),
        "current_product_template": st.session_state.get("_current_prod_tpl", ""),
    })

    st.markdown("</div>", unsafe_allow_html=True)

# ==========================
# 版面渲染（左右 50/50 或 上下）
# ==========================
if layout_mode == "左右 50% / 50%":
    left, right = st.columns(2, gap="large")
    with left:
        render_box_section()
    with right:
        render_product_section()
else:
    render_box_section()
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    render_product_section()

# ==========================
# 計算按鈕
# ==========================
st.markdown('<div class="section-title">3. 裝箱結果與模擬</div>', unsafe_allow_html=True)
run_button = st.button("🚀 開始計算與 3D 模擬", key="btn_run", use_container_width=True)

if run_button:
    with st.spinner("正在進行智慧裝箱運算..."):
        bins = build_candidate_bins()
        if not bins:
            st.error("請至少設定 1 個可用外箱（手動箱或預存箱）且數量 > 0")
            st.stop()

        items, req_counts, unique_products, total_qty = build_items()
        if total_qty == 0:
            st.warning("目前沒有任何商品被納入計算（請確認：啟用=勾選 且 數量>0）")
            st.stop()

        bins_result, bins_used, remaining = pack_with_inventory(items, bins)

        # 統計
        packed_counts: Dict[str, int] = {}
        total_vol = 0.0
        total_net_weight = 0.0
        for placed in bins_result:
            for it in placed:
                packed_counts[it["name"]] = packed_counts.get(it["name"], 0) + 1
                total_vol += it["dx"] * it["dy"] * it["dz"]
                total_net_weight += it["weight"]

        used_box_total_vol = sum(float(b["長"]) * float(b["寬"]) * float(b["高"]) for b in bins_used) or 0.0
        used_box_total_weight = sum(_to_float(b.get("空箱重量", 0.0)) for b in bins_used) or 0.0
        utilization = (total_vol / used_box_total_vol * 100.0) if used_box_total_vol > 0 else 0.0
        gross_weight = total_net_weight + used_box_total_weight

        # 是否全裝入
        missing = []
        all_fitted = True
        for name, req in req_counts.items():
            real = packed_counts.get(name, 0)
            if real < req:
                all_fitted = False
                missing.append((name, req - real))

        # 報告 UI
        tw = _now_tw()
        now_str = tw.strftime("%Y-%m-%d %H:%M (台灣時間)")
        order_name = st.session_state.order_name

        # 外箱摘要
        box_summary = {}
        for bdef in bins_used:
            key = f'{bdef["名稱"]} ({bdef["長"]}×{bdef["寬"]}×{bdef["高"]})'
            box_summary[key] = box_summary.get(key, 0) + 1
        box_summary_html = "<br>".join([f"{k} × {v} 箱" for k, v in box_summary.items()]) if box_summary else "-"

        ok_html = "<div style='color:#065F46;background:#D1FAE5;padding:14px;border-radius:12px;text-align:center;border:1px solid #10B981;font-weight:900;font-size:1.1rem;'>✅ 完美！所有商品皆已裝入。</div>"
        bad_html = "<div style='color:#991B1B;background:#FEE2E2;padding:14px;border-radius:12px;border:1px solid #EF4444;font-weight:900;'>❌ 注意：有部分商品裝不下！（可能箱型不足/尺寸不足/或需要更大箱）</div>"
        miss_html = ""
        if missing:
            miss_html = "<ul style='padding-left:18px;margin-top:10px;'>" + "".join([
                f"<li style='color:#991B1B;background:#FEE2E2;padding:8px;margin:6px 0;border-radius:10px;font-weight:900;'>⚠️ {n}: 遺漏 {d} 個</li>"
                for (n, d) in missing
            ]) + "</ul>"

        st.markdown(f"""
        <div class="panel">
          <div style="font-weight:900;font-size:1.25rem;border-bottom:3px solid #111827;padding-bottom:10px;margin-bottom:12px;">📋 訂單裝箱報告</div>
          <div style="display:grid;grid-template-columns:170px 1fr;row-gap:10px;column-gap:10px;font-size:1.05rem;">
            <div style="font-weight:900;color:#374151;">📝 訂單名稱</div><div style="font-weight:900;color:#1d4ed8;">{order_name}</div>
            <div style="font-weight:900;color:#374151;">🕒 計算時間</div><div>{now_str}</div>
            <div style="font-weight:900;color:#374151;">📦 使用外箱</div><div>{box_summary_html}</div>
            <div style="font-weight:900;color:#374151;">⚖️ 內容淨重</div><div>{total_net_weight:.2f} kg</div>
            <div style="font-weight:900;color:#b91c1c;">🚛 本次總重</div><div style="font-weight:900;color:#b91c1c;font-size:1.15rem;">{gross_weight:.2f} kg</div>
            <div style="font-weight:900;color:#374151;">📊 空間利用率</div><div>{utilization:.2f}%</div>
          </div>
          <div style="margin-top:14px;">{ok_html if all_fitted else (bad_html + miss_html)}</div>
        </div>
        """, unsafe_allow_html=True)

        # 3D
        fig = build_figure(bins_used, bins_result, unique_products)
        st.plotly_chart(fig, use_container_width=True, theme=None, config={"displayModeBar": True})

        # 下載報告
        file_time = tw.strftime("%Y%m%d_%H%M")
        file_name = f"{order_name.replace(' ', '_')}_{file_time}_總數{total_qty}.html"
        full_html = f"""
        <html><head><meta charset="utf-8"><title>裝箱報告 - {order_name}</title></head>
        <body style="font-family:Arial;background:#f3f4f6;padding:24px;color:#111;">
          <div style="max-width:1100px;margin:0 auto;background:#fff;padding:24px;border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.08);">
            <h2 style="margin-top:0;">📋 訂單裝箱報告</h2>
            <p><b>訂單名稱：</b>{order_name}</p>
            <p><b>計算時間：</b>{now_str}</p>
            <p><b>使用外箱：</b><br>{box_summary_html}</p>
            <p><b>內容淨重：</b>{total_net_weight:.2f} kg</p>
            <p><b>本次總重：</b>{gross_weight:.2f} kg</p>
            <p><b>空間利用率：</b>{utilization:.2f}%</p>
            <hr>
            <div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:10px;">
              {fig.to_html(include_plotlyjs="cdn", full_html=False)}
            </div>
          </div>
        </body></html>
        """
        st.download_button(
            "📥 下載完整裝箱報告 (.html)",
            data=full_html,
            file_name=file_name,
            mime="text/html",
            use_container_width=True
        )
