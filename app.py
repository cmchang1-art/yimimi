import streamlit as st
import pandas as pd
import datetime
import math
import json
import os
from itertools import permutations
import plotly.graph_objects as go
import time

# ==========================
# 檔案持久化（本機 JSON）
# ==========================
DATA_DIR = "data"
BOX_FILE = os.path.join(DATA_DIR, "box_presets.json")
TPL_FILE = os.path.join(DATA_DIR, "product_templates.json")

def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def _load_json(path, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def _save_json(path, data):
    try:
        _ensure_data_dir()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

# ==========================
# 安全轉型
# ==========================
def _to_float(x, default=0.0):
    try:
        if x is None:
            return float(default)
        if isinstance(x, (int, float)):
            if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
                return float(default)
            return float(x)
        s = str(x).strip()
        if s == "" or s.lower() in ("nan", "none", "null", "inf", "-inf"):
            return float(default)
        v = float(s)
        if math.isnan(v) or math.isinf(v):
            return float(default)
        return v
    except:
        return float(default)

def _to_int(x, default=0):
    try:
        if x is None:
            return int(default)
        if isinstance(x, bool):
            return int(default)
        if isinstance(x, int):
            return int(x)
        if isinstance(x, float):
            if math.isnan(x) or math.isinf(x):
                return int(default)
            return int(x)
        s = str(x).strip()
        if s == "" or s.lower() in ("nan", "none", "null"):
            return int(default)
        return int(float(s))
    except:
        return int(default)

def _now_tw():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)

# ==========================
# 幾何：碰撞/盒內/點覆蓋
# ==========================
def _collide(a, b):
    return not (
        a["x"] + a["dx"] <= b["x"] or
        b["x"] + b["dx"] <= a["x"] or
        a["y"] + a["dy"] <= b["y"] or
        b["y"] + b["dy"] <= a["y"] or
        a["z"] + a["dz"] <= b["z"] or
        b["z"] + b["dz"] <= a["z"]
    )

def _inside_box(x, y, z, dx, dy, dz, L, W, H):
    return (x >= 0 and y >= 0 and z >= 0 and
            x + dx <= L and y + dy <= W and z + dz <= H)

def _point_is_covered(px, py, pz, placed):
    for b in placed:
        if (b["x"] <= px < b["x"] + b["dx"] and
            b["y"] <= py < b["y"] + b["dy"] and
            b["z"] <= pz < b["z"] + b["dz"]):
            return True
    return False

# ==========================
# 旋轉候選：6 rotations
# ==========================
def orientations_6(l, w, h, box_l, box_w, box_h):
    l = max(_to_float(l), 0.0)
    w = max(_to_float(w), 0.0)
    h = max(_to_float(h), 0.0)
    if l <= 0 or w <= 0 or h <= 0:
        return []
    oris = []
    for dx, dy, dz in set(permutations([l, w, h], 3)):
        if dx <= box_l and dy <= box_w and dz <= box_h:
            oris.append((dx, dy, dz))
    return oris

# ==========================
# Corner-first Extreme Points 裝一箱
# ==========================
def pack_one_bin(items, box):
    L, W, H = box["長"], box["寬"], box["高"]
    placed = []
    points = {(0.0, 0.0, 0.0)}

    def score_candidate(x, y, z, dx, dy, dz):
        base = dx * dy
        return (z, y, x, -base, dz)

    for it in items:
        best = None
        best_s = None

        pts = sorted(points, key=lambda p: (p[2], p[1], p[0]))  # z,y,x
        for (px, py, pz) in pts:
            if _point_is_covered(px, py, pz, placed):
                continue

            for (dx, dy, dz) in it["oris"]:
                if not _inside_box(px, py, pz, dx, dy, dz, L, W, H):
                    continue
                cand = {"x": px, "y": py, "z": pz, "dx": dx, "dy": dy, "dz": dz}
                if any(_collide(cand, p) for p in placed):
                    continue

                s = score_candidate(px, py, pz, dx, dy, dz)
                if best is None or s < best_s:
                    best = cand
                    best_s = s

        if best is None:
            it["placed"] = False
            continue

        it["placed"] = True
        it["x"], it["y"], it["z"] = best["x"], best["y"], best["z"]
        it["dx"], it["dy"], it["dz"] = best["dx"], best["dy"], best["dz"]

        placed.append({
            "_id": it["_id"],
            "name": it["name"],
            "x": it["x"], "y": it["y"], "z": it["z"],
            "dx": it["dx"], "dy": it["dy"], "dz": it["dz"],
            "weight": it["weight"],
        })

        new_pts = [
            (it["x"] + it["dx"], it["y"], it["z"]),
            (it["x"], it["y"] + it["dy"], it["z"]),
            (it["x"], it["y"], it["z"] + it["dz"]),
        ]
        for nx, ny, nz in new_pts:
            if nx <= L and ny <= W and nz <= H:
                points.add((float(nx), float(ny), float(nz)))

        points = {p for p in points if not _point_is_covered(p[0], p[1], p[2], placed)}

    return placed

# ==========================
# 遵循箱型庫存：嚴格用「你勾選 + 你數量」
# ==========================
def build_candidate_bins(manual_box, saved_boxes_df):
    bins = []

    if manual_box.get("使用", False):
        qty = max(_to_int(manual_box.get("數量", 0)), 0)
        if qty > 0:
            for _ in range(qty):
                bins.append({
                    "來源": "手動",
                    "名稱": manual_box.get("名稱", "手動箱"),
                    "長": _to_float(manual_box["長"]),
                    "寬": _to_float(manual_box["寬"]),
                    "高": _to_float(manual_box["高"]),
                    "空箱重量": _to_float(manual_box.get("空箱重量", 0.0)),
                })

    if saved_boxes_df is not None and len(saved_boxes_df) > 0:
        for _, r in saved_boxes_df.iterrows():
            if not bool(r.get("使用", False)):
                continue
            qty = max(_to_int(r.get("數量", 0)), 0)
            if qty <= 0:
                continue
            for _ in range(qty):
                bins.append({
                    "來源": "預存",
                    "名稱": str(r.get("名稱", "外箱")).strip() or "外箱",
                    "長": _to_float(r.get("長", 0)),
                    "寬": _to_float(r.get("寬", 0)),
                    "高": _to_float(r.get("高", 0)),
                    "空箱重量": _to_float(r.get("空箱重量", 0.0)),
                })

    bins = [b for b in bins if b["長"] > 0 and b["寬"] > 0 and b["高"] > 0]
    return bins

# ==========================
# 商品：只取 啟用=是 且 數量>0
# ==========================
def build_items_from_df(df, max_bin):
    maxL, maxW, maxH = max_bin["長"], max_bin["寬"], max_bin["高"]

    items = []
    requested_counts = {}
    unique_products = []
    total_qty = 0
    _id_counter = 1

    df2 = df.copy()
    if "啟用" not in df2.columns:
        df2["啟用"] = True
    if "刪除" not in df2.columns:
        df2["刪除"] = False

    for c in ["長","寬","高","重量(kg)"]:
        if c not in df2.columns:
            df2[c] = 0.0
    if "數量" not in df2.columns:
        df2["數量"] = 0

    df2["長"] = df2["長"].apply(_to_float)
    df2["寬"] = df2["寬"].apply(_to_float)
    df2["高"] = df2["高"].apply(_to_float)
    df2["重量(kg)"] = df2["重量(kg)"].apply(_to_float)
    df2["數量"] = df2["數量"].apply(_to_int)

    df2["base_area"] = df2["長"] * df2["寬"]
    df2["volume"] = df2["長"] * df2["寬"] * df2["高"]
    df2 = df2.sort_values(by=["base_area", "volume"], ascending=[False, False])

    for _, r in df2.iterrows():
        if not bool(r.get("啟用", True)):
            continue

        name = str(r.get("商品名稱", "")).strip()
        if not name:
            continue

        qty = _to_int(r.get("數量", 0))
        if qty <= 0:
            continue

        l = _to_float(r.get("長", 0))
        w = _to_float(r.get("寬", 0))
        h = _to_float(r.get("高", 0))
        weight = _to_float(r.get("重量(kg)", 0))

        if l <= 0 or w <= 0 or h <= 0:
            continue

        oris = orientations_6(l, w, h, maxL, maxW, maxH)
        if not oris:
            oris = []

        requested_counts[name] = requested_counts.get(name, 0) + qty
        if name not in unique_products:
            unique_products.append(name)

        total_qty += qty
        for _ in range(qty):
            items.append({
                "_id": _id_counter,
                "name": name,
                "l": l, "w": w, "h": h,
                "weight": weight,
                "oris": oris
            })
            _id_counter += 1

    return items, requested_counts, unique_products, total_qty

# ==========================
# 一箱判斷：庫存箱中找得到且最省空間的那一箱
# ==========================
def best_single_bin_if_possible(items, candidate_bins):
    total_items = len(items)
    best = None
    best_metric = None

    strategies = [
        ("base_area", lambda it: -(it["l"] * it["w"])),
        ("volume", lambda it: -(it["l"] * it["w"] * it["h"])),
        ("max_edge", lambda it: -max(it["l"], it["w"], it["h"])),
    ]

    for b in candidate_bins:
        for _, keyfn in strategies:
            items_copy = [dict(it) for it in items]
            items_copy.sort(key=keyfn)

            placed = pack_one_bin(items_copy, b)
            if len(placed) == total_items:
                used_vol = sum(p["dx"] * p["dy"] * p["dz"] for p in placed)
                bin_vol = b["長"] * b["寬"] * b["高"]
                waste = bin_vol - used_vol

                metric = (bin_vol, waste)
                if best is None or metric < best_metric:
                    best = {"bins": [placed], "bin_defs": [b], "unplaced": []}
                    best_metric = metric

    return best

# ==========================
# 多箱：依照庫存箱清單逐箱填（用完就沒了）
# ==========================
def pack_with_inventory(items, inventory_bins):
    remaining = [dict(it) for it in items]
    bins_result = []
    bin_defs_used = []

    strategies = [
        ("base_area", lambda it: -(it["l"] * it["w"])),
        ("volume", lambda it: -(it["l"] * it["w"] * it["h"])),
        ("max_edge", lambda it: -max(it["l"], it["w"], it["h"])),
    ]

    available_bins = list(inventory_bins)

    while remaining and available_bins:
        best_choice = None
        best_metric = None
        remaining_ids = set(it["_id"] for it in remaining)

        for idx, b in enumerate(available_bins):
            best_for_this_bin = None
            best_for_this_metric = None

            for _, keyfn in strategies:
                items_copy = [dict(it) for it in remaining]
                items_copy.sort(key=keyfn)

                placed = pack_one_bin(items_copy, b)
                if not placed:
                    continue

                fitted = len(placed)
                used_vol = sum(p["dx"] * p["dy"] * p["dz"] for p in placed)
                bin_vol = b["長"] * b["寬"] * b["高"]
                waste = bin_vol - used_vol

                m = (-fitted, bin_vol, waste)
                if best_for_this_bin is None or m < best_for_this_metric:
                    best_for_this_bin = placed
                    best_for_this_metric = m

            if best_for_this_bin is None:
                continue

            fitted = len(best_for_this_bin)
            used_vol = sum(p["dx"] * p["dy"] * p["dz"] for p in best_for_this_bin)
            bin_vol = b["長"] * b["寬"] * b["高"]
            waste = bin_vol - used_vol

            metric = (-fitted, bin_vol, waste, idx)
            if best_choice is None or metric < best_metric:
                best_choice = (idx, b, best_for_this_bin)
                best_metric = metric

        if best_choice is None:
            break

        idx, chosen_bin, placed = best_choice
        bins_result.append(placed)
        bin_defs_used.append(chosen_bin)

        placed_ids = set(p["_id"] for p in placed).intersection(remaining_ids)
        remaining = [it for it in remaining if it["_id"] not in placed_ids]

        available_bins.pop(idx)

    return bins_result, bin_defs_used, remaining

# ==========================
# UI
# ==========================
st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="collapsed")

# ✅ UI 修正：按鈕分色 + Plotly 強制白底
st.markdown("""
<style>
  /* ===== 全域：強制亮色可讀 ===== */
  .stApp { background:#ffffff !important; color:#111 !important; }
  .stMarkdown, .stCaption, label, p, span, small { color:#111 !important; }

  /* ===== 你截圖裡的怪圓角長條：就是 marker div 被渲染出來 → 全部隱形 ===== */
  .btn-add, .btn-del, .btn-save, .btn-load, .btn-run {
    display:none !important;
    height:0 !important;
    margin:0 !important;
    padding:0 !important;
  }

  /* ===== Streamlit 按鈕：先做一個「不會黑底黑字」的安全底色 ===== */
  div[data-testid="stButton"] > button,
  div.stButton > button,
  button[kind]{
    background:#F3F4F6 !important;
    color:#111 !important;
    border:1px solid #D1D5DB !important;
    border-radius:12px !important;
    font-weight:900 !important;
    padding:10px 14px !important;
  }

  /* ===== 分類上色：用「marker + 下一顆 stButton」的穩定版本（同時支援 stButton / data-testid） ===== */
  .btn-add + div[data-testid="stButton"] > button,
  .btn-add + div.stButton > button{
    background:#D1FAE5 !important; border-color:#10B981 !important; color:#065F46 !important;
  }
  .btn-del + div[data-testid="stButton"] > button,
  .btn-del + div.stButton > button{
    background:#FEE2E2 !important; border-color:#EF4444 !important; color:#991B1B !important;
  }
  .btn-save + div[data-testid="stButton"] > button,
  .btn-save + div.stButton > button{
    background:#DBEAFE !important; border-color:#3B82F6 !important; color:#1E3A8A !important;
  }
  .btn-load + div[data-testid="stButton"] > button,
  .btn-load + div.stButton > button{
    background:#E5E7EB !important; border-color:#9CA3AF !important; color:#111827 !important;
  }
  .btn-run + div[data-testid="stButton"] > button,
  .btn-run + div.stButton > button{
    background:#D1FAE5 !important; border-color:#10B981 !important; color:#065F46 !important;
  }

  /* ===== 你的深色表格（data_editor）保持深色，但文字要亮 ===== */
  div[data-testid="stDataFrame"]{
    background:#0B1220 !important;
    border-radius:12px !important;
    border:1px solid rgba(255,255,255,0.12) !important;
    overflow:hidden !important;
  }
  div[data-testid="stDataFrame"] * { color:#E5E7EB !important; }

  /* ===== Plotly/3D 強制白底（避免黑底） ===== */
  [data-testid="stPlotlyChart"],
  .js-plotly-plot, .plotly, .main-svg{
    background:#ffffff !important;
  }

  /* ===== 標題區塊：純線條，不要黑底 ===== */
  .section-header{
    font-size:1.15rem; font-weight:900; color:#111 !important;
    margin:10px 0 6px 0;
    border-left:5px solid #FF4B4B;
    padding-left:10px;
    background:transparent !important;
  }
</style>

""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統")
st.markdown("---")

# ==========================
# Session init（含持久化載入）
# ==========================
if "box_presets" not in st.session_state:
    loaded = _load_json(BOX_FILE, [])
    st.session_state.box_presets = pd.DataFrame(loaded) if loaded else pd.DataFrame(
        columns=["使用","名稱","長","寬","高","數量","空箱重量","刪除"]
    )
    for col in ["使用","刪除"]:
        if col not in st.session_state.box_presets.columns:
            st.session_state.box_presets[col] = False

if "product_templates" not in st.session_state:
    st.session_state.product_templates = _load_json(TPL_FILE, {})

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(
        [
            {"啟用": True, "商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5, "刪除": False},
            {"啟用": True, "商品名稱": "紙袋",     "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05,"數量": 5, "刪除": False},
        ]
    )

def save_boxes_now():
    df = st.session_state.box_presets.copy()
    if "刪除" in df.columns:
        df = df.drop(columns=["刪除"])
    _save_json(BOX_FILE, df.to_dict(orient="records"))

def save_templates_now():
    _save_json(TPL_FILE, st.session_state.product_templates)

# ==========================
# Layout mode
# ==========================
layout_mode = st.radio("版面配置", ["左右 50% / 50%", "上下（垂直）"], horizontal=True, index=0)

# ==========================
# Sections
# ==========================
def render_box_section():
    st.markdown('<div class="section-header">1. 訂單與外箱設定</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)

    order_name = st.text_input("訂單名稱", value=st.session_state.get("_order_name", "訂單_20241208"), key="order_name")
    st.session_state["_order_name"] = order_name

    st.caption("外箱尺寸 (cm) - 手動 Key in（可選擇是否參與裝箱）")
    c1, c2, c3 = st.columns(3)
    manual_L = c1.number_input("長", value=float(st.session_state.get("manual_L", 35.0)), step=1.0, key="manual_L")
    manual_W = c2.number_input("寬", value=float(st.session_state.get("manual_W", 25.0)), step=1.0, key="manual_W")
    manual_H = c3.number_input("高", value=float(st.session_state.get("manual_H", 20.0)), step=1.0, key="manual_H")
    manual_box_weight = st.number_input("空箱重量 (kg)", value=float(st.session_state.get("manual_box_weight", 0.5)), step=0.1, key="manual_box_weight")

    c4, c5, c6 = st.columns([1, 1, 2])
    manual_use = c4.checkbox("使用手動箱", value=bool(st.session_state.get("manual_use", True)), key="manual_use")
    manual_qty = c5.number_input("手動箱數量", value=int(st.session_state.get("manual_qty", 1)), step=1, min_value=0, key="manual_qty")
    manual_name = c6.text_input("手動箱命名", value=st.session_state.get("manual_name", "手動箱"), key="manual_name")

    st.session_state["_manual_box"] = {
        "使用": manual_use,
        "名稱": manual_name,
        "長": float(manual_L),
        "寬": float(manual_W),
        "高": float(manual_H),
        "空箱重量": float(manual_box_weight),
        "數量": int(manual_qty),
    }

    st.markdown("</div>", unsafe_allow_html=True)

    # 箱型管理
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div style="font-weight:900;margin-bottom:8px;">📦 箱型管理（新增 / 修改 / 刪除 / 勾選使用）</div>', unsafe_allow_html=True)

    left, right = st.columns([1, 2], gap="large")

    with left:
        st.caption("新增一筆箱型（新增後可在右側表格直接修改）")

        # ✅ 用 form 避免「要按兩次」與輸入被重置
        with st.form("form_add_box", clear_on_submit=False):
            new_box_name = st.text_input("新箱型名稱", value=st.session_state.get("new_box_name", ""), placeholder="例如：A款", key="new_box_name")
            nb1, nb2, nb3 = st.columns(3)
            new_L = nb1.number_input("新箱_長", value=float(st.session_state.get("new_L", 45.0)), step=1.0, min_value=0.0, key="new_L")
            new_W = nb2.number_input("新箱_寬", value=float(st.session_state.get("new_W", 30.0)), step=1.0, min_value=0.0, key="new_W")
            new_H = nb3.number_input("新箱_高", value=float(st.session_state.get("new_H", 30.0)), step=1.0, min_value=0.0, key="new_H")
            new_box_weight = st.number_input("新箱_空箱重量(kg)", value=float(st.session_state.get("new_box_weight", 0.5)), step=0.1, min_value=0.0, key="new_box_weight")
            new_qty = st.number_input("新箱_數量", value=int(st.session_state.get("new_qty", 1)), step=1, min_value=0, key="new_qty")

            st.markdown('<div class="btn-add"></div>', unsafe_allow_html=True)
            submitted_add = st.form_submit_button("➕ 新增箱型", use_container_width=True)

        if submitted_add:
            with st.spinner("新增中..."):
                nm = new_box_name.strip() if new_box_name.strip() else f"箱型_{len(st.session_state.box_presets)+1}"
                row = {
                    "使用": True,
                    "名稱": nm,
                    "長": float(new_L),
                    "寬": float(new_W),
                    "高": float(new_H),
                    "數量": int(new_qty),
                    "空箱重量": float(new_box_weight),
                    "刪除": False
                }
                st.session_state.box_presets = pd.concat([st.session_state.box_presets, pd.DataFrame([row])], ignore_index=True)
                save_boxes_now()
            st.toast("✅ 已新增箱型並保存", icon="✅")

        # ✅ 刪除也用 form：單次觸發 + 有回饋
        with st.form("form_del_box"):
            st.markdown('<div class="btn-del"></div>', unsafe_allow_html=True)
            submitted_del = st.form_submit_button("🗑️ 刪除勾選的箱型", use_container_width=True)

        if submitted_del:
            with st.spinner("刪除中..."):
                dfp = st.session_state.box_presets.copy()
                if "刪除" not in dfp.columns:
                    dfp["刪除"] = False
                before = len(dfp)
                st.session_state.box_presets = dfp[dfp["刪除"] != True].reset_index(drop=True)
                save_boxes_now()
                removed = before - len(st.session_state.box_presets)
            st.toast(f"✅ 已刪除 {removed} 筆箱型", icon="🗑️")

    with right:
        st.caption("✅ 勾選「使用」= 參與裝箱；「數量」可輸入 0；「刪除」勾選後按左側刪除按鈕")
        box_df = st.data_editor(
            st.session_state.box_presets,
            num_rows="dynamic",
            use_container_width=True,
            height=280,
            column_config={
                "使用": st.column_config.CheckboxColumn(),
                "刪除": st.column_config.CheckboxColumn(help="勾選後按左側『刪除勾選』"),
                "數量": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
                "長": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
                "寬": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
                "高": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
                "空箱重量": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
            },
            key="box_editor",
        )
        if "刪除" not in box_df.columns:
            box_df["刪除"] = False
        st.session_state.box_presets = box_df
        save_boxes_now()

    st.info(
        "外箱操作：\n"
        "• 手動箱：勾選「使用手動箱」並填數量。\n"
        "• 預存箱：右側表格可直接改尺寸/數量，勾選「使用」後會被拿去裝箱。\n"
        "• 刪除：勾選「刪除」→ 按「刪除勾選的箱型」。\n"
        "• 重新整理也不會消失（已存到本機 JSON）。"
    )

    st.markdown("</div>", unsafe_allow_html=True)

def render_product_section():
    st.markdown('<div class="section-header">2. 商品清單（直接編輯表格）</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)

    st.markdown('<div style="font-weight:900;margin-bottom:8px;">🧩 商品模板（載入 / 儲存 / 刪除）</div>', unsafe_allow_html=True)

    tpl_names = ["(無)"] + sorted(list(st.session_state.product_templates.keys()))

    # ✅ 用 form 避免「要按兩次」＆輸入被重置，並加上「處理中」回饋
    with st.form("form_template_ops", clear_on_submit=False):
        r1 = st.columns([2, 1, 2, 1], gap="medium")
        with r1[0]:
            tpl_sel = st.selectbox("商品初始值模板", tpl_names, key="tpl_sel")
        with r1[1]:
            st.markdown('<div class="btn-load"></div>', unsafe_allow_html=True)
            btn_load = st.form_submit_button("⬇️ 載入", use_container_width=True)
        with r1[2]:
            save_name = st.text_input("另存為模板名稱", value=st.session_state.get("save_name", ""), placeholder="例如：常用商品組合A", key="save_name")
        with r1[3]:
            st.markdown('<div class="btn-save"></div>', unsafe_allow_html=True)
            btn_save = st.form_submit_button("💾 儲存", use_container_width=True)

        r2 = st.columns([2, 1, 2, 1], gap="medium")
        with r2[0]:
            del_sel = st.selectbox("要刪除的模板", tpl_names, key="tpl_del_sel")
        with r2[1]:
            st.markdown('<div class="btn-del"></div>', unsafe_allow_html=True)
            btn_del = st.form_submit_button("🗑️ 刪除模板", use_container_width=True)
        with r2[2]:
            st.caption("提示：模板/箱型都會永久記錄（存在 data/）")
        with r2[3]:
            st.empty()

    if btn_load:
        with st.spinner("讀入中..."):
            if tpl_sel != "(無)" and tpl_sel in st.session_state.product_templates:
                st.session_state.df = pd.DataFrame(st.session_state.product_templates[tpl_sel])
                if "刪除" not in st.session_state.df.columns:
                    st.session_state.df["刪除"] = False
        st.toast("✅ 已載入模板", icon="⬇️")

    if btn_save:
        nm = (save_name or "").strip()
        if not nm:
            st.warning("請先輸入模板名稱再儲存。")
        else:
            with st.spinner("儲存中..."):
                st.session_state.product_templates[nm] = st.session_state.df.to_dict(orient="records")
                save_templates_now()
            st.toast("✅ 已儲存模板", icon="💾")

    if btn_del:
        nm = del_sel
        if nm == "(無)":
            st.warning("請選擇要刪除的模板。")
        else:
            with st.spinner("刪除中..."):
                st.session_state.product_templates.pop(nm, None)
                save_templates_now()
            st.toast("✅ 已刪除模板", icon="🗑️")

    st.markdown("<hr style='border:none;border-top:1px solid #E5E7EB;margin:12px 0;'>", unsafe_allow_html=True)

    # 刪除商品列：也用 form，避免按兩次
    cbtn1, cbtn2 = st.columns([1, 3])
    with cbtn1:
        with st.form("form_del_products"):
            st.markdown('<div class="btn-del"></div>', unsafe_allow_html=True)
            submitted_del_products = st.form_submit_button("🗑️ 刪除勾選商品列", use_container_width=True)
        if submitted_del_products and len(st.session_state.df) > 0:
            with st.spinner("刪除中..."):
                dff = st.session_state.df.copy()
                if "刪除" not in dff.columns:
                    dff["刪除"] = False
                before = len(dff)
                st.session_state.df = dff[dff["刪除"] != True].reset_index(drop=True)
                removed = before - len(st.session_state.df)
            st.toast(f"✅ 已刪除 {removed} 列商品", icon="🗑️")

    with cbtn2:
        st.caption("✅ 可直接在表格修改；數量可輸入 0（不計算）；啟用取消勾選也不計算")

    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        height=340,
        column_config={
            "啟用": st.column_config.CheckboxColumn(),
            "刪除": st.column_config.CheckboxColumn(help="勾選後按『刪除勾選商品列』"),
            "數量": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
            "長": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "寬": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "高": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "重量(kg)": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
        },
        key="product_editor",
    )
    if "刪除" not in edited_df.columns:
        edited_df["刪除"] = False
    st.session_state.df = edited_df

    st.info(
        "商品操作：\n"
        "• 納入計算：啟用=勾選 且 數量>0。\n"
        "• 不想計算：把數量改 0 或取消勾選啟用。\n"
        "• 刪除列：勾選「刪除」→ 按「刪除勾選商品列」。\n"
        "• 模板會永久保留，可載入/刪除。"
    )

    st.markdown("</div>", unsafe_allow_html=True)

# ==========================
# Render layout
# ==========================
if layout_mode == "左右 50% / 50%":
    left, right = st.columns([1, 1], gap="large")
    with left:
        render_box_section()
    with right:
        render_product_section()
else:
    render_box_section()
    st.markdown("---")
    render_product_section()

st.markdown("---")

# ✅ 你要的「開始計算」淡綠色
st.markdown('<div class="btn-run"></div>', unsafe_allow_html=True)
run_button = st.button("🚀 開始計算與 3D 模擬", use_container_width=True)

# ==========================
# Run
# ==========================
if run_button:
    with st.spinner("正在進行智慧裝箱運算..."):
        order_name = st.session_state.get("_order_name", "訂單")
        manual_box = st.session_state.get("_manual_box", {
            "使用": True, "名稱": "手動箱", "長": 35.0, "寬": 25.0, "高": 20.0, "空箱重量": 0.5, "數量": 1
        })

        candidate_bins = build_candidate_bins(manual_box, st.session_state.box_presets)
        if not candidate_bins:
            st.error("請至少勾選 1 種外箱並設定數量 > 0（手動箱或預存箱都可以）。")
            st.stop()

        max_bin = max(candidate_bins, key=lambda b: b["長"] * b["寬"] * b["高"])
        items, requested_counts, unique_products, total_qty = build_items_from_df(st.session_state.df, max_bin)

        if total_qty == 0:
            st.warning("目前沒有任何商品被納入計算（請確認：啟用=勾選 且 數量>0）。")
            st.stop()

        one_bin_solution = best_single_bin_if_possible(items, candidate_bins)

        if one_bin_solution is not None:
            bins_result = one_bin_solution["bins"]
            bin_defs_used = one_bin_solution["bin_defs"]
            remaining = []
        else:
            bins_result, bin_defs_used, remaining = pack_with_inventory(items, candidate_bins)

        packed_counts = {}
        total_vol = 0.0
        total_net_weight = 0.0
        for placed in bins_result:
            for it in placed:
                packed_counts[it["name"]] = packed_counts.get(it["name"], 0) + 1
                total_vol += it["dx"] * it["dy"] * it["dz"]
                total_net_weight += it["weight"]

        used_box_total_vol = sum(b["長"] * b["寬"] * b["高"] for b in bin_defs_used)
        used_box_total_weight = sum(_to_float(b.get("空箱重量", 0.0)) for b in bin_defs_used)

        utilization = (total_vol / used_box_total_vol * 100) if used_box_total_vol > 0 else 0.0
        gross_weight = total_net_weight + used_box_total_weight

        all_fitted = True
        missing_items_html = ""
        for name, req_qty in requested_counts.items():
            real_qty = packed_counts.get(name, 0)
            if real_qty < req_qty:
                all_fitted = False
                diff = req_qty - real_qty
                missing_items_html += f"<li style='color:#991B1B;background:#FEE2E2;padding:8px;margin:6px 0;border-radius:10px;font-weight:900;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status_html = (
            "<div style='color:#065F46;background:#D1FAE5;padding:14px;border-radius:12px;text-align:center;border:1px solid #10B981;font-weight:900;font-size:1.1rem;'>✅ 完美！所有商品皆已裝入。</div>"
            if all_fitted
            else f"<div style='color:#991B1B;background:#FEE2E2;padding:14px;border-radius:12px;border:1px solid #EF4444;font-weight:900;'>❌ 注意：有部分商品裝不下！（可能是箱型庫存不足或尺寸不足）</div><ul style='padding-left:18px;margin-top:10px;'>{missing_items_html}</ul>"
        )

        tw_time = _now_tw()
        now_str = tw_time.strftime("%Y-%m-%d %H:%M")
        file_time_str = tw_time.strftime("%Y%m%d_%H%M")

        st.markdown('<div class="section-header">3. 裝箱結果與模擬</div>', unsafe_allow_html=True)

        box_summary = {}
        for bdef in bin_defs_used:
            key = f'{bdef["名稱"]} ({bdef["長"]}×{bdef["寬"]}×{bdef["高"]})'
            box_summary[key] = box_summary.get(key, 0) + 1
        box_summary_html = "<br>".join([f"{k} × {v} 箱" for k, v in box_summary.items()]) if box_summary else "-"

        st.markdown(f"""
        <div class="panel">
          <div style="font-weight:900;font-size:1.25rem;border-bottom:3px solid #111827;padding-bottom:10px;margin-bottom:12px;">📋 訂單裝箱報告</div>
          <div style="display:grid;grid-template-columns:170px 1fr;row-gap:10px;column-gap:10px;font-size:1.05rem;">
            <div style="font-weight:900;color:#374151;">📝 訂單名稱</div><div style="font-weight:900;color:#1d4ed8;">{order_name}</div>
            <div style="font-weight:900;color:#374151;">🕒 計算時間</div><div>{now_str} (台灣時間)</div>
            <div style="font-weight:900;color:#374151;">📦 使用外箱</div><div>{box_summary_html}</div>
            <div style="font-weight:900;color:#374151;">⚖️ 內容淨重</div><div>{total_net_weight:.2f} kg</div>
            <div style="font-weight:900;color:#b91c1c;">🚛 本次總重</div><div style="font-weight:900;color:#b91c1c;font-size:1.15rem;">{gross_weight:.2f} kg</div>
            <div style="font-weight:900;color:#374151;">📊 空間利用率</div><div>{utilization:.2f}%</div>
          </div>
          <div style="margin-top:14px;">{status_html}</div>
        </div>
        """, unsafe_allow_html=True)

        # ✅ Plotly 強制白底（含下載報告）
        fig = go.Figure()
        axis_config = dict(
            backgroundcolor="white", showbackground=True,
            zerolinecolor="#000000", gridcolor="#999999",
            linecolor="#000000", showgrid=True, showline=True,
            tickfont=dict(color="black", size=12, family="Arial Black"),
            title=dict(font=dict(color="black", size=14, family="Arial Black"))
        )
        fig.update_layout(
            template=None,
            paper_bgcolor="white",
            plot_bgcolor="white",
            font=dict(color="black"),
            autosize=True,
            scene=dict(
                bgcolor="white",
                xaxis={**axis_config, 'title': '長 (L)'},
                yaxis={**axis_config, 'title': '寬 (W)'},
                zaxis={**axis_config, 'title': '高 (H)'},
                aspectmode='data',
                camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))
            ),
            margin=dict(t=30, b=0, l=0, r=0),
            height=640,
            legend=dict(
                x=0, y=1, xanchor="left", yanchor="top",
                font=dict(color="black", size=13),
                bgcolor="rgba(255,255,255,0.90)",
                bordercolor="#000000", borderwidth=1
            )
        )

        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        def draw_box(offset_x, L, W, H, label):
            fig.add_trace(go.Scatter3d(
                x=[offset_x+0, offset_x+L, offset_x+L, offset_x+0, offset_x+0, offset_x+0, offset_x+L, offset_x+L, offset_x+0, offset_x+0, offset_x+0, offset_x+0, offset_x+L, offset_x+L, offset_x+L, offset_x+L],
                y=[0, 0, W, W, 0, 0, 0, W, W, 0, 0, W, W, 0, 0, W],
                z=[0, 0, 0, 0, 0, H, H, H, H, H, 0, H, H, H, 0, 0],
                mode='lines', line=dict(color='#000000', width=6),
                name=label
            ))

        offsets = []
        cur_x = 0.0
        gap = 8.0
        for bdef in bin_defs_used:
            offsets.append(cur_x)
            cur_x += float(bdef["長"]) + gap

        for bi, placed in enumerate(bins_result):
            bdef = bin_defs_used[bi]
            ox = offsets[bi]
            label = "外箱" if bi == 0 else f"外箱_{bi+1}"
            label = f'{label} ({bdef["名稱"]})'
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
                    color=color, opacity=1, name=name, showlegend=True,
                ))

                fig.add_trace(go.Scatter3d(
                    x=[ox+x, ox+x+dx, ox+x+dx, ox+x, ox+x, ox+x, ox+x+dx, ox+x+dx, ox+x, ox+x, ox+x, ox+x, ox+x+dx, ox+x+dx, ox+x+dx, ox+x+dx],
                    y=[y, y, y+dy, y+dy, y, y, y, y, y+dy, y+dy, y, y+dy, y+dy, y, y, y+dy],
                    z=[z, z, z, z, z, z+dz, z+dz, z+dz, z+dz, z+dz, z, z+dz, z+dz, z+dz, z, z],
                    mode='lines', line=dict(color='#000000', width=2),
                    showlegend=False
                ))

        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        full_html_content = f"""
        <html><head><meta charset="utf-8"><title>裝箱報告 - {order_name}</title></head>
        <body style="font-family:Arial;background:#f3f4f6;padding:24px;color:#111;">
          <div style="max-width:1100px;margin:0 auto;background:#fff;padding:24px;border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.08);">
            <h2 style="margin-top:0;">📋 訂單裝箱報告</h2>
            <p><b>訂單名稱：</b>{order_name}</p>
            <p><b>計算時間：</b>{now_str} (台灣時間)</p>
            <p><b>使用外箱：</b><br>{box_summary_html}</p>
            <p><b>內容淨重：</b>{total_net_weight:.2f} kg</p>
            <p><b>本次總重：</b>{gross_weight:.2f} kg</p>
            <p><b>空間利用率：</b>{utilization:.2f}%</p>
            <hr>
            <div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:10px;">
              {fig.to_html(include_plotlyjs='cdn', full_html=False)}
            </div>
          </div>
        </body></html>
        """
        file_name = f"{order_name.replace(' ', '_')}_{file_time_str}_總數{total_qty}.html"

        st.markdown('<div class="btn-load"></div>', unsafe_allow_html=True)
        st.download_button(
            label="📥 下載完整裝箱報告 (.html)",
            data=full_html_content,
            file_name=file_name,
            mime="text/html",
            use_container_width=True
        )

        st.plotly_chart(fig, use_container_width=True, theme=None, config={'displayModeBar': False})
