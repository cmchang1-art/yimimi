
import streamlit as st
st.sidebar.error("✅ sidebar 測試：看到這行代表程式有更新成功")

# =========================================================
# 3D 裝箱系統 - 單檔模組化穩定版 (Stable Editor + No Double Click)
# =========================================================

import os
import json
import math
import random
import datetime
from itertools import permutations
from typing import Dict, List, Tuple, Any

import pandas as pd
import streamlit as st
import plotly.graph_objects as go



# =========================================================
# 0) 基本設定
# =========================================================
DATA_DIR = "data"
BOX_FILE = os.path.join(DATA_DIR, "box_presets.json")
TPL_FILE = os.path.join(DATA_DIR, "product_templates.json")

DEFAULT_BOX_COLS = ["使用", "名稱", "長", "寬", "高", "數量", "空箱重量"]
DEFAULT_PROD_COLS = ["啟用", "商品名稱", "長", "寬", "高", "重量(kg)", "數量"]


# =========================================================
# 1) Utils / Type Safe
# =========================================================
def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def _to_float(x, default=0.0) -> float:
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
    except Exception:
        return float(default)

def _to_int(x, default=0) -> int:
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
    except Exception:
        return int(default)

def _clean_bool(v) -> bool:
    # ✅ 最關鍵：把 [True] / [False] 這種污染徹底修掉
    if isinstance(v, list):
        return bool(v[0]) if len(v) > 0 else False
    return bool(v)

def _now_tw() -> datetime.datetime:
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


# =========================================================
# 2) Storage Layer (JSON)
# =========================================================
def load_json(path: str, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: str, data):
    _ensure_data_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================================
# 3) Cleaning Layer (永遠乾淨的主資料)
# =========================================================
def ensure_box_df(df: pd.DataFrame) -> pd.DataFrame:
    """保證 box DataFrame 欄位存在 + 型別乾淨（永不 LIST）"""
    if df is None or df.empty:
        df = pd.DataFrame(columns=DEFAULT_BOX_COLS)

    # 補欄位
    for c in DEFAULT_BOX_COLS:
        if c not in df.columns:
            df[c] = False if c == "使用" else (0 if c == "數量" else (0.0 if c in ["長","寬","高","空箱重量"] else ""))

    # 強制型別
    df["使用"] = df["使用"].apply(_clean_bool)
    df["名稱"] = df["名稱"].astype(str).fillna("")
    for c in ["長", "寬", "高", "空箱重量"]:
        df[c] = df[c].apply(_to_float)
    df["數量"] = df["數量"].apply(_to_int)

    # 合理修正
    df["數量"] = df["數量"].clip(lower=0)
    for c in ["長", "寬", "高", "空箱重量"]:
        df[c] = df[c].clip(lower=0)

    return df

def ensure_product_df(df: pd.DataFrame) -> pd.DataFrame:
    """商品表格也做乾淨化（避免 NaN / None 造成怪行為）"""
    if df is None or df.empty:
        df = pd.DataFrame(columns=DEFAULT_PROD_COLS)

    for c in DEFAULT_PROD_COLS:
        if c not in df.columns:
            df[c] = False if c == "啟用" else (0 if c == "數量" else (0.0 if c in ["長","寬","高","重量(kg)"] else ""))

    df["啟用"] = df["啟用"].apply(_clean_bool)
    df["商品名稱"] = df["商品名稱"].astype(str).fillna("").replace("None","")
    for c in ["長","寬","高","重量(kg)"]:
        df[c] = df[c].apply(_to_float).clip(lower=0)
    df["數量"] = df["數量"].apply(_to_int).clip(lower=0)
    return df


# =========================================================
# 4) Packing Engine (多策略多次嘗試)
# =========================================================
def _collide(a, b) -> bool:
    return not (
        a["x"] + a["dx"] <= b["x"] or
        b["x"] + b["dx"] <= a["x"] or
        a["y"] + a["dy"] <= b["y"] or
        b["y"] + b["dy"] <= a["y"] or
        a["z"] + a["dz"] <= b["z"] or
        b["z"] + b["dz"] <= a["z"]
    )

def _inside_box(x, y, z, dx, dy, dz, L, W, H) -> bool:
    return (x >= 0 and y >= 0 and z >= 0 and
            x + dx <= L and y + dy <= W and z + dz <= H)

def _point_is_covered(px, py, pz, placed) -> bool:
    for b in placed:
        if (b["x"] <= px < b["x"] + b["dx"] and
            b["y"] <= py < b["y"] + b["dy"] and
            b["z"] <= pz < b["z"] + b["dz"]):
            return True
    return False

def orientations_6_sorted(l, w, h, box_l, box_w, box_h) -> List[Tuple[float,float,float]]:
    l = max(_to_float(l), 0.0)
    w = max(_to_float(w), 0.0)
    h = max(_to_float(h), 0.0)
    if l <= 0 or w <= 0 or h <= 0:
        return []
    oris = []
    for dx, dy, dz in set(permutations([l, w, h], 3)):
        if dx <= box_l and dy <= box_w and dz <= box_h:
            oris.append((float(dx), float(dy), float(dz)))
    # 省高度 -> 底面大 -> 其他
    oris.sort(key=lambda t: (t[2], -(t[0]*t[1]), max(t), t[0]*t[1]*t[2]))
    return oris

def pack_one_bin(items: List[Dict[str,Any]], box: Dict[str,Any], score_mode="smart") -> List[Dict[str,Any]]:
    L, W, H = box["長"], box["寬"], box["高"]
    placed = []
    points = {(0.0, 0.0, 0.0)}

    def score_candidate(x, y, z, dx, dy, dz):
        base = dx * dy
        top = z + dz
        if score_mode == "smart":
            return (z, top, -base, dz, y, x)
        if score_mode == "low_top":
            return (top, z, -base, dz, y, x)
        if score_mode == "max_base":
            return (z, -base, top, dz, y, x)
        if score_mode == "corner_first":
            return (z, y, x, top, -base, dz)
        return (z, top, -base, dz, y, x)

    for it in items:
        best = None
        best_s = None
        pts = sorted(points, key=lambda p: (p[2], p[1], p[0]))

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
                    best, best_s = cand, s

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

        # 強化極點
        x0, y0, z0 = it["x"], it["y"], it["z"]
        dx, dy, dz = it["dx"], it["dy"], it["dz"]
        new_pts = [
            (x0 + dx, y0, z0),
            (x0, y0 + dy, z0),
            (x0, y0, z0 + dz),
            (x0 + dx, y0 + dy, z0),
            (x0 + dx, y0, z0 + dz),
            (x0, y0 + dy, z0 + dz),
        ]
        for nx, ny, nz in new_pts:
            if nx <= L and ny <= W and nz <= H:
                points.add((float(nx), float(ny), float(nz)))

        points = {p for p in points if not _point_is_covered(p[0], p[1], p[2], placed)}

    return placed

def best_pack_for_one_bin(items: List[Dict[str,Any]], box: Dict[str,Any], tries=18) -> List[Dict[str,Any]]:
    score_modes = ["smart", "low_top", "max_base", "corner_first"]
    order_strategies = [
        ("base_area", lambda it: (-(it["l"]*it["w"]), -it["h"])),
        ("volume",    lambda it: (-(it["l"]*it["w"]*it["h"]), -max(it["l"],it["w"],it["h"]))),
        ("max_edge",  lambda it: (-max(it["l"],it["w"],it["h"]), -(it["l"]*it["w"]))),
        ("height",    lambda it: (-it["h"], -(it["l"]*it["w"]))),
    ]

    best = None
    best_metric = None

    # 固定策略
    for sm in score_modes:
        for _, keyfn in order_strategies:
            items_copy = [dict(it) for it in items]
            items_copy.sort(key=keyfn)
            placed = pack_one_bin(items_copy, box, score_mode=sm)
            fitted = len(placed)
            used_vol = sum(p["dx"]*p["dy"]*p["dz"] for p in placed)
            bin_vol = box["長"]*box["寬"]*box["高"]
            waste = bin_vol - used_vol
            metric = (-fitted, waste, bin_vol)
            if best is None or metric < best_metric:
                best, best_metric = placed, metric

    # 隨機擾動
    rng = random.Random(7)
    for _ in range(tries):
        sm = rng.choice(score_modes)
        items_copy = [dict(it) for it in items]
        items_copy.sort(key=rng.choice(order_strategies)[1])
        if len(items_copy) > 6:
            a = rng.randint(0, len(items_copy)-1)
            b = rng.randint(0, len(items_copy)-1)
            items_copy[a], items_copy[b] = items_copy[b], items_copy[a]

        placed = pack_one_bin(items_copy, box, score_mode=sm)
        fitted = len(placed)
        used_vol = sum(p["dx"]*p["dy"]*p["dz"] for p in placed)
        bin_vol = box["長"]*box["寬"]*box["高"]
        waste = bin_vol - used_vol
        metric = (-fitted, waste, bin_vol)
        if best is None or metric < best_metric:
            best, best_metric = placed, metric

    return best or []

def build_candidate_bins(manual_box: Dict[str,Any], saved_boxes_df: pd.DataFrame) -> List[Dict[str,Any]]:
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

def build_items_from_df(df: pd.DataFrame, max_bin: Dict[str,Any]):
    maxL, maxW, maxH = max_bin["長"], max_bin["寬"], max_bin["高"]
    items = []
    requested_counts = {}
    unique_products = []
    total_qty = 0
    _id_counter = 1

    df2 = df.copy()
    df2 = ensure_product_df(df2)
    df2["base_area"] = df2["長"] * df2["寬"]
    df2["volume"] = df2["長"] * df2["寬"] * df2["高"]
    df2["max_edge"] = df2[["長","寬","高"]].max(axis=1)

    df2 = df2.sort_values(by=["base_area", "max_edge", "volume"], ascending=[False, False, False])

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

        oris = orientations_6_sorted(l, w, h, maxL, maxW, maxH)
        if name not in unique_products:
            unique_products.append(name)
        requested_counts[name] = requested_counts.get(name, 0) + qty
        total_qty += qty

        for _ in range(qty):
            items.append({
                "_id": _id_counter,
                "name": name,
                "l": l, "w": w, "h": h,
                "weight": weight,
                "oris": oris,
            })
            _id_counter += 1

    return items, requested_counts, unique_products, total_qty

def best_single_bin_if_possible(items, candidate_bins):
    total_items = len(items)
    best = None
    best_metric = None
    for b in candidate_bins:
        placed = best_pack_for_one_bin(items, b, tries=18)
        if len(placed) == total_items:
            used_vol = sum(p["dx"]*p["dy"]*p["dz"] for p in placed)
            bin_vol = b["長"]*b["寬"]*b["高"]
            waste = bin_vol - used_vol
            metric = (bin_vol, waste)
            if best is None or metric < best_metric:
                best = {"bins": [placed], "bin_defs": [b], "unplaced": []}
                best_metric = metric
    return best

def pack_with_inventory(items, inventory_bins):
    remaining = [dict(it) for it in items]
    bins_result = []
    bin_defs_used = []
    available_bins = list(inventory_bins)

    while remaining and available_bins:
        best_choice = None
        best_metric = None
        remaining_ids = set(it["_id"] for it in remaining)

        for idx, b in enumerate(available_bins):
            placed = best_pack_for_one_bin(remaining, b, tries=18)
            if not placed:
                continue
            fitted = len(placed)
            used_vol = sum(p["dx"]*p["dy"]*p["dz"] for p in placed)
            bin_vol = b["長"]*b["寬"]*b["高"]
            waste = bin_vol - used_vol
            metric = (-fitted, waste, bin_vol, idx)
            if best_choice is None or metric < best_metric:
                best_choice = (idx, b, placed)
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


# =========================================================
# 5) UI Theme (按鈕分級)
# =========================================================
def inject_css():
    st.markdown("""
    <style>
      .stApp { background:#ffffff !important; color:#111 !important; }
      [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stDecoration"],
      .stDeployButton, footer, #MainMenu, [data-testid="stToolbar"] { display:none !important; }
      [data-testid="stHeader"] { background-color:transparent !important; pointer-events:none; }

      .section-header{
        font-size:1.15rem; font-weight:900; color:#111;
        margin:10px 0 6px 0; border-left:5px solid #FF4B4B; padding-left:10px;
      }
      .panel{
        background:#FFFFFF;
        border:1px solid #E5E7EB;
        border-radius:14px;
        padding:14px 14px 10px 14px;
        box-shadow:0 6px 18px rgba(0,0,0,0.04);
        margin-bottom:12px;
      }

      .stButton > button{
        background:#F3F4F6 !important;
        color:#111 !important;
        border:1px solid #D1D5DB !important;
        border-radius:12px !important;
        font-weight:900 !important;
        padding:10px 14px !important;
      }

      /* 新增：淡綠 */
      button[aria-label="➕ 新增箱型"],
      button[aria-label="➕ 新增商品列"],
      button[aria-label="🚀 開始計算與 3D 模擬"]{
        background:#D1FAE5 !important;
        border-color:#10B981 !important;
        color:#065F46 !important;
      }

      /* 刪除：淡紅 */
      button[aria-label="🗑️ 刪除勾選的箱型"],
      button[aria-label="🗑️ 刪除勾選商品列"],
      button[aria-label="🗑️ 刪除模板"]{
        background:#FEE2E2 !important;
        border-color:#EF4444 !important;
        color:#991B1B !important;
      }

      /* 儲存：淡藍 */
      button[aria-label="💾 儲存"]{
        background:#DBEAFE !important;
        border-color:#3B82F6 !important;
        color:#1E3A8A !important;
      }

      /* 載入：淡灰 */
      button[aria-label="⬇️ 載入"]{
        background:#E5E7EB !important;
        border-color:#9CA3AF !important;
        color:#111827 !important;
      }

      [data-testid="stPlotlyChart"]{
        background:#ffffff !important;
        border-radius:14px !important;
        border:1px solid #E5E7EB !important;
        padding:10px !important;
      }
    </style>
    """, unsafe_allow_html=True)


# =========================================================
# 6) State Init (永遠乾淨主資料)
# =========================================================
def init_state():
    if "box_presets" not in st.session_state:
        loaded = load_json(BOX_FILE, [])
        df = pd.DataFrame(loaded)
        st.session_state.box_presets = ensure_box_df(df)

    if "product_templates" not in st.session_state:
        st.session_state.product_templates = load_json(TPL_FILE, {})

    if "df" not in st.session_state:
        seed = pd.DataFrame([
            {"啟用": True, "商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.50, "數量": 5},
            {"啟用": True, "商品名稱": "紙袋",     "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5},
        ])
        st.session_state.df = ensure_product_df(seed)

    if "action" not in st.session_state:
        st.session_state.action = None


# =========================================================
# 7) Actions (唯一寫回點：按鈕)
# =========================================================
def set_action(name: str):
    st.session_state.action = name

def save_boxes_main(df_main: pd.DataFrame):
    df_main = ensure_box_df(df_main)
    st.session_state.box_presets = df_main
    save_json(BOX_FILE, df_main.to_dict(orient="records"))

def save_templates_main():
    save_json(TPL_FILE, st.session_state.product_templates)

def handle_actions(payload: Dict[str,Any]):
    action = st.session_state.action
    if not action:
        return
    st.session_state.action = None

    # --- Box actions ---
    if action == "box_add":
        with st.spinner("新增中..."):
            df_main = st.session_state.box_presets.copy()
            row = payload["new_box_row"]
            df_main = pd.concat([df_main, pd.DataFrame([row])], ignore_index=True)
            save_boxes_main(df_main)
        st.toast("✅ 已新增箱型並保存", icon="✅")
        st.rerun()

    if action == "box_apply_editor":
        # ✅ 最穩：只在按鈕時把 editor 副本寫回
        with st.spinner("套用中..."):
            edited = payload["box_editor_value"]
            cleaned = ensure_box_df(edited.drop(columns=["刪除"], errors="ignore"))
            # 刪除勾選
            if "刪除" in edited.columns:
                del_mask = edited["刪除"].apply(_clean_bool)
                cleaned = cleaned[~del_mask.values].reset_index(drop=True)
            save_boxes_main(cleaned)
        st.toast("✅ 外箱表格已套用保存", icon="✅")
        st.rerun()

    if action == "box_delete_rows":
        with st.spinner("刪除中..."):
            edited = payload["box_editor_value"]
            cleaned = ensure_box_df(edited.drop(columns=["刪除"], errors="ignore"))
            if "刪除" in edited.columns:
                del_mask = edited["刪除"].apply(_clean_bool)
                cleaned = cleaned[~del_mask.values].reset_index(drop=True)
            save_boxes_main(cleaned)
        st.toast("✅ 已刪除勾選箱型", icon="🗑️")
        st.rerun()

    # --- Template actions ---
    if action == "tpl_load":
        with st.spinner("讀入中..."):
            sel = payload["tpl_sel"]
            if sel != "(無)" and sel in st.session_state.product_templates:
                st.session_state.df = ensure_product_df(pd.DataFrame(st.session_state.product_templates[sel]))
        st.toast("✅ 已載入模板", icon="⬇️")
        st.rerun()

    if action == "tpl_save":
        nm = payload["tpl_save_name"]
        if not nm:
            st.warning("請先輸入模板名稱再儲存。")
            return
        with st.spinner("儲存中..."):
            st.session_state.product_templates[nm] = st.session_state.df.to_dict(orient="records")
            save_templates_main()
        st.toast("✅ 已儲存模板", icon="💾")
        st.rerun()

    if action == "tpl_delete":
        nm = payload["tpl_del_sel"]
        if nm == "(無)":
            st.warning("請選擇要刪除的模板。")
            return
        with st.spinner("刪除中..."):
            st.session_state.product_templates.pop(nm, None)
            save_templates_main()
        st.toast("✅ 已刪除模板", icon="🗑️")
        st.rerun()

    # --- Product actions ---
    if action == "prod_delete_rows":
        with st.spinner("刪除中..."):
            df = st.session_state.df.copy()
            if "刪除" in df.columns:
                df = df[~df["刪除"].apply(_clean_bool)].reset_index(drop=True)
            if "刪除" in df.columns:
                df = df.drop(columns=["刪除"], errors="ignore")
            st.session_state.df = ensure_product_df(df)
        st.toast("✅ 已刪除勾選商品列", icon="🗑️")
        st.rerun()

    # --- Run pack ---
    if action == "run_pack":
        st.session_state["_run_pack"] = True
        st.rerun()


# =========================================================
# 8) UI Components (模組化)
# =========================================================
def ui_header():
    st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="collapsed")
    inject_css()
    st.title("📦 3D裝箱系統")
    st.markdown("---")

def ui_layout_choice() -> str:
    return st.radio("版面配置", ["左右 50% / 50%", "上下（垂直）"], horizontal=True, index=0)

def ui_box_section() -> Dict[str,Any]:
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

    st.markdown("</div>", unsafe_allow_html=True)

    manual_box = {
        "使用": manual_use,
        "名稱": manual_name,
        "長": float(manual_L),
        "寬": float(manual_W),
        "高": float(manual_H),
        "空箱重量": float(manual_box_weight),
        "數量": int(manual_qty),
    }

    # --------------------------
    # ✅ 外箱 Editor（最穩定版）
    # --------------------------
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div style="font-weight:900;margin-bottom:8px;">📦 箱型管理（新增 / 修改 / 刪除 / 勾選使用）</div>', unsafe_allow_html=True)

    left, right = st.columns([1, 2], gap="large")

    with left:
        st.caption("新增一筆箱型（新增後可在右側表格直接修改）")
        new_box_name = st.text_input("新箱型名稱", value="", placeholder="例如：A款", key="new_box_name")
        nb1, nb2, nb3 = st.columns(3)
        new_L = nb1.number_input("新箱_長", value=45.0, step=1.0, min_value=0.0, key="new_L")
        new_W = nb2.number_input("新箱_寬", value=30.0, step=1.0, min_value=0.0, key="new_W")
        new_H = nb3.number_input("新箱_高", value=30.0, step=1.0, min_value=0.0, key="new_H")
        new_box_weight = st.number_input("新箱_空箱重量(kg)", value=0.5, step=0.1, min_value=0.0, key="new_box_weight")
        new_qty = st.number_input("新箱_數量", value=1, step=1, min_value=0, key="new_qty")

        new_row = {
            "使用": True,
            "名稱": (new_box_name.strip() or f"箱型_{len(st.session_state.box_presets)+1}"),
            "長": float(new_L),
            "寬": float(new_W),
            "高": float(new_H),
            "數量": int(new_qty),
            "空箱重量": float(new_box_weight),
        }

        st.button("➕ 新增箱型", use_container_width=True, on_click=set_action, args=("box_add",))
        st.button("🗑️ 刪除勾選的箱型", use_container_width=True, on_click=set_action, args=("box_delete_rows",))

        st.markdown("<hr style='border:none;border-top:1px solid #E5E7EB;margin:10px 0;'>", unsafe_allow_html=True)
        st.button("✅ 套用並保存外箱表格", use_container_width=True, on_click=set_action, args=("box_apply_editor",))

    with right:
        st.caption("✅ 勾選「使用」= 參與裝箱；「數量」可輸入 0；勾選「刪除」後按左側刪除")
        # 只給編輯用副本（重點）
        edit_df = st.session_state.box_presets.copy()
        edit_df = ensure_box_df(edit_df)
        edit_df["刪除"] = False

        edited = st.data_editor(
            edit_df,
            use_container_width=True,
            height=280,
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "使用": st.column_config.CheckboxColumn("使用"),
                "刪除": st.column_config.CheckboxColumn("刪除"),
                "數量": st.column_config.NumberColumn("數量", min_value=0, step=1, format="%d"),
                "長": st.column_config.NumberColumn("長", min_value=0.0, format="%.1f"),
                "寬": st.column_config.NumberColumn("寬", min_value=0.0, format="%.1f"),
                "高": st.column_config.NumberColumn("高", min_value=0.0, format="%.1f"),
                "空箱重量": st.column_config.NumberColumn("空箱重量", min_value=0.0, format="%.2f"),
            },
            key="box_editor",
        )

    st.markdown("</div>", unsafe_allow_html=True)

    return {
        "manual_box": manual_box,
        "box_editor_value": edited,
        "new_box_row": new_row,
        "order_name": order_name,
    }

def ui_product_section() -> Dict[str,Any]:
    st.markdown('<div class="section-header">2. 商品清單（直接編輯表格）</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)

    st.markdown('<div style="font-weight:900;margin-bottom:8px;">🧩 商品模板（載入 / 儲存 / 刪除）</div>', unsafe_allow_html=True)

    tpl_names = ["(無)"] + sorted(list(st.session_state.product_templates.keys()))
    left, mid, right = st.columns([2, 1, 2], gap="large")

    with left:
        tpl_sel = st.selectbox("商品初始值模板", tpl_names, key="tpl_sel")
        st.button("⬇️ 載入", use_container_width=True, on_click=set_action, args=("tpl_load",))

        tpl_del_sel = st.selectbox("要刪除的模板", tpl_names, key="tpl_del_sel")
        st.button("🗑️ 刪除模板", use_container_width=True, on_click=set_action, args=("tpl_delete",))

    with right:
        tpl_save_name = st.text_input("另存為模板名稱", value="", placeholder="例如：常用商品組合A", key="save_name")
        st.button("💾 儲存", use_container_width=True, on_click=set_action, args=("tpl_save",))
        st.caption("提示：模板/箱型都會永久記錄（存在 data/）")

    st.markdown("<hr style='border:none;border-top:1px solid #E5E7EB;margin:12px 0;'>", unsafe_allow_html=True)

    cbtn1, cbtn2 = st.columns([1, 3])
    with cbtn1:
        st.button("🗑️ 刪除勾選商品列", use_container_width=True, on_click=set_action, args=("prod_delete_rows",))
    with cbtn2:
        st.caption("✅ 可直接在表格修改；數量可輸入 0（不計算）；取消啟用也不計算")

    # 商品 editor 可直接改 session_state.df（商品不會產生 list checkbox 的坑那麼嚴重）
    # 但我仍然加一個刪除欄位，用按鈕刪除，避免即時寫回造成回滾感
    df = ensure_product_df(st.session_state.df.copy())
    df["刪除"] = False
    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        height=360,
        hide_index=True,
        column_config={
            "啟用": st.column_config.CheckboxColumn("啟用"),
            "刪除": st.column_config.CheckboxColumn("刪除"),
            "數量": st.column_config.NumberColumn("數量", min_value=0, step=1, format="%d"),
            "長": st.column_config.NumberColumn("長", min_value=0.0, format="%.1f"),
            "寬": st.column_config.NumberColumn("寬", min_value=0.0, format="%.1f"),
            "高": st.column_config.NumberColumn("高", min_value=0.0, format="%.1f"),
            "重量(kg)": st.column_config.NumberColumn("重量(kg)", min_value=0.0, format="%.2f"),
        },
        key="product_editor",
    )
    st.session_state.df = ensure_product_df(edited_df.drop(columns=["刪除"], errors="ignore"))

    st.markdown("</div>", unsafe_allow_html=True)

    return {
        "tpl_sel": tpl_sel,
        "tpl_del_sel": tpl_del_sel,
        "tpl_save_name": (tpl_save_name or "").strip(),
    }

def ui_run_button():
    st.markdown("---")
    st.button("🚀 開始計算與 3D 模擬", use_container_width=True, on_click=set_action, args=("run_pack",))


# =========================================================
# 9) Report / Plotly
# =========================================================
def build_plotly_figure(bins_result, bin_defs_used, unique_products):
    fig = go.Figure()
    fig.update_layout(
        template=None,
        paper_bgcolor="white",
        plot_bgcolor="white",
        font=dict(color="black"),
        autosize=True,
        scene=dict(
            bgcolor="white",
            xaxis=dict(backgroundcolor="white", showbackground=True, gridcolor="#BDBDBD", linecolor="#000000", showline=True, zerolinecolor="#000000"),
            yaxis=dict(backgroundcolor="white", showbackground=True, gridcolor="#BDBDBD", linecolor="#000000", showline=True, zerolinecolor="#000000"),
            zaxis=dict(backgroundcolor="white", showbackground=True, gridcolor="#BDBDBD", linecolor="#000000", showline=True, zerolinecolor="#000000"),
            aspectmode="data",
            camera=dict(eye=dict(x=1.6, y=1.6, z=1.6)),
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
            name=label, showlegend=True
        ))

    offsets = []
    cur_x = 0.0
    gap = 8.0
    for bdef in bin_defs_used:
        offsets.append(cur_x)
        cur_x += float(bdef["長"]) + gap

    for bi, bdef in enumerate(bin_defs_used):
        ox = offsets[bi]
        label = f'外箱_{bi+1} ({bdef["名稱"]})' if bi > 0 else f'外箱 ({bdef["名稱"]})'
        draw_box(ox, bdef["長"], bdef["寬"], bdef["高"], label)

    for bi, placed in enumerate(bins_result):
        ox = offsets[bi]
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
    return fig

def ui_report_and_download(order_name, candidate_bins, manual_box):
    if not st.session_state.get("_run_pack"):
        return

    st.session_state["_run_pack"] = False

    with st.spinner("正在進行智慧裝箱運算..."):
        candidate_bins = candidate_bins
        if not candidate_bins:
            st.error("請至少勾選 1 種外箱並設定數量 > 0（手動箱或預存箱都可以）。")
            return

        max_bin = max(candidate_bins, key=lambda b: b["長"] * b["寬"] * b["高"])
        items, requested_counts, unique_products, total_qty = build_items_from_df(st.session_state.df, max_bin)

        if total_qty == 0:
            st.warning("目前沒有任何商品被納入計算（請確認：啟用=勾選 且 數量>0）。")
            return

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

        used_box_total_vol = sum(b["長"] * b["寬"] * b["高"] for b in bin_defs_used) if bin_defs_used else (max_bin["長"] * max_bin["寬"] * max_bin["高"])
        used_box_total_weight = sum(_to_float(b.get("空箱重量", 0.0)) for b in bin_defs_used) if bin_defs_used else _to_float(manual_box.get("空箱重量", 0.0))
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
        if bin_defs_used:
            for bdef in bin_defs_used:
                key = f'{bdef["名稱"]} ({bdef["長"]}×{bdef["寬"]}×{bdef["高"]})'
                box_summary[key] = box_summary.get(key, 0) + 1
        else:
            key = f'{max_bin["名稱"]} ({max_bin["長"]}×{max_bin["寬"]}×{max_bin["高"]})'
            box_summary[key] = 1
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

        fig = build_plotly_figure(bins_result, bin_defs_used, unique_products)

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

        st.download_button(
            label="📥 下載完整裝箱報告 (.html)",
            data=full_html_content,
            file_name=file_name,
            mime="text/html",
            use_container_width=True,
        )
        st.plotly_chart(fig, use_container_width=True, theme=None, config={'displayModeBar': False})


# =========================================================
# 10) Main
# =========================================================
def main():
    ui_header()
    init_state()

    layout_mode = ui_layout_choice()

    # UI 先畫，再集中處理 actions（避免一次按就回滾）
    box_payload = {}
    prod_payload = {}

    if layout_mode == "左右 50% / 50%":
        left, right = st.columns([1, 1], gap="large")
        with left:
            box_payload = ui_box_section()
        with right:
            prod_payload = ui_product_section()
    else:
        box_payload = ui_box_section()
        st.markdown("---")
        prod_payload = ui_product_section()

    ui_run_button()

    # 收集 payload 給 action handler
    payload = {}
    payload.update(box_payload)
    payload.update(prod_payload)

    # 先處理 actions（寫回只在按鈕）
    handle_actions(payload)

    # 如果 run_pack 旗標，才跑報告
    manual_box = payload.get("manual_box", {"使用": True, "名稱":"手動箱", "長":35, "寬":25, "高":20, "空箱重量":0.5, "數量":1})
    candidate_bins = build_candidate_bins(manual_box, st.session_state.box_presets)
    ui_report_and_download(payload.get("order_name","訂單"), candidate_bins, manual_box)


if __name__ == "__main__":
    main()
