import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import datetime
import math
import json
from itertools import permutations

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
# - 先低 z -> 低 y -> 低 x（人類靠牆）
# - 同一點上，挑更省路徑的姿態
# ==========================
def pack_one_bin(items, box):
    L, W, H = box["長"], box["寬"], box["高"]
    placed = []
    points = {(0.0, 0.0, 0.0)}

    def score_candidate(x, y, z, dx, dy, dz):
        # 越靠牆越好；底面積越小越不擋路；高度越低越好（避免早早堆高擋住）
        base = dx * dy
        return (z, y, x, base, dz)

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
                cand_box = {"x": px, "y": py, "z": pz, "dx": dx, "dy": dy, "dz": dz}
                if any(_collide(cand_box, p) for p in placed):
                    continue

                s = score_candidate(px, py, pz, dx, dy, dz)
                if best is None or s < best_s:
                    best = cand_box
                    best_s = s

        if best is None:
            it["placed"] = False
            continue

        it["placed"] = True
        it["x"], it["y"], it["z"] = best["x"], best["y"], best["z"]
        it["dx"], it["dy"], it["dz"] = best["dx"], best["dy"], best["dz"]

        placed.append({
            "name": it["name"],
            "x": it["x"], "y": it["y"], "z": it["z"],
            "dx": it["dx"], "dy": it["dy"], "dz": it["dz"],
            "weight": it["weight"],
        })

        # 新極點
        new_pts = [
            (it["x"] + it["dx"], it["y"], it["z"]),
            (it["x"], it["y"] + it["dy"], it["z"]),
            (it["x"], it["y"], it["z"] + it["dz"]),
        ]
        for nx, ny, nz in new_pts:
            if nx <= L and ny <= W and nz <= H:
                points.add((float(nx), float(ny), float(nz)))

        # 清掉盒內點，避免亂塞中間
        points = {p for p in points if not _point_is_covered(p[0], p[1], p[2], placed)}

    return placed

# ==========================
# 改善「單箱優先」與「多箱選擇」
# 1) 先對每個可用箱(含手動/預存、含數量)嘗試「裝完全部」，
#    成功就選浪費空間最少的那一箱（= 不會硬開第2箱）
# 2) 若無任何單箱可全裝，才開始逐箱：
#    每次選「能裝進最多件 + 空間浪費最少」的那個箱實例
# ==========================
def try_pack_all_in_one_bin(items, candidate_bins):
    best = None
    best_metric = None
    total_items = len(items)

    for b in candidate_bins:
        # 多種排序策略再試（避免貪婪卡住）
        strategies = [
            ("base_area", lambda it: -(it["l"] * it["w"])),
            ("volume", lambda it: -(it["l"] * it["w"] * it["h"])),
            ("max_edge", lambda it: -max(it["l"], it["w"], it["h"])),
        ]

        for _, keyfn in strategies:
            items_copy = [dict(it) for it in items]
            items_copy.sort(key=keyfn)

            placed = pack_one_bin(items_copy, b)
            fitted = len(placed)
            if fitted == total_items:
                # 成功：選浪費最少
                used_vol = sum(p["dx"] * p["dy"] * p["dz"] for p in placed)
                bin_vol = b["長"] * b["寬"] * b["高"]
                waste = bin_vol - used_vol
                metric = (waste, bin_vol)  # waste 小優先
                if best is None or metric < best_metric:
                    best = {"bins": [placed], "bin_defs": [b], "unplaced": []}
                    best_metric = metric

    return best

def greedy_multi_bin_pack(items, candidate_bins):
    remaining = [dict(it) for it in items]
    bins_result = []
    bin_defs_used = []
    max_loops = 200

    for _ in range(max_loops):
        if not remaining:
            break
        best_choice = None
        best_metric = None

        for b in candidate_bins:
            # 一樣多策略試，取該箱最好的結果
            best_for_bin = None
            best_for_bin_metric = None

            strategies = [
                ("base_area", lambda it: -(it["l"] * it["w"])),
                ("volume", lambda it: -(it["l"] * it["w"] * it["h"])),
                ("max_edge", lambda it: -max(it["l"], it["w"], it["h"])),
            ]

            for _, keyfn in strategies:
                items_copy = [dict(it) for it in remaining]
                items_copy.sort(key=keyfn)

                placed = pack_one_bin(items_copy, b)
                fitted = len(placed)
                if fitted == 0:
                    continue
                used_vol = sum(p["dx"] * p["dy"] * p["dz"] for p in placed)
                bin_vol = b["長"] * b["寬"] * b["高"]
                utilization = used_vol / bin_vol if bin_vol > 0 else 0.0
                waste = bin_vol - used_vol

                # 主目標：裝最多件，其次浪費最少，其次箱越小越好（避免大箱塞少量）
                m = (-fitted, waste, bin_vol, -utilization)
                if best_for_bin is None or m < best_for_bin_metric:
                    best_for_bin = placed
                    best_for_bin_metric = m

            if best_for_bin is None:
                continue

            fitted = len(best_for_bin)
            used_vol = sum(p["dx"] * p["dy"] * p["dz"] for p in best_for_bin)
            bin_vol = b["長"] * b["寬"] * b["高"]
            waste = bin_vol - used_vol
            metric = (-fitted, waste, bin_vol)

            if best_choice is None or metric < best_metric:
                best_choice = (b, best_for_bin)
                best_metric = metric

        if best_choice is None:
            break

        chosen_bin, placed = best_choice
        bins_result.append(placed)
        bin_defs_used.append(chosen_bin)

        # 把已放入的 items 從 remaining 移除（用 name+dx+dy+dz+weight 計數移除）
        # 注意：remaining 內每個 it 是單件，placed 也是單件，做 multiset 移除
        placed_keys = []
        for p in placed:
            placed_keys.append((p["name"], round(p["dx"], 6), round(p["dy"], 6), round(p["dz"], 6), round(p["weight"], 6)))

        # 建立 remaining 的 key list
        new_remaining = []
        used = {}
        for k in placed_keys:
            used[k] = used.get(k, 0) + 1

        for it in remaining:
            k = (it["name"], round(it["oris"][0][0], 6), round(it["oris"][0][1], 6), round(it["oris"][0][2], 6), round(it["weight"], 6))
            # 上面用 it["oris"][0] 不可靠（不同 rotation），所以改成用 it 的原始尺寸做 key
            # 我們在 build_items 時會保留 it["l"], it["w"], it["h"]
        # 重新做：以 (name,l,w,h,weight) 移除
        used2 = {}
        for it in remaining:
            pass

        used2 = {}
        for p in placed:
            # placed 只有當下放置姿態 dx/dy/dz，原本 l/w/h 可能不同旋轉，所以不能用原 l/w/h
            # 因此改用：在 build_items 時為每一件商品加上唯一 id，placed 也會帶 id
            pass

        # -> 這段靠 id 來做最穩，所以我們在外層保證每件 item 有 id，placed 也回傳 id
        # 由於 pack_one_bin 目前沒帶 id，我們在 pack_one_bin 前就把 id 帶進 placed
        # 這裡採取簡化：直接用座標回寫的方式是難的
        # 改：在 pack_one_bin 內 placed.append 時把 it["_id"] 一起存
        # 因此此函式需要配合 build_items 與 pack_one_bin（下方會處理）
        raise RuntimeError("INTERNAL_SYNC_ERROR")

    return None

# ==========================
# 這裡把 greedy_multi_bin_pack 改成用 _id 安全移除（避免誤刪）
# ==========================
def greedy_multi_bin_pack_id(items, candidate_bins):
    remaining = [dict(it) for it in items]
    bins_result = []
    bin_defs_used = []
    max_loops = 200

    for _ in range(max_loops):
        if not remaining:
            break

        best_choice = None
        best_metric = None
        remaining_ids = set(it["_id"] for it in remaining)

        for b in candidate_bins:
            best_for_bin = None
            best_for_bin_metric = None

            strategies = [
                ("base_area", lambda it: -(it["l"] * it["w"])),
                ("volume", lambda it: -(it["l"] * it["w"] * it["h"])),
                ("max_edge", lambda it: -max(it["l"], it["w"], it["h"])),
            ]

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
                utilization = used_vol / bin_vol if bin_vol > 0 else 0.0

                # 主：裝最多；次：浪費少；次：箱小
                m = (-fitted, waste, bin_vol, -utilization)
                if best_for_bin is None or m < best_for_bin_metric:
                    best_for_bin = placed
                    best_for_bin_metric = m

            if best_for_bin is None:
                continue

            fitted = len(best_for_bin)
            used_vol = sum(p["dx"] * p["dy"] * p["dz"] for p in best_for_bin)
            bin_vol = b["長"] * b["寬"] * b["高"]
            waste = bin_vol - used_vol
            metric = (-fitted, waste, bin_vol)

            if best_choice is None or metric < best_metric:
                best_choice = (b, best_for_bin)
                best_metric = metric

        if best_choice is None:
            break

        chosen_bin, placed = best_choice
        bins_result.append(placed)
        bin_defs_used.append(chosen_bin)

        placed_ids = set(p["_id"] for p in placed)
        # 防呆：避免任何不在 remaining 的 id
        placed_ids = placed_ids.intersection(remaining_ids)
        remaining = [it for it in remaining if it["_id"] not in placed_ids]

    return bins_result, bin_defs_used, remaining

# ==========================
# pack_one_bin：加上 _id 回傳，讓多箱能正確移除
# ==========================
def pack_one_bin(items, box):
    L, W, H = box["長"], box["寬"], box["高"]
    placed = []
    points = {(0.0, 0.0, 0.0)}

    def score_candidate(x, y, z, dx, dy, dz):
        base = dx * dy
        return (z, y, x, base, dz)

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
                cand_box = {"x": px, "y": py, "z": pz, "dx": dx, "dy": dy, "dz": dz}
                if any(_collide(cand_box, p) for p in placed):
                    continue

                s = score_candidate(px, py, pz, dx, dy, dz)
                if best is None or s < best_s:
                    best = cand_box
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
# 依照勾選的箱型 + 數量，生成「箱實例清單」
# ==========================
def build_candidate_bins(manual_box, saved_boxes_df):
    bins = []

    # 手動箱：可勾選是否使用 + 數量
    if manual_box.get("使用", False):
        qty = max(_to_int(manual_box.get("數量", 0)), 0)
        if qty > 0:
            for i in range(qty):
                bins.append({
                    "名稱": manual_box.get("名稱", "手動箱"),
                    "長": _to_float(manual_box["長"]),
                    "寬": _to_float(manual_box["寬"]),
                    "高": _to_float(manual_box["高"]),
                    "空箱重量": _to_float(manual_box.get("空箱重量", 0.0)),
                })

    # 預存箱：每列可勾選是否使用 + 數量
    if saved_boxes_df is not None and len(saved_boxes_df) > 0:
        for _, r in saved_boxes_df.iterrows():
            use = bool(r.get("使用", False))
            if not use:
                continue
            qty = max(_to_int(r.get("數量", 0)), 0)
            if qty <= 0:
                continue
            for i in range(qty):
                bins.append({
                    "名稱": str(r.get("名稱", "外箱")).strip() or "外箱",
                    "長": _to_float(r.get("長", 0)),
                    "寬": _to_float(r.get("寬", 0)),
                    "高": _to_float(r.get("高", 0)),
                    "空箱重量": _to_float(r.get("空箱重量", 0.0)),
                })

    # 過濾不合法
    bins = [b for b in bins if b["長"] > 0 and b["寬"] > 0 and b["高"] > 0]
    return bins

# ==========================
# 商品：只取「啟用=是」且 數量>0 的列
# 允許數量=0（不計算）
# ==========================
def build_items_from_df(df, box_for_oris):
    # box_for_oris: 用於先過濾 rotations（用最大箱做上限，避免候選空）
    # 但實際裝箱會再用每個箱尺寸判斷 inside_box
    maxL = box_for_oris["長"]
    maxW = box_for_oris["寬"]
    maxH = box_for_oris["高"]

    items = []
    requested_counts = {}
    unique_products = []
    total_qty = 0
    _id_counter = 1

    df2 = df.copy()
    if "啟用" not in df2.columns:
        df2["啟用"] = True

    df2["長"] = df2["長"].apply(_to_float)
    df2["寬"] = df2["寬"].apply(_to_float)
    df2["高"] = df2["高"].apply(_to_float)
    df2["重量(kg)"] = df2["重量(kg)"].apply(_to_float)
    df2["數量"] = df2["數量"].apply(_to_int)

    # 排序：底面積大先（更像人類先放大件）
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
            # 用最大箱都放不進，直接留空（後面一定會 unfit）
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
# Streamlit Page
# ==========================
st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="collapsed")

# CSS（維持你原本）
st.markdown("""
<style>
    .stApp { background-color: #ffffff !important; color: #000000 !important; }
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="stSidebarCollapsedControl"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    .stDeployButton { display: none !important; }
    footer { display: none !important; }
    #MainMenu { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stHeader"] { background-color: transparent !important; pointer-events: none; }

    div[data-baseweb="input"] input,
    div[data-baseweb="select"] div,
    .stDataFrame, .stTable {
        color: #000000 !important;
        background-color: #f9f9f9 !important;
        border-color: #cccccc !important;
    }

    .section-header {
        font-size: 1.2rem;
        font-weight: bold;
        color: #333;
        margin-top: 10px;
        margin-bottom: 5px;
        border-left: 5px solid #FF4B4B;
        padding-left: 10px;
    }

    .report-card {
        font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
        padding: 20px;
        border: 2px solid #e0e0e0;
        border-radius: 10px;
        background: #ffffff;
        color: #333333;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }

    .js-plotly-plot .plotly .bg { fill: #ffffff !important; }
    .xtick text, .ytick text, .ztick text {
        fill: #000000 !important;
        font-weight: bold !important;
    }

    .block-container {
        padding-top: 2rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統")
st.markdown("---")

# ==========================
# Session State init
# ==========================
if "box_presets" not in st.session_state:
    st.session_state.box_presets = pd.DataFrame(
        columns=["使用", "名稱", "長", "寬", "高", "數量", "空箱重量"]
    )

if "product_templates" not in st.session_state:
    st.session_state.product_templates = {}  # name -> list[dict]

# 預設商品表（移除彎折欄，新增啟用欄）
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(
        [
            {"啟用": True, "商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5},
            {"啟用": True, "商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5},
        ]
    )

# ==========================
# Layout
# ==========================
col_left, col_right = st.columns([1, 2], gap="large")

# ==========================
# 1. 訂單與外箱設定（新增：箱型管理 / 勾選 / 數量）
# ==========================
with col_left:
    st.markdown('<div class="section-header">1. 訂單與外箱設定</div>', unsafe_allow_html=True)

    order_name = st.text_input("訂單名稱", value="訂單_20241208")

    st.caption("外箱尺寸 (cm) - 手動 Key in（可選擇是否參與裝箱）")
    c1, c2, c3 = st.columns(3)
    manual_L = c1.number_input("長", value=35.0, step=1.0, key="manual_L")
    manual_W = c2.number_input("寬", value=25.0, step=1.0, key="manual_W")
    manual_H = c3.number_input("高", value=20.0, step=1.0, key="manual_H")
    manual_box_weight = st.number_input("空箱重量 (kg)", value=0.5, step=0.1, key="manual_box_weight")

    c4, c5, c6 = st.columns([1, 1, 2])
    manual_use = c4.checkbox("使用手動箱", value=True)
    manual_qty = c5.number_input("手動箱數量", value=1, step=1, min_value=0)
    manual_name = c6.text_input("手動箱命名", value="手動箱")

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    st.caption("外箱尺寸 - 預存箱型（可無限新增、命名、刪除、數量）")

    with st.expander("📦 箱型管理（新增 / 刪除 / 勾選使用）", expanded=True):
        add_c1, add_c2 = st.columns([2, 3])
        with add_c1:
            new_box_name = st.text_input("新箱型名稱", value="", placeholder="例如：A款")
            nb1, nb2, nb3 = st.columns(3)
            new_L = nb1.number_input("新箱_長", value=45.0, step=1.0, min_value=0.0)
            new_W = nb2.number_input("新箱_寬", value=30.0, step=1.0, min_value=0.0)
            new_H = nb3.number_input("新箱_高", value=30.0, step=1.0, min_value=0.0)
            new_box_weight = st.number_input("新箱_空箱重量(kg)", value=0.5, step=0.1, min_value=0.0)
            new_qty = st.number_input("新箱_數量", value=1, step=1, min_value=0)
            if st.button("➕ 新增箱型", use_container_width=True):
                nm = new_box_name.strip() if new_box_name.strip() else f"箱型_{len(st.session_state.box_presets)+1}"
                row = {
                    "使用": True,
                    "名稱": nm,
                    "長": float(new_L),
                    "寬": float(new_W),
                    "高": float(new_H),
                    "數量": int(new_qty),
                    "空箱重量": float(new_box_weight)
                }
                st.session_state.box_presets = pd.concat([st.session_state.box_presets, pd.DataFrame([row])], ignore_index=True)

        with add_c2:
            st.caption("勾選要參與裝箱的箱型，並調整數量（可輸入 0）")
            box_df = st.data_editor(
                st.session_state.box_presets,
                num_rows="dynamic",
                use_container_width=True,
                height=240,
                column_config={
                    "使用": st.column_config.CheckboxColumn(),
                    "數量": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
                    "長": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
                    "寬": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
                    "高": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
                    "空箱重量": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
                },
            )
            st.session_state.box_presets = box_df

# ==========================
# 2. 商品清單（新增：模板保存/載入 + 勾選啟用 + 數量允許0）
# ==========================
with col_right:
    st.markdown('<div class="section-header">2. 商品清單 (直接編輯表格)</div>', unsafe_allow_html=True)

    top1, top2, top3 = st.columns([2, 2, 3])
    with top1:
        tpl_names = ["(無)"] + sorted(list(st.session_state.product_templates.keys()))
        tpl_sel = st.selectbox("商品初始值模板", tpl_names)
    with top2:
        if st.button("⬇️ 載入模板", use_container_width=True):
            if tpl_sel != "(無)" and tpl_sel in st.session_state.product_templates:
                st.session_state.df = pd.DataFrame(st.session_state.product_templates[tpl_sel])
    with top3:
        save_name = st.text_input("另存為模板名稱", value="", placeholder="例如：常用商品組合A")
        if st.button("💾 儲存目前商品為模板", use_container_width=True):
            nm = save_name.strip()
            if nm:
                st.session_state.product_templates[nm] = st.session_state.df.to_dict(orient="records")

    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        height=280,
        column_config={
            "啟用": st.column_config.CheckboxColumn(),
            "數量": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),  # ✅ 允許 0
            "長": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "寬": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "高": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "重量(kg)": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
        }
    )
    st.session_state.df = edited_df

st.markdown("---")

b1, b2, b3 = st.columns([1, 2, 1])
with b2:
    run_button = st.button("🚀 開始計算與 3D 模擬", type="primary", use_container_width=True)

# ==========================
# Run
# ==========================
if run_button:
    with st.spinner("正在進行智慧裝箱運算..."):

        # 生成可用箱（手動 + 預存）
        manual_box = {
            "使用": manual_use,
            "名稱": manual_name,
            "長": float(manual_L),
            "寬": float(manual_W),
            "高": float(manual_H),
            "空箱重量": float(manual_box_weight),
            "數量": int(manual_qty),
        }
        candidate_bins = build_candidate_bins(manual_box, st.session_state.box_presets)

        if not candidate_bins:
            st.error("請至少勾選 1 種外箱並設定數量 > 0（手動箱或預存箱都可以）。")
            st.stop()

        # 用最大箱當作 rotations 的上限（避免先被過濾掉）
        max_bin = max(candidate_bins, key=lambda b: b["長"] * b["寬"] * b["高"])
        items, requested_counts, unique_products, total_qty = build_items_from_df(st.session_state.df, max_bin)

        if total_qty == 0:
            st.warning("目前沒有任何商品被納入計算（請確認：啟用=勾選 且 數量>0）。")
            st.stop()

        # 先「單箱優先」：只要任一可用箱能裝完，就不開第2箱
        one_bin_solution = try_pack_all_in_one_bin(items, candidate_bins)

        if one_bin_solution is not None:
            bins_result = one_bin_solution["bins"]
            bin_defs_used = one_bin_solution["bin_defs"]
            remaining = []
        else:
            # 多箱：逐箱挑最佳（能裝最多 + 浪費最少）
            bins_result, bin_defs_used, remaining = greedy_multi_bin_pack_id(items, candidate_bins)

        # 統計
        packed_counts = {}
        total_vol = 0.0
        total_net_weight = 0.0

        for bi, b in enumerate(bins_result):
            for it in b:
                packed_counts[it["name"]] = packed_counts.get(it["name"], 0) + 1
                total_vol += it["dx"] * it["dy"] * it["dz"]
                total_net_weight += it["weight"]

        used_box_count = len(bins_result) if bins_result else 0
        used_box_count = max(1, used_box_count)

        # 空間利用率：以「實際使用的箱數 + 該箱體積」計算
        used_box_total_vol = 0.0
        used_box_total_weight = 0.0
        for bdef in bin_defs_used:
            used_box_total_vol += bdef["長"] * bdef["寬"] * bdef["高"]
            used_box_total_weight += bdef.get("空箱重量", 0.0)

        utilization = (total_vol / used_box_total_vol * 100) if used_box_total_vol > 0 else 0.0
        gross_weight = total_net_weight + used_box_total_weight

        # 缺貨/裝不下清單
        all_fitted = True
        missing_items_html = ""
        for name, req_qty in requested_counts.items():
            real_qty = packed_counts.get(name, 0)
            if real_qty < req_qty:
                all_fitted = False
                diff = req_qty - real_qty
                missing_items_html += f"<li style='color: #D8000C; background-color: #FFD2D2; padding: 8px; margin: 5px 0; border-radius: 4px; font-weight: bold;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status_html = (
            "<h3 style='color: #155724; background-color: #d4edda; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #c3e6cb;'>✅ 完美！所有商品皆已裝入。</h3>"
            if all_fitted
            else f"<h3 style='color: #721c24; background-color: #f8d7da; padding: 10px; border-radius: 8px; border: 1px solid #f5c6cb;'>❌ 注意：有部分商品裝不下！</h3><ul style='padding-left: 20px;'>{missing_items_html}</ul>"
        )

        tw_time = _now_tw()
        now_str = tw_time.strftime("%Y-%m-%d %H:%M")
        file_time_str = tw_time.strftime("%Y%m%d_%H%M")

        # 外箱尺寸文字：若多箱不同尺寸，列出「使用箱型與數量」
        box_summary = {}
        for bdef in bin_defs_used:
            key = f'{bdef["名稱"]} ({bdef["長"]}×{bdef["寬"]}×{bdef["高"]})'
            box_summary[key] = box_summary.get(key, 0) + 1
        box_summary_html = "<br>".join([f"{k} × {v} 箱" for k, v in box_summary.items()]) if box_summary else f"{max_bin['長']} x {max_bin['寬']} x {max_bin['高']} cm"

        report_html = f"""
        <div class="report-card">
            <h2 style="margin-top:0; color: #2c3e50; border-bottom: 3px solid #2c3e50; padding-bottom: 10px;">📋 訂單裝箱報告</h2>
            <table style="border-collapse: collapse; margin-bottom: 20px; width: 100%; font-size: 1.1em;">
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">📝 訂單名稱:</td><td style="color: #0056b3; font-weight: bold;">{order_name}</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">🕒 計算時間:</td><td>{now_str} (台灣時間)</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">📦 使用外箱:</td><td>{box_summary_html}</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">⚖️ 內容淨重:</td><td>{total_net_weight:.2f} kg</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555; color: #d9534f;">🚛 本次總重:</td><td style="color: #d9534f; font-weight: bold; font-size: 1.2em;">{gross_weight:.2f} kg</td></tr>
                <tr><td style="padding: 12px 5px; font-weight: bold; color: #555;">📊 空間利用率:</td><td>{utilization:.2f}%</td></tr>
            </table>
            {status_html}
        </div>
        """

        st.markdown('<div class="section-header">3. 裝箱結果與模擬</div>', unsafe_allow_html=True)
        st.markdown(report_html, unsafe_allow_html=True)

        # ==========================
        # 3D Plot：多箱（不同箱型也可）
        # - 每箱依序往 x 方向平移顯示
        # ==========================
        fig = go.Figure()

        axis_config = dict(
            backgroundcolor="white",
            showbackground=True,
            zerolinecolor="#000000",
            gridcolor="#999999",
            linecolor="#000000",
            showgrid=True,
            showline=True,
            tickfont=dict(color="black", size=12, family="Arial Black"),
            title=dict(font=dict(color="black", size=14, family="Arial Black"))
        )

        fig.update_layout(
            template="plotly_white",
            font=dict(color="black"),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            autosize=True,
            scene=dict(
                xaxis={**axis_config, 'title': '長 (L)'},
                yaxis={**axis_config, 'title': '寬 (W)'},
                zaxis={**axis_config, 'title': '高 (H)'},
                aspectmode='data',
                camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))
            ),
            margin=dict(t=30, b=0, l=0, r=0),
            height=600,
            legend=dict(
                x=0, y=1,
                xanchor="left",
                yanchor="top",
                font=dict(color="black", size=13),
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="#000000",
                borderwidth=1
            )
        )

        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        # 箱子間距：用該箱長度+固定空隙累計
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
        gap = 8.0  # 固定空隙
        for bi, bdef in enumerate(bin_defs_used if bin_defs_used else [max_bin]):
            offsets.append(cur_x)
            cur_x += float(bdef["長"]) + gap

        # 畫箱與內容
        if not bins_result:
            bdef = max_bin
            draw_box(0, bdef["長"], bdef["寬"], bdef["高"], "外箱")
        else:
            for bi, placed in enumerate(bins_result):
                bdef = bin_defs_used[bi]
                ox = offsets[bi]
                label = "外箱" if bi == 0 else f"外箱_{bi+1}"
                # 顯示箱型名稱
                if bdef.get("名稱"):
                    label = f'{label} ({bdef["名稱"]})'
                draw_box(ox, bdef["長"], bdef["寬"], bdef["高"], label)

                for it in placed:
                    name = it["name"]
                    color = product_colors.get(name, "#888")
                    x, y, z = it["x"], it["y"], it["z"]
                    dx, dy, dz = it["dx"], it["dy"], it["dz"]
                    wgt = it["weight"]

                    hover_text = f"{name}<br>實際佔用: {dx}x{dy}x{dz}<br>重量: {wgt:.2f}kg<br>位置:({x},{y},{z})<br>箱: {bi+1}"

                    fig.add_trace(go.Mesh3d(
                        x=[ox+x, ox+x+dx, ox+x+dx, ox+x, ox+x, ox+x+dx, ox+x+dx, ox+x],
                        y=[y, y, y+dy, y+dy, y, y, y+dy, y+dy],
                        z=[z, z, z, z, z+dz, z+dz, z+dz, z+dz],
                        i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
                        j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
                        k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                        color=color, opacity=1, name=name, showlegend=True,
                        text=hover_text, hoverinfo='text',
                        lighting=dict(ambient=0.8, diffuse=0.8, specular=0.1, roughness=0.5),
                        lightposition=dict(x=1000, y=1000, z=2000)
                    ))

                    fig.add_trace(go.Scatter3d(
                        x=[ox+x, ox+x+dx, ox+x+dx, ox+x, ox+x, ox+x, ox+x+dx, ox+x+dx, ox+x, ox+x, ox+x, ox+x, ox+x+dx, ox+x+dx, ox+x+dx, ox+x+dx],
                        y=[y, y, y+dy, y+dy, y, y, y, y, y+dy, y+dy, y, y+dy, y+dy, y, y, y+dy],
                        z=[z, z, z, z, z, z+dz, z+dz, z+dz, z+dz, z+dz, z, z+dz, z+dz, z+dz, z, z],
                        mode='lines', line=dict(color='#000000', width=2), showlegend=False
                    ))

        # legend 去重
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # 下載報告
        full_html_content = f"""
        <html>
        <head>
            <title>裝箱報告 - {order_name}</title>
            <meta charset="utf-8">
        </head>
        <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f4f4f4; padding: 30px; color: #333;">
            <div style="max-width: 1000px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 5px 15px rgba(0,0,0,0.1);">
                {report_html.replace('class="report-card"', '')}
                <div style="margin-top: 30px;">
                    <h3 style="border-bottom: 2px solid #eee; padding-bottom: 10px;">🧊 3D 模擬視圖</h3>
                    {fig.to_html(include_plotlyjs='cdn', full_html=False)}
                </div>
            </div>
        </body>
        </html>
        """
        file_name = f"{order_name.replace(' ', '_')}_{file_time_str}_總數{total_qty}.html"

        st.download_button(
            label="📥 下載完整裝箱報告 (.html)",
            data=full_html_content,
            file_name=file_name,
            mime="text/html",
            type="primary"
        )

        st.plotly_chart(fig, use_container_width=True, theme=None, config={'displayModeBar': False})
