import os
import json
from datetime import datetime
from itertools import combinations
from copy import deepcopy

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from py3dbp import Packer, Bin, Item


# =========================
# 基本設定
# =========================
st.set_page_config(page_title="3D裝箱系統", layout="wide", initial_sidebar_state="collapsed")

DATA_DIR = "data"
BOXES_FILE = os.path.join(DATA_DIR, "boxes.json")                 # 儲存箱型清單（永久）
PRODUCTS_FILE = os.path.join(DATA_DIR, "products.json")           # 儲存商品清單（永久）
PRODUCT_TPL_FILE = os.path.join(DATA_DIR, "product_templates.json")  # 商品模板（永久）


# =========================
# 工具：資料讀寫
# =========================
def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def safe_load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return deepcopy(default)

def safe_save_json(path, data):
    ensure_data_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def toast_ok(msg):
    try:
        st.toast(msg, icon="✅")
    except Exception:
        st.success(msg)

def toast_warn(msg):
    try:
        st.toast(msg, icon="⚠️")
    except Exception:
        st.warning(msg)


# =========================
# CSS：白底、按鈕配色分級、移除怪條、避免黑底
# =========================
st.markdown(
    """
<style>
/* 全域白底黑字 */
.stApp { background: #ffffff !important; color: #111111 !important; }
h1,h2,h3,h4,h5,h6,p,span,label,small,div { color: #111111; }

/* 移除頁面裝飾 / menu */
[data-testid="stDecoration"], footer, #MainMenu { display:none !important; }

/* 標題樣式（左紅線、不要黑底） */
.section-title{
  font-weight: 800;
  font-size: 1.1rem;
  padding: 0.2rem 0 0.2rem 0.7rem;
  border-left: 5px solid #ff4b4b;
  margin: 0.6rem 0 0.4rem 0;
}

/* 避免出現你說的「奇怪圓角長條」：不使用 marker div 方式 */
div._no_marker { display:none !important; height:0 !important; margin:0 !important; padding:0 !important; }

/* Button 基礎 */
.stButton>button{
  border-radius: 10px !important;
  font-weight: 800 !important;
  border: 1px solid rgba(0,0,0,0.08) !important;
  padding: 0.55rem 0.9rem !important;
}

/* 按鈕配色分級 */
.btn-add .stButton>button{ background:#d1fae5 !important; color:#065f46 !important; }   /* 淡綠 */
.btn-del .stButton>button{ background:#fee2e2 !important; color:#7f1d1d !important; }   /* 淡紅 */
.btn-save .stButton>button{ background:#dbeafe !important; color:#1e3a8a !important; }  /* 淡藍 */
.btn-load .stButton>button{ background:#f3f4f6 !important; color:#374151 !important; }  /* 淡灰 */
.btn-run  .stButton>button{ background:#dcfce7 !important; color:#166534 !important; font-size: 1.05rem !important; } /* 計算淡綠醒目 */

/* info 區塊 */
.helpbox{
  background:#eff6ff;
  border:1px solid #bfdbfe;
  color:#0f172a;
  padding:0.8rem 0.9rem;
  border-radius:12px;
  margin-top:0.6rem;
  line-height:1.55;
}

/* Plotly 白底 */
[data-testid="stPlotlyChart"]{ background:#ffffff !important; }
.js-plotly-plot, .plotly, .main-svg{ background:#ffffff !important; }
</style>
""",
    unsafe_allow_html=True,
)


# =========================
# 初始化 SessionState（首次讀檔）
# =========================
if "order_name" not in st.session_state:
    st.session_state.order_name = "訂單_20241208"

if "boxes" not in st.session_state:
    # boxes: list[ {use, name, l, w, h, empty_weight, qty} ]
    st.session_state.boxes = safe_load_json(BOXES_FILE, [])

if "products" not in st.session_state:
    # products: list[ {use, name, l, w, h, weight, qty} ]
    st.session_state.products = safe_load_json(PRODUCTS_FILE, [])

if "product_templates" not in st.session_state:
    # templates: dict[str] -> list[product_rows]
    st.session_state.product_templates = safe_load_json(PRODUCT_TPL_FILE, {})

if "layout_mode" not in st.session_state:
    st.session_state.layout_mode = "左右 50% / 50%"

if "last_result" not in st.session_state:
    st.session_state.last_result = None  # 存 pack 結果


# =========================
# 版面配置
# =========================
st.title("📦 3D裝箱系統")

st.markdown('<div class="section-title">版面配置</div>', unsafe_allow_html=True)
st.session_state.layout_mode = st.radio(
    "",
    ["左右 50% / 50%", "上下（垂直）"],
    index=0 if st.session_state.layout_mode == "左右 50% / 50%" else 1,
    horizontal=True,
)

def two_panes():
    if st.session_state.layout_mode == "左右 50% / 50%":
        return st.columns([1, 1], gap="large")
    else:
        c1 = st.container()
        c2 = st.container()
        return c1, c2

left, right = two_panes()


# =========================
# Section 1：訂單與外箱設定
# =========================
with left:
    st.markdown('<div class="section-title">1. 訂單與外箱設定</div>', unsafe_allow_html=True)

    st.session_state.order_name = st.text_input("訂單名稱", value=st.session_state.order_name)

    # ---- 手動 Key-in 外箱（可選擇是否參與裝箱）----
    st.caption("外箱尺寸（cm）- 手動 Key in（可選擇是否參與裝箱）")
    use_manual_box = st.checkbox("使用手動箱", value=True)
    c1, c2, c3 = st.columns(3)
    manual_l = c1.number_input("長", min_value=1.0, value=35.0, step=1.0)
    manual_w = c2.number_input("寬", min_value=1.0, value=25.0, step=1.0)
    manual_h = c3.number_input("高", min_value=1.0, value=20.0, step=1.0)
    manual_empty_weight = st.number_input("空箱重量 (kg)", min_value=0.0, value=0.50, step=0.05)
    c4, c5 = st.columns([1, 2])
    manual_qty = c4.number_input("手動箱數量", min_value=0, value=1, step=1)
    manual_name = c5.text_input("手動箱命名", value="手動箱")

    # ---- 箱型管理（永久保存）----
    st.markdown('<div class="section-title">箱型管理（新增 / 修改 / 刪除 / 勾選使用）</div>', unsafe_allow_html=True)

    # 新增箱型表單
    with st.form("add_box_form", clear_on_submit=True):
        n = st.text_input("新增箱型名稱")
        b1, b2, b3 = st.columns(3)
        nl = b1.number_input("新增_長", min_value=1.0, value=45.0, step=1.0)
        nw = b2.number_input("新增_寬", min_value=1.0, value=30.0, step=1.0)
        nh = b3.number_input("新增_高", min_value=1.0, value=30.0, step=1.0)
        new_empty_w = st.number_input("新增_空箱重量(kg)", min_value=0.0, value=0.50, step=0.05)
        new_qty = st.number_input("新增_數量", min_value=0, value=1, step=1)

        st.markdown('<div class="btn-add">', unsafe_allow_html=True)
        add_box_btn = st.form_submit_button("➕ 新增箱型")
        st.markdown("</div>", unsafe_allow_html=True)

        if add_box_btn:
            if not n.strip():
                toast_warn("請輸入箱型名稱")
            else:
                st.session_state.boxes.append({
                    "use": True,
                    "name": n.strip(),
                    "l": float(nl),
                    "w": float(nw),
                    "h": float(nh),
                    "empty_weight": float(new_empty_w),
                    "qty": int(new_qty),
                    "delete": False,
                })
                safe_save_json(BOXES_FILE, st.session_state.boxes)
                toast_ok("已新增箱型並永久保存")

    # 箱型列表（可直接修改）
    if len(st.session_state.boxes) == 0:
        st.info("尚未建立箱型。你可以使用上方『新增箱型』建立多個箱型，並設定數量與是否參與裝箱。")
    else:
        df_boxes = pd.DataFrame(st.session_state.boxes)
        # 保底欄位
        for col, default in [("use", True), ("delete", False), ("qty", 1), ("empty_weight", 0.5)]:
            if col not in df_boxes.columns:
                df_boxes[col] = default

        st.caption("勾選「use」= 參與裝箱；「qty」可輸入 0；勾選「delete」後按刪除")
        edited_boxes = st.data_editor(
            df_boxes,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "use": st.column_config.CheckboxColumn("使用", help="勾選後此箱型才參與裝箱"),
                "name": st.column_config.TextColumn("名稱"),
                "l": st.column_config.NumberColumn("長", min_value=1.0),
                "w": st.column_config.NumberColumn("寬", min_value=1.0),
                "h": st.column_config.NumberColumn("高", min_value=1.0),
                "qty": st.column_config.NumberColumn("數量", min_value=0, step=1),
                "empty_weight": st.column_config.NumberColumn("空箱重(kg)", min_value=0.0, step=0.05),
                "delete": st.column_config.CheckboxColumn("刪除", help="勾選後可批次刪除"),
            },
            key="boxes_editor",
        )

        # 操作按鈕：儲存/刪除
        cbtn1, cbtn2 = st.columns([1, 1])
        with cbtn1:
            st.markdown('<div class="btn-save">', unsafe_allow_html=True)
            save_boxes_btn = st.button("💾 儲存箱型變更", key="save_boxes_btn")
            st.markdown("</div>", unsafe_allow_html=True)
        with cbtn2:
            st.markdown('<div class="btn-del">', unsafe_allow_html=True)
            del_boxes_btn = st.button("🗑️ 刪除勾選箱型", key="del_boxes_btn")
            st.markdown("</div>", unsafe_allow_html=True)

        if save_boxes_btn:
            with st.spinner("儲存中..."):
                st.session_state.boxes = edited_boxes.to_dict("records")
                # 清掉不存在欄位
                for r in st.session_state.boxes:
                    r.setdefault("use", True)
                    r.setdefault("delete", False)
                    r["qty"] = int(r.get("qty", 0) or 0)
                    r["l"] = float(r.get("l", 1))
                    r["w"] = float(r.get("w", 1))
                    r["h"] = float(r.get("h", 1))
                    r["empty_weight"] = float(r.get("empty_weight", 0.0) or 0.0)
                safe_save_json(BOXES_FILE, st.session_state.boxes)
            toast_ok("箱型變更已保存")

        if del_boxes_btn:
            with st.spinner("刪除中..."):
                rows = edited_boxes.to_dict("records")
                rows = [r for r in rows if not r.get("delete")]
                st.session_state.boxes = rows
                safe_save_json(BOXES_FILE, st.session_state.boxes)
            toast_ok("已刪除勾選箱型")

    st.markdown(
        """
        <div class="helpbox">
        <b>外箱操作說明：</b><br>
        1) <b>手動箱</b>：勾選「使用手動箱」後，手動箱會加入裝箱。數量可輸入 0。<br>
        2) <b>箱型管理</b>：新增後會永久保存（data/boxes.json）。<br>
        3) <b>使用</b>：勾選後才參與裝箱；<b>數量</b>可為 0（代表不提供此箱型）。<br>
        4) <b>修改</b>：直接在表格改數值，按「儲存箱型變更」。<br>
        5) <b>刪除</b>：勾選「刪除」欄位後按「刪除勾選箱型」。<br>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =========================
# Section 2：商品清單
# =========================
with right:
    st.markdown('<div class="section-title">2. 商品清單（直接編輯表格）</div>', unsafe_allow_html=True)

    # ---- 商品模板：載入 / 儲存 / 刪除（永久）----
    tpl_names = ["(無)"] + sorted(list(st.session_state.product_templates.keys()))

    ctpl1, ctpl2, ctpl3 = st.columns([2, 1, 1])
    selected_tpl = ctpl1.selectbox("商品初始值模板", tpl_names, index=0)
    new_tpl_name = ctpl2.text_input("另存模板名稱", value="")
    del_tpl_name = ctpl3.selectbox("要刪除的模板", ["(無)"] + sorted(list(st.session_state.product_templates.keys())), index=0)

    cb1, cb2, cb3 = st.columns([1, 1, 1])
    with cb1:
        st.markdown('<div class="btn-load">', unsafe_allow_html=True)
        load_tpl_btn = st.button("⬇️ 載入", key="load_tpl_btn")
        st.markdown("</div>", unsafe_allow_html=True)

    with cb2:
        st.markdown('<div class="btn-save">', unsafe_allow_html=True)
        save_tpl_btn = st.button("💾 儲存", key="save_tpl_btn")
        st.markdown("</div>", unsafe_allow_html=True)

    with cb3:
        st.markdown('<div class="btn-del">', unsafe_allow_html=True)
        del_tpl_btn = st.button("🗑️ 刪除模板", key="del_tpl_btn")
        st.markdown("</div>", unsafe_allow_html=True)

    if load_tpl_btn:
        with st.spinner("讀入中..."):
            if selected_tpl == "(無)":
                toast_warn("請先選擇要載入的模板")
            else:
                st.session_state.products = deepcopy(st.session_state.product_templates[selected_tpl])
                safe_save_json(PRODUCTS_FILE, st.session_state.products)  # 也同步成目前清單
                toast_ok(f"已載入模板：{selected_tpl}")

    if save_tpl_btn:
        with st.spinner("儲存中..."):
            name = new_tpl_name.strip()
            if not name:
                toast_warn("請輸入要儲存的模板名稱")
            else:
                st.session_state.product_templates[name] = deepcopy(st.session_state.products)
                safe_save_json(PRODUCT_TPL_FILE, st.session_state.product_templates)
                toast_ok(f"已儲存模板：{name}")

    if del_tpl_btn:
        with st.spinner("刪除中..."):
            if del_tpl_name == "(無)":
                toast_warn("請選擇要刪除的模板")
            else:
                st.session_state.product_templates.pop(del_tpl_name, None)
                safe_save_json(PRODUCT_TPL_FILE, st.session_state.product_templates)
                toast_ok(f"已刪除模板：{del_tpl_name}")

    # ---- 商品新增 ----
    st.markdown('<div class="section-title">商品管理（新增 / 修改 / 刪除 / 勾選是否計算）</div>', unsafe_allow_html=True)

    with st.form("add_product_form", clear_on_submit=True):
        pname = st.text_input("新增商品名稱")
        p1, p2, p3 = st.columns(3)
        pl = p1.number_input("長", min_value=0.1, value=21.0, step=0.1)
        pw = p2.number_input("寬", min_value=0.1, value=14.0, step=0.1)
        ph = p3.number_input("高", min_value=0.1, value=8.5, step=0.1)
        pweight = st.number_input("重量(kg)", min_value=0.0, value=0.50, step=0.01)
        pqty = st.number_input("數量（可為 0）", min_value=0, value=1, step=1)

        st.markdown('<div class="btn-add">', unsafe_allow_html=True)
        add_product_btn = st.form_submit_button("➕ 新增商品")
        st.markdown("</div>", unsafe_allow_html=True)

        if add_product_btn:
            if not pname.strip():
                toast_warn("請輸入商品名稱")
            else:
                st.session_state.products.append({
                    "use": True,
                    "name": pname.strip(),
                    "l": float(pl),
                    "w": float(pw),
                    "h": float(ph),
                    "weight": float(pweight),
                    "qty": int(pqty),
                    "delete": False,
                })
                safe_save_json(PRODUCTS_FILE, st.session_state.products)
                toast_ok("已新增商品並永久保存")

    # ---- 商品列表（可直接改 + 可刪除列）----
    if len(st.session_state.products) == 0:
        st.info("尚未建立商品。你可以用上方『新增商品』加入，也可儲存為模板。")
    else:
        df_prod = pd.DataFrame(st.session_state.products)
        for col, default in [("use", True), ("delete", False), ("qty", 0), ("weight", 0.0)]:
            if col not in df_prod.columns:
                df_prod[col] = default

        st.caption("提示：數量可為 0（代表不計算）；或取消勾選「使用」也不計算。")
        edited_prod = st.data_editor(
            df_prod,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "use": st.column_config.CheckboxColumn("啟用", help="勾選且數量>0 才會參與裝箱"),
                "name": st.column_config.TextColumn("商品名稱"),
                "l": st.column_config.NumberColumn("長", min_value=0.1),
                "w": st.column_config.NumberColumn("寬", min_value=0.1),
                "h": st.column_config.NumberColumn("高", min_value=0.1),
                "weight": st.column_config.NumberColumn("重量(kg)", min_value=0.0, step=0.01),
                "qty": st.column_config.NumberColumn("數量", min_value=0, step=1),
                "delete": st.column_config.CheckboxColumn("刪除", help="勾選後可批次刪除"),
            },
            key="prod_editor",
        )

        cbtn1, cbtn2 = st.columns([1, 1])
        with cbtn1:
            st.markdown('<div class="btn-save">', unsafe_allow_html=True)
            save_prod_btn = st.button("💾 儲存商品變更", key="save_prod_btn")
            st.markdown("</div>", unsafe_allow_html=True)
        with cbtn2:
            st.markdown('<div class="btn-del">', unsafe_allow_html=True)
            del_prod_btn = st.button("🗑️ 刪除勾選商品", key="del_prod_btn")
            st.markdown("</div>", unsafe_allow_html=True)

        if save_prod_btn:
            with st.spinner("儲存中..."):
                st.session_state.products = edited_prod.to_dict("records")
                for r in st.session_state.products:
                    r.setdefault("use", True)
                    r.setdefault("delete", False)
                    r["qty"] = int(r.get("qty", 0) or 0)
                    r["l"] = float(r.get("l", 0.1))
                    r["w"] = float(r.get("w", 0.1))
                    r["h"] = float(r.get("h", 0.1))
                    r["weight"] = float(r.get("weight", 0.0) or 0.0)
                safe_save_json(PRODUCTS_FILE, st.session_state.products)
            toast_ok("商品變更已保存")

        if del_prod_btn:
            with st.spinner("刪除中..."):
                rows = edited_prod.to_dict("records")
                rows = [r for r in rows if not r.get("delete")]
                st.session_state.products = rows
                safe_save_json(PRODUCTS_FILE, st.session_state.products)
            toast_ok("已刪除勾選商品")

    st.markdown(
        """
        <div class="helpbox">
        <b>商品操作說明：</b><br>
        1) <b>啟用</b>：勾選且數量 > 0 才會參與裝箱。<br>
        2) <b>數量可為 0</b>：快速排除不想計算的品項。<br>
        3) <b>修改</b>：直接在表格改數值，按「儲存商品變更」。<br>
        4) <b>刪除</b>：勾選「刪除」欄位後按「刪除勾選商品」。<br>
        5) <b>模板</b>：可把目前商品清單永久存成模板、日後一鍵載入。<br>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =========================
# 裝箱演算法：挑最少箱數 + 再比總箱體積
# =========================
def expand_bins(manual_on, manual_name, L, W, H, empty_w, manual_qty, saved_boxes_rows):
    bins = []
    # 手動箱
    if manual_on and manual_qty > 0:
        for i in range(int(manual_qty)):
            bins.append({
                "id": f"{manual_name}_{i+1}",
                "name": manual_name,
                "l": float(L),
                "w": float(W),
                "h": float(H),
                "empty_weight": float(empty_w),
                "source": "manual",
            })
    # 儲存箱型
    for r in saved_boxes_rows:
        if not r.get("use"):
            continue
        qty = int(r.get("qty", 0) or 0)
        if qty <= 0:
            continue
        for i in range(qty):
            bins.append({
                "id": f"{r['name']}_{i+1}",
                "name": r["name"],
                "l": float(r["l"]),
                "w": float(r["w"]),
                "h": float(r["h"]),
                "empty_weight": float(r.get("empty_weight", 0.0) or 0.0),
                "source": "saved",
            })
    return bins

def expand_items(products_rows):
    items = []
    for r in products_rows:
        if not r.get("use"):
            continue
        qty = int(r.get("qty", 0) or 0)
        if qty <= 0:
            continue
        for _ in range(qty):
            items.append({
                "name": r["name"],
                "l": float(r["l"]),
                "w": float(r["w"]),
                "h": float(r["h"]),
                "weight": float(r.get("weight", 0.0) or 0.0),
            })
    return items

def try_pack_with_bins(bins_subset, items):
    packer = Packer()
    for b in bins_subset:
        packer.add_bin(Bin(b["id"], b["l"], b["w"], b["h"], b["empty_weight"]))
    for it in items:
        packer.add_item(Item(it["name"], it["l"], it["w"], it["h"], it["weight"]))
    packer.pack(bigger_first=True)
    # 檢查是否全部裝入
    fitted = sum(len(b.items) for b in packer.bins)
    return packer, fitted

def choose_best_bins(all_bins, items):
    """
    目標：
    1) 使用箱數最少
    2) 若箱數相同 → 總箱體積更小（更省空間、更不浪費）
    """
    if len(items) == 0:
        return [], None, 0

    if len(all_bins) == 0:
        return [], None, 0

    # 先依箱體積由小到大排序（因為要找最少箱數，且同箱數希望體積小）
    bins_sorted = sorted(all_bins, key=lambda b: (b["l"] * b["w"] * b["h"], b["l"], b["w"], b["h"]))

    best = None  # (k, total_volume, packer, bins_used)
    max_bins = len(bins_sorted)

    # 逐步嘗試：1 箱、2 箱、3 箱...
    for k in range(1, max_bins + 1):
        # 組合數可能爆炸 → 做一個保護（尤其箱很多時）
        # 這裡採「偏小體積優先」：只取前 N 個箱候選做組合（通常已足夠）
        CAND_LIMIT = 18  # 可視需求調整：越大越慢、越準
        cand = bins_sorted[:min(CAND_LIMIT, len(bins_sorted))]

        # k 太大時組合數爆掉，直接退回貪婪（用最小體積前 k 個）
        if len(cand) >= 18 and k >= 6:
            subset = cand[:k]
            packer, fitted = try_pack_with_bins(subset, items)
            if fitted == len(items):
                total_vol = sum(b["l"] * b["w"] * b["h"] for b in subset)
                return subset, packer, fitted
            continue

        # 正常組合嘗試
        for subset in combinations(cand, k):
            subset = list(subset)
            packer, fitted = try_pack_with_bins(subset, items)
            if fitted == len(items):
                total_vol = sum(b["l"] * b["w"] * b["h"] for b in subset)
                cand_best = (k, total_vol, packer, subset)
                if best is None or cand_best[:2] < best[:2]:
                    best = cand_best

        if best is not None:
            return best[3], best[2], len(items)

    # 沒找到完整可裝的方案
    # 回傳「用所有箱去裝」的結果（至少知道裝了多少）
    packer, fitted = try_pack_with_bins(bins_sorted, items)
    return bins_sorted, packer, fitted


# =========================
# 3D 畫 cuboid（每個箱分開擺）
# =========================
def cuboid_mesh(x0, y0, z0, dx, dy, dz, color, opacity, name):
    # 8 vertices
    x = [x0, x0+dx, x0+dx, x0,   x0, x0+dx, x0+dx, x0]
    y = [y0, y0,   y0+dy, y0+dy, y0, y0,   y0+dy, y0+dy]
    z = [z0, z0,   z0,    z0,    z0+dz, z0+dz, z0+dz, z0+dz]

    # 12 triangles (two per face)
    I = [0,0,0,  1,1,2,  4,4,5,  7,7,6]
    J = [1,2,3,  2,5,3,  5,6,6,  6,3,2]
    K = [2,3,0,  5,6,7,  6,7,4,  3,0,1]

    return go.Mesh3d(
        x=x, y=y, z=z,
        i=I, j=J, k=K,
        color=color,
        opacity=opacity,
        name=name,
        flatshading=True,
        showscale=False
    )

def build_3d_figure(packer, used_bins_only=True):
    fig = go.Figure()
    x_offset = 0.0
    gap = 6.0

    for b in packer.bins:
        if used_bins_only and len(b.items) == 0:
            continue

        # 外箱外框（用透明盒子表示空間）
        fig.add_trace(cuboid_mesh(
            x_offset, 0, 0,
            b.width, b.depth, b.height,
            color="rgba(0,0,0,0.08)",
            opacity=0.10,
            name=f"外箱({b.name})"
        ))

        # 箱內商品
        # py3dbp 的 position = (x,y,z) 對應 width/depth/height
        for it in b.items:
            # it.position -> (x,y,z)
            px, py, pz = it.position
            dx, dy, dz = it.get_dimension()
            fig.add_trace(cuboid_mesh(
                x_offset + px, py, pz,
                dx, dy, dz,
                color="rgba(34,197,94,0.85)",  # 綠
                opacity=0.85,
                name=it.name
            ))

        x_offset += b.width + gap

    fig.update_layout(
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=10, r=10, t=30, b=10),
        scene=dict(
            bgcolor="white",
            xaxis=dict(backgroundcolor="white", gridcolor="rgba(0,0,0,0.1)", zerolinecolor="rgba(0,0,0,0.2)"),
            yaxis=dict(backgroundcolor="white", gridcolor="rgba(0,0,0,0.1)", zerolinecolor="rgba(0,0,0,0.2)"),
            zaxis=dict(backgroundcolor="white", gridcolor="rgba(0,0,0,0.1)", zerolinecolor="rgba(0,0,0,0.2)"),
        ),
        legend=dict(bgcolor="rgba(255,255,255,0.95)")
    )
    return fig


# =========================
# Section 3：裝箱結果與模擬
# =========================
st.markdown('<div class="section-title">3. 裝箱結果與模擬</div>', unsafe_allow_html=True)

st.markdown('<div class="btn-run">', unsafe_allow_html=True)
run_btn = st.button("🚀 開始計算與 3D 模擬", key="run_pack_btn")
st.markdown("</div>", unsafe_allow_html=True)

if run_btn:
    with st.spinner("計算中..."):
        # 取出箱與商品
        all_bins = expand_bins(
            manual_on=use_manual_box,
            manual_name=manual_name.strip() or "手動箱",
            L=manual_l, W=manual_w, H=manual_h,
            empty_w=manual_empty_weight,
            manual_qty=int(manual_qty),
            saved_boxes_rows=st.session_state.boxes
        )
        items = expand_items(st.session_state.products)

        if len(items) == 0:
            st.session_state.last_result = {"error": "目前沒有任何商品參與裝箱（請確認啟用 + 數量 > 0）"}
        elif len(all_bins) == 0:
            st.session_state.last_result = {"error": "目前沒有任何外箱參與裝箱（請確認手動箱或箱型管理有啟用且數量 > 0）"}
        else:
            chosen_bins, packer, fitted = choose_best_bins(all_bins, items)
            st.session_state.last_result = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_items": len(items),
                "fitted": fitted,
                "chosen_bins": chosen_bins,
                "packer": packer,
            }

# 顯示結果
res = st.session_state.last_result
if res:
    if "error" in res:
        st.error(res["error"])
    else:
        packer = res["packer"]
        total_items = res["total_items"]
        fitted = res["fitted"]

        # 統計：使用到的箱（有放商品）
        used_bins = [b for b in packer.bins if len(b.items) > 0]
        unused_bins = [b for b in packer.bins if len(b.items) == 0]

        content_weight = 0.0
        for b in used_bins:
            for it in b.items:
                content_weight += float(it.weight)

        box_weight = 0.0
        for b in used_bins:
            # b.max_weight 在 py3dbp 這裡用作箱重
            box_weight += float(b.max_weight)

        total_weight = content_weight + box_weight

        # 空間利用率（使用到的箱合計）
        used_box_volume = sum(b.width * b.depth * b.height for b in used_bins) if used_bins else 0.0
        items_volume = 0.0
        for b in used_bins:
            for it in b.items:
                dx, dy, dz = it.get_dimension()
                items_volume += dx * dy * dz
        utilization = (items_volume / used_box_volume * 100.0) if used_box_volume > 0 else 0.0

        st.write("")
        st.markdown(f"**🧾 訂單名稱：** {st.session_state.order_name}")
        st.markdown(f"**🕒 計算時間：** {res['time']}（台灣時間）")
        st.markdown(f"**📦 使用箱數：** {len(used_bins)}（未使用箱：{len(unused_bins)}）")
        st.markdown(f"**⚖️ 內容淨重：** {content_weight:.2f} kg")
        st.markdown(f"**📦 空箱重量：** {box_weight:.2f} kg")
        st.markdown(f"**🚚 本箱總重：** {total_weight:.2f} kg")
        st.markdown(f"**📊 空間利用率：** {utilization:.2f}%")

        if fitted < total_items:
            st.error(f"❌ 注意：有部分商品裝不下！（遺漏 {total_items - fitted} 件）")
        else:
            st.success("✅ 完美！所有商品皆已裝入。")

        # 3D 顯示（白底）
        fig = build_3d_figure(packer, used_bins_only=True)
        st.plotly_chart(fig, use_container_width=True)

        # 下載報告（白底 HTML）
        report_html = f"""
<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>裝箱報告</title>
<style>
  body{{font-family: Arial, \"Noto Sans TC\", sans-serif; background:#fff; color:#111; padding:24px;}}
  .card{{border:1px solid #e5e7eb; border-radius:12px; padding:16px; margin:12px 0;}}
  h2{{margin:0 0 10px 0;}}
  table{{border-collapse:collapse; width:100%;}}
  th,td{{border:1px solid #e5e7eb; padding:8px; font-size:14px;}}
  th{{background:#f9fafb;}}
  .ok{{background:#dcfce7; border:1px solid #86efac; padding:10px; border-radius:10px;}}
  .bad{{background:#fee2e2; border:1px solid #fecaca; padding:10px; border-radius:10px;}}
</style>
</head>
<body>
  <h2>訂單裝箱報告</h2>
  <div class="card">
    <div><b>訂單名稱：</b> {st.session_state.order_name}</div>
    <div><b>計算時間：</b> {res['time']}（台灣時間）</div>
    <div><b>使用箱數：</b> {len(used_bins)}</div>
    <div><b>內容淨重：</b> {content_weight:.2f} kg</div>
    <div><b>空箱重量：</b> {box_weight:.2f} kg</div>
    <div><b>本箱總重：</b> {total_weight:.2f} kg</div>
    <div><b>空間利用率：</b> {utilization:.2f}%</div>
  </div>

  {"<div class='ok'>✅ 所有商品皆已裝入。</div>" if fitted==total_items else f"<div class='bad'>❌ 有商品裝不下（遺漏 {total_items-fitted} 件）。</div>"}

  <div class="card">
    <h3>箱內明細</h3>
    <table>
      <tr><th>箱名</th><th>箱尺寸</th><th>箱內商品</th></tr>
"""
        for b in used_bins:
            items_list = ", ".join([it.name for it in b.items]) if b.items else "-"
            report_html += f"<tr><td>{b.name}</td><td>{b.width}×{b.depth}×{b.height}</td><td>{items_list}</td></tr>"

        report_html += """
    </table>
  </div>
</body>
</html>
"""
        st.download_button(
            "⬇️ 下載完整裝箱報告（.html）",
            data=report_html.encode("utf-8"),
            file_name=f"{st.session_state.order_name}_裝箱報告.html",
            mime="text/html",
        )
