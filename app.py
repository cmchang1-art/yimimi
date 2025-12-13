import streamlit as st
import pandas as pd
import datetime
import math
from itertools import permutations
import plotly.graph_objects as go

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
        return (z, y, x, base, dz)  # 越靠牆(低z低y低x)越優先

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
# 單箱優先
# ==========================
def try_pack_all_in_one_bin(items, candidate_bins):
    best = None
    best_metric = None
    total_items = len(items)

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
                metric = (waste, bin_vol)
                if best is None or metric < best_metric:
                    best = {"bins": [placed], "bin_defs": [b], "unplaced": []}
                    best_metric = metric

    return best

# ==========================
# 多箱：逐箱挑最佳（用 _id 安全移除）
# ==========================
def greedy_multi_bin_pack_id(items, candidate_bins):
    remaining = [dict(it) for it in items]
    bins_result = []
    bin_defs_used = []
    max_loops = 200

    strategies = [
        ("base_area", lambda it: -(it["l"] * it["w"])),
        ("volume", lambda it: -(it["l"] * it["w"] * it["h"])),
        ("max_edge", lambda it: -max(it["l"], it["w"], it["h"])),
    ]

    for _ in range(max_loops):
        if not remaining:
            break

        best_choice = None
        best_metric = None
        remaining_ids = set(it["_id"] for it in remaining)

        for b in candidate_bins:
            best_for_bin = None
            best_for_bin_metric = None

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

        placed_ids = set(p["_id"] for p in placed).intersection(remaining_ids)
        remaining = [it for it in remaining if it["_id"] not in placed_ids]

    return bins_result, bin_defs_used, remaining

# ==========================
# 依照勾選的箱型 + 數量，生成「箱實例清單」
# ==========================
def build_candidate_bins(manual_box, saved_boxes_df):
    bins = []

    if manual_box.get("使用", False):
        qty = max(_to_int(manual_box.get("數量", 0)), 0)
        if qty > 0:
            for _ in range(qty):
                bins.append({
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
def build_items_from_df(df, box_for_oris):
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
# UI / Page
# ==========================
st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="collapsed")

# ✅ UI 修正：按鈕顏色 / 文字可見 / expander header / caption / 表格
st.markdown("""
<style>
  .stApp { background-color:#ffffff !important; color:#111 !important; }
  [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stDecoration"],
  .stDeployButton, footer, #MainMenu, [data-testid="stToolbar"] { display:none !important; }
  [data-testid="stHeader"] { background-color:transparent !important; pointer-events:none; }

  /* 標題小紅條 */
  .section-header{
    font-size:1.15rem; font-weight:800; color:#222;
    margin:10px 0 6px 0; border-left:5px solid #FF4B4B; padding-left:10px;
  }

  /* ✅ 讓 caption / 說明字不要變白看不到 */
  .stCaption, .stMarkdown, label, p, span { color:#111 !important; }

  /* ✅ 全站按鈕：固定可讀 */
  .stButton>button{
    background:#FF4B4B !important;
    color:#fff !important;
    border:1px solid #FF4B4B !important;
    border-radius:10px !important;
    font-weight:800 !important;
    padding:10px 14px !important;
  }
  .stButton>button:hover{ filter:brightness(0.96); }
  .stButton>button:disabled{ opacity:0.55; }

  /* ✅ expander 標題列 */
  [data-testid="stExpander"]>details>summary{
    background:#111827 !important;
    color:#fff !important;
    border-radius:10px !important;
    padding:10px 12px !important;
    font-weight:800 !important;
  }
  [data-testid="stExpander"]>details>summary svg{ color:#fff !important; }

  /* ✅ data_editor 表格區：底色與文字 */
  div[data-testid="stDataFrame"] * { color:#E5E7EB !important; }
  div[data-testid="stDataFrame"]{
    background:#0B1220 !important;
    border-radius:12px !important;
    border:1px solid rgba(255,255,255,0.12) !important;
    overflow:hidden !important;
  }

  /* ✅ 文字輸入框可讀 */
  div[data-baseweb="input"] input{
    background:#fff !important;
    color:#111 !important;
    border:1px solid #D1D5DB !important;
    border-radius:10px !important;
  }

  /* ✅ select */
  div[data-baseweb="select"]>div{
    background:#fff !important;
    color:#111 !important;
    border:1px solid #D1D5DB !important;
    border-radius:10px !important;
  }

  /* ✅ info/warn/error 統一圓角 */
  [data-testid="stAlert"]{ border-radius:12px !important; }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統")
st.markdown("---")

# ==========================
# Session State init
# ==========================
if "box_presets" not in st.session_state:
    st.session_state.box_presets = pd.DataFrame(
        columns=["使用","名稱","長","寬","高","數量","空箱重量","刪除"]
    )

if "product_templates" not in st.session_state:
    st.session_state.product_templates = {}

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(
        [
            {"啟用": True, "商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5, "刪除": False},
            {"啟用": True, "商品名稱": "紙袋",     "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05,"數量": 5, "刪除": False},
        ]
    )

# ==========================
# Layout Mode（左右50/50 or 上下）
# ==========================
layout_mode = st.radio(
    "版面配置",
    ["左右 50% / 50%", "上下（垂直）"],
    horizontal=True,
    index=0
)

def render_box_section():
    st.markdown('<div class="section-header">1. 訂單與外箱設定</div>', unsafe_allow_html=True)

    order_name = st.text_input("訂單名稱", value="訂單_20241208")
    st.session_state["_order_name"] = order_name

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

    st.session_state["_manual_box"] = {
        "使用": manual_use,
        "名稱": manual_name,
        "長": float(manual_L),
        "寬": float(manual_W),
        "高": float(manual_H),
        "空箱重量": float(manual_box_weight),
        "數量": int(manual_qty),
    }

    st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)

    # ✅ 把箱型管理做成寬一點：在 50/50 也能看得到
    with st.expander("📦 箱型管理（新增 / 修改 / 刪除 / 勾選使用）", expanded=True):

        left, right = st.columns([1, 2], gap="medium")

        with left:
            st.caption("新增一筆箱型（新增後可在右側表格直接修改）")
            new_box_name = st.text_input("新箱型名稱", value="", placeholder="例如：A款")
            nb1, nb2, nb3 = st.columns(3)
            new_L = nb1.number_input("新箱_長", value=45.0, step=1.0, min_value=0.0)
            new_W = nb2.number_input("新箱_寬", value=30.0, step=1.0, min_value=0.0)
            new_H = nb3.number_input("新箱_高", value=30.0, step=1.0, min_value=0.0)
            new_box_weight = st.number_input("新箱_空箱重量(kg)", value=0.5, step=0.1, min_value=0.0)
            new_qty = st.number_input("新箱_數量", value=1, step=1, min_value=0)

            add_btn = st.button("➕ 新增箱型", use_container_width=True)
            del_btn = st.button("🗑️ 刪除勾選的箱型", use_container_width=True)

            if add_btn:
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
                st.session_state.box_presets = pd.concat(
                    [st.session_state.box_presets, pd.DataFrame([row])],
                    ignore_index=True
                )

            if del_btn and len(st.session_state.box_presets) > 0:
                dfp = st.session_state.box_presets.copy()
                if "刪除" not in dfp.columns:
                    dfp["刪除"] = False
                st.session_state.box_presets = dfp[dfp["刪除"] != True].reset_index(drop=True)

        with right:
            st.caption("✅ 勾選「使用」= 參與裝箱；「數量」可輸入 0；「刪除」勾選後按左側刪除按鈕")
            box_df = st.data_editor(
                st.session_state.box_presets,
                num_rows="dynamic",
                use_container_width=True,
                height=260,
                column_config={
                    "使用": st.column_config.CheckboxColumn(),
                    "刪除": st.column_config.CheckboxColumn(help="勾選後按左側『刪除勾選』"),
                    "數量": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
                    "長": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
                    "寬": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
                    "高": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
                    "空箱重量": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
                },
            )
            if "刪除" not in box_df.columns:
                box_df["刪除"] = False
            st.session_state.box_presets = box_df

    st.info(
        "外箱操作說明：\n"
        "1) 手動箱：勾選『使用手動箱』並填數量。\n"
        "2) 預存箱：在『箱型管理』新增箱型 → 在表格直接修改尺寸/數量 → 勾選『使用』參與裝箱。\n"
        "3) 刪除箱型：在表格勾選『刪除』後按『刪除勾選的箱型』。"
    )

def render_product_section():
    st.markdown('<div class="section-header">2. 商品清單（直接編輯表格）</div>', unsafe_allow_html=True)

    # 模板列
    row1 = st.columns([2, 2, 3], gap="medium")
    with row1[0]:
        tpl_names = ["(無)"] + sorted(list(st.session_state.product_templates.keys()))
        tpl_sel = st.selectbox("商品初始值模板", tpl_names)
    with row1[1]:
        if st.button("⬇️ 載入模板", use_container_width=True):
            if tpl_sel != "(無)" and tpl_sel in st.session_state.product_templates:
                st.session_state.df = pd.DataFrame(st.session_state.product_templates[tpl_sel])
                if "刪除" not in st.session_state.df.columns:
                    st.session_state.df["刪除"] = False
    with row1[2]:
        save_name = st.text_input("另存為模板名稱", value="", placeholder="例如：常用商品組合A")
        if st.button("💾 儲存目前商品為模板", use_container_width=True):
            nm = save_name.strip()
            if nm:
                st.session_state.product_templates[nm] = st.session_state.df.to_dict(orient="records")

    # 商品表格 + 刪除按鈕
    cbtn1, cbtn2 = st.columns([2, 3])
    with cbtn1:
        del_products = st.button("🗑️ 刪除勾選的商品列", use_container_width=True)
    with cbtn2:
        st.caption("✅ 可直接在表格修改；數量可輸入 0（不計算）；啟用取消勾選也不計算")

    if del_products and len(st.session_state.df) > 0:
        dff = st.session_state.df.copy()
        if "刪除" not in dff.columns:
            dff["刪除"] = False
        st.session_state.df = dff[dff["刪除"] != True].reset_index(drop=True)

    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        height=320,
        column_config={
            "啟用": st.column_config.CheckboxColumn(),
            "刪除": st.column_config.CheckboxColumn(help="勾選後按『刪除勾選的商品列』"),
            "數量": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
            "長": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "寬": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "高": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "重量(kg)": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
        }
    )
    if "刪除" not in edited_df.columns:
        edited_df["刪除"] = False
    st.session_state.df = edited_df

    st.info(
        "商品操作說明：\n"
        "1) 勾選『啟用』且『數量>0』的商品才會納入裝箱。\n"
        "2) 想暫時不算：把數量改 0 或取消勾選啟用。\n"
        "3) 刪除列：勾選『刪除』→ 按『刪除勾選的商品列』。\n"
        "4) 需要固定初始值：用『儲存目前商品為模板』，下次可一鍵載入。"
    )

# ==========================
# 版面渲染
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

run_button = st.button("🚀 開始計算與 3D 模擬", type="primary", use_container_width=True)

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

        one_bin_solution = try_pack_all_in_one_bin(items, candidate_bins)

        if one_bin_solution is not None:
            bins_result = one_bin_solution["bins"]
            bin_defs_used = one_bin_solution["bin_defs"]
            remaining = []
        else:
            bins_result, bin_defs_used, remaining = greedy_multi_bin_pack_id(items, candidate_bins)

        # 統計
        packed_counts = {}
        total_vol = 0.0
        total_net_weight = 0.0

        for placed in bins_result:
            for it in placed:
                packed_counts[it["name"]] = packed_counts.get(it["name"], 0) + 1
                total_vol += it["dx"] * it["dy"] * it["dz"]
                total_net_weight += it["weight"]

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
                missing_items_html += f"<li style='color:#721c24;background:#f8d7da;padding:8px;margin:6px 0;border-radius:8px;font-weight:800;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status_html = (
            "<div style='color:#155724;background:#d4edda;padding:14px;border-radius:12px;text-align:center;border:1px solid #c3e6cb;font-weight:900;font-size:1.1rem;'>✅ 完美！所有商品皆已裝入。</div>"
            if all_fitted
            else f"<div style='color:#721c24;background:#f8d7da;padding:14px;border-radius:12px;border:1px solid #f5c6cb;font-weight:900;'>❌ 注意：有部分商品裝不下！</div><ul style='padding-left:18px;margin-top:10px;'>{missing_items_html}</ul>"
        )

        tw_time = _now_tw()
        now_str = tw_time.strftime("%Y-%m-%d %H:%M")
        file_time_str = tw_time.strftime("%Y%m%d_%H%M")

        box_summary = {}
        for bdef in bin_defs_used:
            key = f'{bdef["名稱"]} ({bdef["長"]}×{bdef["寬"]}×{bdef["高"]})'
            box_summary[key] = box_summary.get(key, 0) + 1
        box_summary_html = "<br>".join([f"{k} × {v} 箱" for k, v in box_summary.items()]) if box_summary else "-"

        st.markdown('<div class="section-header">3. 裝箱結果與模擬</div>', unsafe_allow_html=True)

        st.markdown(f"""
        <div style="padding:18px;border:1px solid #e5e7eb;border-radius:14px;background:#fff;box-shadow:0 6px 18px rgba(0,0,0,0.06);">
          <div style="font-weight:900;font-size:1.25rem;border-bottom:3px solid #111827;padding-bottom:10px;margin-bottom:12px;">📋 訂單裝箱報告</div>
          <div style="display:grid;grid-template-columns:170px 1fr;row-gap:10px;column-gap:10px;font-size:1.05rem;">
            <div style="font-weight:800;color:#374151;">📝 訂單名稱</div><div style="font-weight:900;color:#1d4ed8;">{order_name}</div>
            <div style="font-weight:800;color:#374151;">🕒 計算時間</div><div>{now_str} (台灣時間)</div>
            <div style="font-weight:800;color:#374151;">📦 使用外箱</div><div>{box_summary_html}</div>
            <div style="font-weight:800;color:#374151;">⚖️ 內容淨重</div><div>{total_net_weight:.2f} kg</div>
            <div style="font-weight:800;color:#b91c1c;">🚛 本次總重</div><div style="font-weight:900;color:#b91c1c;font-size:1.15rem;">{gross_weight:.2f} kg</div>
            <div style="font-weight:800;color:#374151;">📊 空間利用率</div><div>{utilization:.2f}%</div>
          </div>
          <div style="margin-top:14px;">{status_html}</div>
        </div>
        """, unsafe_allow_html=True)

        # 3D Plot（多箱平移）
        fig = go.Figure()

        axis_config = dict(
            backgroundcolor="white", showbackground=True,
            zerolinecolor="#000000", gridcolor="#999999",
            linecolor="#000000", showgrid=True, showline=True,
            tickfont=dict(color="black", size=12, family="Arial Black"),
            title=dict(font=dict(color="black", size=14, family="Arial Black"))
        )

        fig.update_layout(
            template="plotly_white",
            font=dict(color="black"),
            autosize=True,
            scene=dict(
                xaxis={**axis_config, 'title': '長 (L)'},
                yaxis={**axis_config, 'title': '寬 (W)'},
                zaxis={**axis_config, 'title': '高 (H)'},
                aspectmode='data',
                camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))
            ),
            margin=dict(t=30, b=0, l=0, r=0),
            height=620,
            legend=dict(
                x=0, y=1, xanchor="left", yanchor="top",
                font=dict(color="black", size=13),
                bgcolor="rgba(255,255,255,0.86)",
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

        # legend 去重
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # 下載報告
        full_html_content = f"""
        <html><head><meta charset="utf-8"><title>裝箱報告 - {order_name}</title></head>
        <body style="font-family:Arial;background:#f3f4f6;padding:24px;">
          <div style="max-width:1100px;margin:0 auto;background:#fff;padding:24px;border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.08);">
            <h2 style="margin-top:0;">📋 訂單裝箱報告</h2>
            <p><b>訂單名稱：</b>{order_name}</p>
            <p><b>計算時間：</b>{now_str} (台灣時間)</p>
            <p><b>使用外箱：</b><br>{box_summary_html}</p>
            <p><b>內容淨重：</b>{total_net_weight:.2f} kg</p>
            <p><b>本次總重：</b>{gross_weight:.2f} kg</p>
            <p><b>空間利用率：</b>{utilization:.2f}%</p>
            <hr>
            {fig.to_html(include_plotlyjs='cdn', full_html=False)}
          </div>
        </body></html>
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
