import json
import datetime as dt
from urllib import request as urlreq
from urllib.error import URLError

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="3D裝箱系統", page_icon="📦", layout="wide")

# -----------------------
# Secrets (Streamlit Community Cloud)
# -----------------------
GS_WEBAPP_URL = st.secrets.get("GS_WEBAPP_URL", "").strip()
GS_TOKEN = st.secrets.get("GS_TOKEN", "").strip()

BOX_SHEET = "box_templates"
PROD_SHEET = "product_templates"

# -----------------------
# CSS: buttons + clean UI
# -----------------------
CSS = """
<style>
.block-container{max-width:1600px;padding-top:1.2rem;padding-bottom:2rem;}
hr{border:none;border-top:1px solid #E5E7EB;margin:14px 0;}
.section-title{font-weight:900;font-size:1.05rem;margin:2px 0 10px 0;padding-left:10px;border-left:4px solid #EF4444;}
.panel{border:1px solid #E5E7EB;background:#FFFFFF;border-radius:16px;padding:14px 14px 10px 14px;box-shadow:0 6px 18px rgba(0,0,0,.04);}
.smallnote{color:#6B7280;font-size:0.88rem;margin-top:-4px;}
.badge{display:inline-block;padding:6px 10px;border-radius:999px;font-weight:900;font-size:0.9rem;border:1px solid #E5E7EB;background:#F9FAFB;}

button[aria-label="🚀 開始計算與 3D 模擬"]{background:#2563EB !important;color:white !important;border:1px solid #2563EB !important;}
button[aria-label="💾 儲存模板"]{background:#DBEAFE !important;color:#1D4ED8 !important;border:1px solid #BFDBFE !important;}
button[aria-label="⬇️ 載入模板"]{background:#F5F5F5 !important;color:#263238 !important;border:1px solid #E0E0E0 !important;}
button[aria-label="🗑 刪除模板"]{background:#FEE2E2 !important;color:#B91C1C !important;border:1px solid #FECACA !important;}
button[aria-label="🗑 刪除勾選"]{background:#FEE2E2 !important;color:#B91C1C !important;border:1px solid #FECACA !important;}
button[aria-label="🧹 清除套用"]{background:#F5F5F5 !important;color:#263238 !important;border:1px solid #E0E0E0 !important;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# -----------------------
# Google Apps Script API (list/get/upsert/delete)
# -----------------------
def gs_get(params: dict) -> dict:
    if not GS_WEBAPP_URL or not GS_TOKEN:
        return {"ok": False, "error": "Missing GS_WEBAPP_URL / GS_TOKEN"}
    q = "&".join([f"{k}={urlreq.quote(str(v))}" for k, v in params.items()])
    url = f"{GS_WEBAPP_URL}?token={urlreq.quote(GS_TOKEN)}&{q}"
    try:
        with urlreq.urlopen(url, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"GET failed: {e}"}

def gs_post(action: str, sheet: str, name: str, payload_json: str) -> dict:
    if not GS_WEBAPP_URL or not GS_TOKEN:
        return {"ok": False, "error": "Missing GS_WEBAPP_URL / GS_TOKEN"}
    url = f"{GS_WEBAPP_URL}?token={urlreq.quote(GS_TOKEN)}&action={urlreq.quote(action)}&sheet={urlreq.quote(sheet)}&name={urlreq.quote(name)}"
    body = json.dumps({"token": GS_TOKEN, "action": action, "sheet": sheet, "name": name, "payload_json": payload_json}).encode("utf-8")
    try:
        req = urlreq.Request(url, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        with urlreq.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"POST failed: {e}"}

# -----------------------
# Data normalize
# -----------------------
BOX_COLS = ["選取","使用","名稱","長","寬","高","數量","空箱重量"]
PROD_COLS = ["選取","啟用","商品名稱","長","寬","高","重量(kg)","數量"]

def norm_box_df(df: pd.DataFrame) -> pd.DataFrame:
    for c in BOX_COLS:
        if c not in df.columns:
            df[c] = False if c in ["選取","使用"] else ""
    df = df[BOX_COLS].copy()
    df["選取"] = df["選取"].fillna(False).astype(bool)
    df["使用"] = df["使用"].fillna(False).astype(bool)
    df["名稱"] = df["名稱"].fillna("").astype(str)
    for c in ["長","寬","高","空箱重量"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["數量"] = pd.to_numeric(df["數量"], errors="coerce").fillna(0).astype(int)
    df["數量"] = df["數量"].clip(lower=0)
    return df

def norm_prod_df(df: pd.DataFrame) -> pd.DataFrame:
    for c in PROD_COLS:
        if c not in df.columns:
            df[c] = False if c in ["選取","啟用"] else ""
    df = df[PROD_COLS].copy()
    df["選取"] = df["選取"].fillna(False).astype(bool)
    df["啟用"] = df["啟用"].fillna(True).astype(bool)
    df["商品名稱"] = df["商品名稱"].fillna("").astype(str)
    for c in ["長","寬","高","重量(kg)"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["數量"] = pd.to_numeric(df["數量"], errors="coerce").fillna(0).astype(int)
    df["數量"] = df["數量"].clip(lower=0)
    return df

# -----------------------
# init state (only once)
# -----------------------
def load_current_from_gs():
    # 用固定 name：box_state / product_state（你清單已看到 box_state）
    box = gs_get({"action":"get","sheet":BOX_SHEET,"name":"box_state"})
    prod = gs_get({"action":"get","sheet":PROD_SHEET,"name":"product_state"})

    box_rows = []
    prod_rows = []

    if box.get("ok"):
        try:
            box_rows = json.loads(box.get("payload_json") or "[]")
        except Exception:
            box_rows = []
    if prod.get("ok"):
        try:
            prod_rows = json.loads(prod.get("payload_json") or "[]")
        except Exception:
            prod_rows = []

    return box_rows, prod_rows

if "inited" not in st.session_state:
    st.session_state.inited = True
    st.session_state.order_name = st.session_state.get("order_name", f"訂單_{dt.datetime.now().strftime('%Y%m%d')}")
    st.session_state.layout_mode = st.session_state.get("layout_mode", "左右 50% / 50%")
    st.session_state.active_box_tpl = ""
    st.session_state.active_prod_tpl = ""

    # load current
    box_rows, prod_rows = load_current_from_gs()
    if box_rows:
        st.session_state.box_df = norm_box_df(pd.DataFrame(box_rows))
    else:
        st.session_state.box_df = norm_box_df(pd.DataFrame([{
            "選取":False,"使用":True,"名稱":"手動箱","長":35,"寬":25,"高":20,"數量":1,"空箱重量":0.5
        }]))
    if prod_rows:
        st.session_state.prod_df = norm_prod_df(pd.DataFrame(prod_rows))
    else:
        st.session_state.prod_df = norm_prod_df(pd.DataFrame([{
            "選取":False,"啟用":True,"商品名稱":"禮盒(米餅)","長":21,"寬":14,"高":8.5,"重量(kg)":0.5,"數量":5
        }]))

# -----------------------
# UI Header
# -----------------------
st.markdown("## 📦 3D裝箱系統")
st.radio("版面配置", ["左右 50% / 50%","上下（垂直）"], key="layout_mode", horizontal=True)

# -----------------------
# Template helpers
# -----------------------
def list_templates(sheet: str):
    r = gs_get({"action":"list","sheet":sheet})
    if r.get("ok"):
        return r.get("items", [])
    return []

def load_template(sheet: str, name: str):
    r = gs_get({"action":"get","sheet":sheet,"name":name})
    if r.get("ok"):
        try:
            return json.loads(r.get("payload_json") or "[]")
        except Exception:
            return []
    return None

def save_template(sheet: str, name: str, rows: list):
    payload_json = json.dumps(rows, ensure_ascii=False)
    return gs_post("upsert", sheet, name, payload_json)

def delete_template(sheet: str, name: str):
    # delete 是 GET 也行（你的 Script 用 query 參數）
    r = gs_get({"action":"delete","sheet":sheet,"name":name})
    return r

# -----------------------
# Section render
# -----------------------
def render_boxes():
    st.markdown('<div class="section-title">1. 訂單與外箱</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)

    st.text_input("訂單名稱", key="order_name")

    st.markdown("### 箱型模板（載入 / 儲存 / 刪除）")
    names = ["(無)"] + list_templates(BOX_SHEET)
    c1,c2,c3 = st.columns([2,2,2])
    with c1:
        sel = st.selectbox("選擇模板", names, key="box_tpl_sel")
        saveas = st.text_input("另存為模板名稱", key="box_tpl_saveas", placeholder="例如：常用箱型A")
    with c2:
        if st.button("⬇️ 載入模板", key="box_tpl_load", use_container_width=True):
            if sel != "(無)":
                with st.spinner("讀取中..."):
                    rows = load_template(BOX_SHEET, sel)
                if rows is None:
                    st.error("載入失敗")
                else:
                    st.session_state.box_df = norm_box_df(pd.DataFrame(rows))
                    st.session_state.active_box_tpl = sel
                    st.toast("已載入箱型模板", icon="⬇️")
            else:
                st.warning("請先選擇模板")
        if st.button("💾 儲存模板", key="box_tpl_save", use_container_width=True):
            nm = (saveas or "").strip()
            if not nm:
                st.warning("請輸入另存為模板名稱")
            else:
                with st.spinner("儲存中..."):
                    r = save_template(BOX_SHEET, nm, st.session_state.box_df.to_dict("records"))
                if r.get("ok"):
                    st.session_state.active_box_tpl = nm
                    st.toast("已儲存", icon="💾")
                else:
                    st.error(f"儲存失敗：{r.get('error') or r}")
    with c3:
        del_sel = st.selectbox("要刪除的模板", names, key="box_tpl_del_sel")
        if st.button("🗑 刪除模板", key="box_tpl_del", use_container_width=True):
            if del_sel != "(無)":
                with st.spinner("刪除中..."):
                    r = delete_template(BOX_SHEET, del_sel)
                if r.get("ok"):
                    if st.session_state.active_box_tpl == del_sel:
                        st.session_state.active_box_tpl = ""
                    st.toast("已刪除", icon="🗑")
                else:
                    st.error(f"刪除失敗：{r.get('error') or r}")

    st.markdown(f'<div class="smallnote">目前套用：<span class="badge">{st.session_state.active_box_tpl or "未選擇"}</span></div>', unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("### 箱型表格（勾選→刪除）")

    with st.form("box_form"):
        edited = st.data_editor(
            st.session_state.box_df,
            use_container_width=True,
            num_rows="dynamic",
            height=360,
            column_config={
                "選取": st.column_config.CheckboxColumn(width="small"),
                "使用": st.column_config.CheckboxColumn(width="small"),
            },
            key="box_editor",
        )
        cA,cB = st.columns([1,1])
        with cA:
            apply_btn = st.form_submit_button("✅ 套用變更", use_container_width=True)
        with cB:
            del_btn = st.form_submit_button("🗑 刪除勾選", use_container_width=True)

    if apply_btn or del_btn:
        df = norm_box_df(edited)
        if del_btn:
            df = df[df["選取"] == False].copy()
            df["選取"] = False
        st.session_state.box_df = norm_box_df(df.reset_index(drop=True))

        # 同步目前狀態到 box_state
        save_template(BOX_SHEET, "box_state", st.session_state.box_df.to_dict("records"))
        st.toast("已套用並同步", icon="✅")
        st.rerun()

    if st.button("🧹 清除套用", key="box_clear", use_container_width=True):
        st.session_state.box_df = norm_box_df(pd.DataFrame([]))
        save_template(BOX_SHEET, "box_state", [])
        st.session_state.active_box_tpl = ""
        st.toast("已清除", icon="🧹")
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

def render_products():
    st.markdown('<div class="section-title">2. 商品清單</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)

    st.markdown("### 商品模板（載入 / 儲存 / 刪除）")
    names = ["(無)"] + list_templates(PROD_SHEET)
    c1,c2,c3 = st.columns([2,2,2])
    with c1:
        sel = st.selectbox("選擇模板", names, key="prod_tpl_sel")
        saveas = st.text_input("另存為模板名稱", key="prod_tpl_saveas", placeholder="例如：常用商品組合A")
    with c2:
        if st.button("⬇️ 載入模板", key="prod_tpl_load", use_container_width=True):
            if sel != "(無)":
                with st.spinner("讀取中..."):
                    rows = load_template(PROD_SHEET, sel)
                if rows is None:
                    st.error("載入失敗")
                else:
                    st.session_state.prod_df = norm_prod_df(pd.DataFrame(rows))
                    st.session_state.active_prod_tpl = sel
                    st.toast("已載入商品模板", icon="⬇️")
            else:
                st.warning("請先選擇模板")
        if st.button("💾 儲存模板", key="prod_tpl_save", use_container_width=True):
            nm = (saveas or "").strip()
            if not nm:
                st.warning("請輸入另存為模板名稱")
            else:
                with st.spinner("儲存中..."):
                    r = save_template(PROD_SHEET, nm, st.session_state.prod_df.to_dict("records"))
                if r.get("ok"):
                    st.session_state.active_prod_tpl = nm
                    st.toast("已儲存", icon="💾")
                else:
                    st.error(f"儲存失敗：{r.get('error') or r}")
    with c3:
        del_sel = st.selectbox("要刪除的模板", names, key="prod_tpl_del_sel")
        if st.button("🗑 刪除模板", key="prod_tpl_del", use_container_width=True):
            if del_sel != "(無)":
                with st.spinner("刪除中..."):
                    r = delete_template(PROD_SHEET, del_sel)
                if r.get("ok"):
                    if st.session_state.active_prod_tpl == del_sel:
                        st.session_state.active_prod_tpl = ""
                    st.toast("已刪除", icon="🗑")
                else:
                    st.error(f"刪除失敗：{r.get('error') or r}")

    st.markdown(f'<div class="smallnote">目前套用：<span class="badge">{st.session_state.active_prod_tpl or "未選擇"}</span></div>', unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("### 商品表格（勾選→刪除）")

    with st.form("prod_form"):
        edited = st.data_editor(
            st.session_state.prod_df,
            use_container_width=True,
            num_rows="dynamic",
            height=360,
            column_config={
                "選取": st.column_config.CheckboxColumn(width="small"),
                "啟用": st.column_config.CheckboxColumn(width="small"),
            },
            key="prod_editor",
        )
        cA,cB = st.columns([1,1])
        with cA:
            apply_btn = st.form_submit_button("✅ 套用變更", use_container_width=True)
        with cB:
            del_btn = st.form_submit_button("🗑 刪除勾選", use_container_width=True)

    if apply_btn or del_btn:
        df = norm_prod_df(edited)
        if del_btn:
            df = df[df["選取"] == False].copy()
            df["選取"] = False
        st.session_state.prod_df = norm_prod_df(df.reset_index(drop=True))

        # 同步目前狀態到 product_state
        save_template(PROD_SHEET, "product_state", st.session_state.prod_df.to_dict("records"))
        st.toast("已套用並同步", icon="✅")
        st.rerun()

    if st.button("🧹 清除套用", key="prod_clear", use_container_width=True):
        st.session_state.prod_df = norm_prod_df(pd.DataFrame([]))
        save_template(PROD_SHEET, "product_state", [])
        st.session_state.active_prod_tpl = ""
        st.toast("已清除", icon="🧹")
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# -----------------------
# Layout
# -----------------------
if st.session_state.layout_mode == "左右 50% / 50%":
    left,right = st.columns(2, gap="large")
    with left: render_boxes()
    with right: render_products()
else:
    render_boxes()
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    render_products()

# -----------------------
# 3D 模擬（先保留簡版：確認存取正常再繼續升級智慧擺放）
# -----------------------
st.markdown('<div class="section-title">3. 模擬</div>', unsafe_allow_html=True)
st.button("🚀 開始計算與 3D 模擬", key="btn_run", use_container_width=True)
st.info("✅ 目前先以「模板讀寫穩定」為第一優先；3D 智慧擺放（直/橫/平）我下一步再幫你升級。")
