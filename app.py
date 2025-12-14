import json
import re
import datetime as dt
from urllib import request as urlreq

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# -----------------------
# Page
# -----------------------
st.set_page_config(page_title="3D裝箱系統", page_icon="📦", layout="wide")

# -----------------------
# Secrets (Streamlit Community Cloud)
# -----------------------
GS_WEBAPP_URL = st.secrets.get("GS_WEBAPP_URL", "").strip()
GS_TOKEN = st.secrets.get("GS_TOKEN", "").strip()

BOX_SHEET = "box_templates"
PROD_SHEET = "product_templates"

# -----------------------
# CSS (UI clean + button colors)
# -----------------------
CSS = """
<style>
.block-container{max-width:1600px;padding-top:1.2rem;padding-bottom:2rem;}
hr{border:none;border-top:1px solid #E5E7EB;margin:12px 0;}
.h-title{display:flex;align-items:center;gap:10px;margin-bottom:6px;}
.h-title .logo{font-size:1.55rem;}
.h-title .txt{font-weight:900;font-size:1.7rem;}
.section-title{font-weight:900;font-size:1.05rem;margin:6px 0 10px 0;padding-left:10px;border-left:4px solid #EF4444;}
.panel{border:1px solid #E5E7EB;background:#FFFFFF;border-radius:16px;padding:14px 14px 12px 14px;box-shadow:0 6px 18px rgba(0,0,0,.04);}
.subttl{font-weight:900;font-size:1.05rem;margin:0 0 8px 0;}
.smallnote{color:#6B7280;font-size:0.88rem;margin-top:-2px;}
.badge{display:inline-block;padding:6px 10px;border-radius:999px;font-weight:900;font-size:0.9rem;border:1px solid #E5E7EB;background:#F9FAFB;}
.btnrow{display:flex;gap:10px;flex-wrap:wrap;margin-top:6px;}
/* Streamlit buttons (best-effort) */
button[kind="primary"]{border-radius:12px;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# -----------------------
# Google Apps Script API (list/get/upsert/delete)
# -----------------------
def _require_cloud_config():
    if not GS_WEBAPP_URL or not GS_TOKEN:
        st.error("缺少 Streamlit Secrets：GS_WEBAPP_URL / GS_TOKEN（Settings → Secrets）")
        st.stop()

def gs_get(params: dict) -> dict:
    _require_cloud_config()
    q = "&".join([f"{k}={urlreq.quote(str(v))}" for k, v in params.items()])
    url = f"{GS_WEBAPP_URL}?token={urlreq.quote(GS_TOKEN)}&{q}"
    try:
        with urlreq.urlopen(url, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"GET failed: {e}"}

def gs_post(action: str, sheet: str, name: str, payload_json: str) -> dict:
    _require_cloud_config()
    url = (
        f"{GS_WEBAPP_URL}"
        f"?token={urlreq.quote(GS_TOKEN)}"
        f"&action={urlreq.quote(action)}"
        f"&sheet={urlreq.quote(sheet)}"
        f"&name={urlreq.quote(name)}"
    )
    body = json.dumps(
        {"token": GS_TOKEN, "action": action, "sheet": sheet, "name": name, "payload_json": payload_json},
        ensure_ascii=False
    ).encode("utf-8")
    try:
        req = urlreq.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST"
        )
        with urlreq.urlopen(req, timeout=35) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"POST failed: {e}"}

# -----------------------
# Data schema (ONLY ONE checkbox column: 選取)
# -----------------------
BOX_COLS = ["選取", "名稱", "長", "寬", "高", "數量", "空箱重量"]
PROD_COLS = ["選取", "商品名稱", "長", "寬", "高", "重量(kg)", "數量"]

def norm_box_df(df: pd.DataFrame) -> pd.DataFrame:
    for c in BOX_COLS:
        if c not in df.columns:
            df[c] = False if c == "選取" else ""
    df = df[BOX_COLS].copy()
    df["選取"] = df["選取"].fillna(False).astype(bool)
    df["名稱"] = df["名稱"].fillna("").astype(str)

    for c in ["長", "寬", "高", "空箱重量"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    df["數量"] = pd.to_numeric(df["數量"], errors="coerce").fillna(0).astype(int)
    df["數量"] = df["數量"].clip(lower=0)
    return df

def norm_prod_df(df: pd.DataFrame) -> pd.DataFrame:
    for c in PROD_COLS:
        if c not in df.columns:
            df[c] = False if c == "選取" else ""
    df = df[PROD_COLS].copy()
    df["選取"] = df["選取"].fillna(False).astype(bool)
    df["商品名稱"] = df["商品名稱"].fillna("").astype(str)

    for c in ["長", "寬", "高", "重量(kg)"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    df["數量"] = pd.to_numeric(df["數量"], errors="coerce").fillna(0).astype(int)
    df["數量"] = df["數量"].clip(lower=0)
    return df

# -----------------------
# Template helpers
# -----------------------
def list_templates(sheet: str):
    r = gs_get({"action": "list", "sheet": sheet})
    if r.get("ok"):
        return sorted(list(dict.fromkeys(r.get("items", []))))
    return []

def load_template(sheet: str, name: str):
    r = gs_get({"action": "get", "sheet": sheet, "name": name})
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
    return gs_get({"action": "delete", "sheet": sheet, "name": name})

# -----------------------
# Load current state from Google Sheet (box_state / product_state)
# -----------------------
def load_current_state():
    box = gs_get({"action": "get", "sheet": BOX_SHEET, "name": "box_state"})
    prod = gs_get({"action": "get", "sheet": PROD_SHEET, "name": "product_state"})

    box_rows, prod_rows = [], []
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

# -----------------------
# Init session state (stable on Community Cloud)
# -----------------------
if "inited" not in st.session_state:
    st.session_state.inited = True
    st.session_state.layout_mode = "左右 50% / 50%"
    st.session_state.order_name = f"訂單_{dt.datetime.now().strftime('%Y%m%d')}"
    st.session_state.active_box_tpl = ""
    st.session_state.active_prod_tpl = ""

    box_rows, prod_rows = load_current_state()

    if box_rows:
        st.session_state.box_df = norm_box_df(pd.DataFrame(box_rows))
    else:
        st.session_state.box_df = norm_box_df(pd.DataFrame([{
            "選取": False,
            "名稱": "手動箱",
            "長": 35.0,
            "寬": 25.0,
            "高": 20.0,
            "數量": 1,
            "空箱重量": 0.50
        }]))

    if prod_rows:
        st.session_state.prod_df = norm_prod_df(pd.DataFrame(prod_rows))
    else:
        st.session_state.prod_df = norm_prod_df(pd.DataFrame([{
            "選取": False,
            "商品名稱": "禮盒(米餅)",
            "長": 21.0,
            "寬": 14.0,
            "高": 8.5,
            "重量(kg)": 0.50,
            "數量": 5
        }]))

# -----------------------
# Header
# -----------------------
st.markdown(
    '<div class="h-title"><div class="logo">📦</div><div class="txt">3D裝箱系統</div></div>',
    unsafe_allow_html=True
)
st.radio("版面配置", ["左右 50% / 50%", "上下（垂直）"], key="layout_mode", horizontal=True)

# -----------------------
# UI building blocks
# -----------------------
def template_block(title: str, sheet: str, active_key: str, load_key_prefix: str):
    st.markdown(f'<div class="subttl">{title}</div>', unsafe_allow_html=True)
    names = ["(無)"] + list_templates(sheet)

    c1, c2, c3 = st.columns([2.3, 2.2, 2.0])
    with c1:
        sel = st.selectbox("選擇模板", names, key=f"{load_key_prefix}_sel")
        saveas = st.text_input("另存為模板名稱", key=f"{load_key_prefix}_saveas", placeholder="例如：常用A")
    with c2:
        load_btn = st.button("⬇️ 載入模板", key=f"{load_key_prefix}_load", use_container_width=True)
        save_btn = st.button("💾 儲存模板", key=f"{load_key_prefix}_save", use_container_width=True)
    with c3:
        del_sel = st.selectbox("要刪除的模板", names, key=f"{load_key_prefix}_del_sel")
        del_btn = st.button("🗑 刪除模板", key=f"{load_key_prefix}_del", use_container_width=True)

    if load_btn:
        if sel == "(無)":
            st.warning("請先選擇模板")
        else:
            with st.spinner("讀取中..."):
                rows = load_template(sheet, sel)
            if rows is None:
                st.error("載入失敗")
            else:
                st.session_state[active_key] = sel
                st.toast("已載入模板", icon="⬇️")
                return ("load", sel, rows)

    if save_btn:
        nm = (saveas or "").strip()
        if not nm:
            st.warning("請輸入另存為模板名稱")
        else:
            st.session_state[active_key] = nm
            return ("save", nm, None)

    if del_btn:
        if del_sel == "(無)":
            st.warning("請先選擇要刪除的模板")
        else:
            with st.spinner("刪除中..."):
                r = delete_template(sheet, del_sel)
            if r.get("ok"):
                if st.session_state.get(active_key, "") == del_sel:
                    st.session_state[active_key] = ""
                st.toast("已刪除模板", icon="🗑")
                st.rerun()
            else:
                st.error(f"刪除失敗：{r.get('error') or r}")

    st.markdown(
        f'<div class="smallnote">目前套用：<span class="badge">{st.session_state.get(active_key) or "未選擇"}</span></div>',
        unsafe_allow_html=True
    )
    return (None, None, None)

def data_editor_box(df: pd.DataFrame):
    return st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        height=420,  # >= 8 rows feel
        column_config={
            "選取": st.column_config.CheckboxColumn("選取", help="勾選後按下方「刪除勾選」即可刪除該列", width="small"),
            "長": st.column_config.NumberColumn("長", step=0.1, format="%.2f"),
            "寬": st.column_config.NumberColumn("寬", step=0.1, format="%.2f"),
            "高": st.column_config.NumberColumn("高", step=0.1, format="%.2f"),
            "空箱重量": st.column_config.NumberColumn("空箱重量", step=0.01, format="%.2f"),
            "數量": st.column_config.NumberColumn("數量", step=1, format="%d"),
        },
        key="box_editor",
    )

def data_editor_prod(df: pd.DataFrame):
    return st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        height=420,
        column_config={
            "選取": st.column_config.CheckboxColumn("選取", help="勾選後按下方「刪除勾選」即可刪除該列", width="small"),
            "長": st.column_config.NumberColumn("長", step=0.1, format="%.2f"),
            "寬": st.column_config.NumberColumn("寬", step=0.1, format="%.2f"),
            "高": st.column_config.NumberColumn("高", step=0.1, format="%.2f"),
            "重量(kg)": st.column_config.NumberColumn("重量(kg)", step=0.01, format="%.2f"),
            "數量": st.column_config.NumberColumn("數量", step=1, format="%d"),
        },
        key="prod_editor",
    )

# -----------------------
# Sections
# -----------------------
def render_left():
    st.markdown('<div class="section-title">1. 訂單與外箱</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)

    st.text_input("訂單名稱", key="order_name")

    st.markdown("<hr>", unsafe_allow_html=True)
    action, name, rows = template_block("箱型模板（載入 / 儲存 / 刪除）", BOX_SHEET, "active_box_tpl", "box_tpl")

    # apply load/save actions
    if action == "load":
        st.session_state.box_df = norm_box_df(pd.DataFrame(rows))
        save_template(BOX_SHEET, "box_state", st.session_state.box_df.to_dict("records"))
        st.rerun()

    if action == "save":
        with st.spinner("儲存中..."):
            r = save_template(BOX_SHEET, name, st.session_state.box_df.to_dict("records"))
        if r.get("ok"):
            st.toast("已儲存箱型模板", icon="💾")
            st.rerun()
        else:
            st.error(f"儲存失敗：{r.get('error') or r}")

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<div class="subttl">箱型表格（數量 > 0 會參與計算；選取用於刪除）</div>', unsafe_allow_html=True)
    edited = data_editor_box(st.session_state.box_df)

    cA, cB, cC = st.columns([1, 1, 1])
    if cA.button("✅ 套用變更", use_container_width=True):
        st.session_state.box_df = norm_box_df(edited)
        save_template(BOX_SHEET, "box_state", st.session_state.box_df.to_dict("records"))
        st.toast("已套用外箱變更", icon="✅")
        st.rerun()

    if cB.button("🗑 刪除勾選", use_container_width=True):
        df = norm_box_df(edited)
        df = df[df["選取"] == False].copy()
        df["選取"] = False
        st.session_state.box_df = norm_box_df(df.reset_index(drop=True))
        save_template(BOX_SHEET, "box_state", st.session_state.box_df.to_dict("records"))
        st.toast("已刪除勾選列", icon="🗑")
        st.rerun()

    if cC.button("🧹 清除所有外箱", use_container_width=True):
        st.session_state.box_df = norm_box_df(pd.DataFrame([]))
        save_template(BOX_SHEET, "box_state", [])
        st.session_state.active_box_tpl = ""
        st.toast("已清除外箱", icon="🧹")
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

def render_right():
    st.markdown('<div class="section-title">2. 商品清單</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)

    action, name, rows = template_block("商品模板（載入 / 儲存 / 刪除）", PROD_SHEET, "active_prod_tpl", "prod_tpl")

    if action == "load":
        st.session_state.prod_df = norm_prod_df(pd.DataFrame(rows))
        save_template(PROD_SHEET, "product_state", st.session_state.prod_df.to_dict("records"))
        st.rerun()

    if action == "save":
        with st.spinner("儲存中..."):
            r = save_template(PROD_SHEET, name, st.session_state.prod_df.to_dict("records"))
        if r.get("ok"):
            st.toast("已儲存商品模板", icon="💾")
            st.rerun()
        else:
            st.error(f"儲存失敗：{r.get('error') or r}")

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<div class="subttl">商品表格（數量 > 0 會參與計算；選取用於刪除）</div>', unsafe_allow_html=True)
    edited = data_editor_prod(st.session_state.prod_df)

    cA, cB, cC = st.columns([1, 1, 1])
    if cA.button("✅ 套用變更", use_container_width=True):
        st.session_state.prod_df = norm_prod_df(edited)
        save_template(PROD_SHEET, "product_state", st.session_state.prod_df.to_dict("records"))
        st.toast("已套用商品變更", icon="✅")
        st.rerun()

    if cB.button("🗑 刪除勾選", use_container_width=True):
        df = norm_prod_df(edited)
        df = df[df["選取"] == False].copy()
        df["選取"] = False
        st.session_state.prod_df = norm_prod_df(df.reset_index(drop=True))
        save_template(PROD_SHEET, "product_state", st.session_state.prod_df.to_dict("records"))
        st.toast("已刪除勾選列", icon="🗑")
        st.rerun()

    if cC.button("🧹 清除所有商品", use_container_width=True):
        st.session_state.prod_df = norm_prod_df(pd.DataFrame([]))
        save_template(PROD_SHEET, "product_state", [])
        st.session_state.active_prod_tpl = ""
        st.toast("已清除商品", icon="🧹")
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# Layout switch (fix your #1 UI)
if st.session_state.layout_mode == "左右 50% / 50%":
    L, R = st.columns(2, gap="large")
    with L:
        render_left()
    with R:
        render_right()
else:
    render_left()
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    render_right()

# -----------------------
# Packing + 3D + Export HTML
# -----------------------
def safe_filename(s: str) -> str:
    s = (s or "").strip()
    if not s:
        s = "訂單"
    s = re.sub(r"[\\/:*?\"<>|#]+", "_", s)
    s = re.sub(r"\s+", "_", s)
    return s[:80]

def build_plotly_3d(bin_dim, items):
    """
    bin_dim: (L,W,H)
    items: list of dict {name, x,y,z, dx,dy,dz}
    """
    L, W, H = bin_dim

    fig = go.Figure()

    # outer box (wireframe)
    # draw a wireframe cuboid
    corners = [
        (0, 0, 0), (L, 0, 0), (L, W, 0), (0, W, 0), (0, 0, 0),
        (0, 0, H), (L, 0, H), (L, W, H), (0, W, H), (0, 0, H),
        (L, 0, H), (L, 0, 0), (L, W, 0), (L, W, H), (0, W, H), (0, W, 0)
    ]
    xs, ys, zs = zip(*corners)
    fig.add_trace(go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="lines",
        line=dict(width=6, color="black"),
        name="外箱"
    ))

    # Professional muted palette (not too light / not rainbow)
    palette = [
        "rgba(37,99,235,0.70)",   # blue
        "rgba(16,185,129,0.70)",  # green
        "rgba(245,158,11,0.70)",  # amber
        "rgba(139,92,246,0.70)",  # violet
        "rgba(239,68,68,0.70)",   # red
        "rgba(14,116,144,0.70)",  # teal
    ]

    # add items as meshes (rectangular prism)
    def cuboid_mesh(x, y, z, dx, dy, dz):
        # 8 corners
        pts = [
            (x, y, z),
            (x+dx, y, z),
            (x+dx, y+dy, z),
            (x, y+dy, z),
            (x, y, z+dz),
            (x+dx, y, z+dz),
            (x+dx, y+dy, z+dz),
            (x, y+dy, z+dz),
        ]
        X, Y, Z = zip(*pts)
        # 12 triangles
        I = [0,0,0, 1,1, 2,2, 4,4, 5,5, 6]
        J = [1,2,3, 2,5, 3,6, 5,6, 6,7, 7]
        K = [2,3,1, 5,4, 6,7, 6,7, 7,4, 4]
        return X, Y, Z, I, J, K

    for idx, it in enumerate(items):
        color = palette[idx % len(palette)]
        X, Y, Z, I, J, K = cuboid_mesh(it["x"], it["y"], it["z"], it["dx"], it["dy"], it["dz"])
        fig.add_trace(go.Mesh3d(
            x=X, y=Y, z=Z,
            i=I, j=J, k=K,
            opacity=1.0,
            color=color,
            name=it["name"],
            flatshading=True
        ))

    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        scene=dict(
            xaxis=dict(title="x", backgroundcolor="white", gridcolor="#E5E7EB", zerolinecolor="#E5E7EB"),
            yaxis=dict(title="y", backgroundcolor="white", gridcolor="#E5E7EB", zerolinecolor="#E5E7EB"),
            zaxis=dict(title="z", backgroundcolor="white", gridcolor="#E5E7EB", zerolinecolor="#E5E7EB"),
            bgcolor="white",
            aspectmode="data"
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig

def run_packing(box_df: pd.DataFrame, prod_df: pd.DataFrame):
    # Only count rows with qty>0
    boxes = box_df.copy()
    boxes = boxes[boxes["數量"] > 0].copy()

    prods = prod_df.copy()
    prods = prods[prods["數量"] > 0].copy()

    if boxes.empty:
        return {"ok": False, "error": "沒有可用外箱（請至少一個外箱數量 > 0）"}
    if prods.empty:
        return {"ok": False, "error": "沒有商品（請至少一個商品數量 > 0）"}

    # Take first box as target (single-box simulate) — stable baseline
    # (你要多箱分配我之後可以再加，但先確保穩定不報錯)
    b = boxes.iloc[0]
    bin_dim = (float(b["長"]), float(b["寬"]), float(b["高"]))
    empty_weight = float(b["空箱重量"])

    # Try py3dbp
    try:
        from py3dbp import Packer, Bin, Item
    except Exception:
        return {"ok": False, "error": "缺少套件 py3dbp，請確認 requirements.txt 有 py3dbp"}

    packer = Packer()
    packer.add_bin(Bin("Box", bin_dim[0], bin_dim[1], bin_dim[2], 999999))

    total_weight = 0.0
    total_qty = 0

    for _, r in prods.iterrows():
        name = str(r["商品名稱"] or "").strip() or "商品"
        L = float(r["長"]); W = float(r["寬"]); H = float(r["高"])
        w = float(r["重量(kg)"])
        qty = int(r["數量"])
        for i in range(qty):
            total_qty += 1
            total_weight += w
            packer.add_item(Item(f"{name}", L, W, H, w))

    # Avoid using unsupported kwargs (fix_point caused your crash before)
    try:
        packer.pack(bigger_first=True, distribute_items=False)
    except TypeError:
        packer.pack()

    b0 = packer.bins[0]
    fitted = getattr(b0, "items", []) or []
    unfitted = getattr(b0, "unfitted_items", []) or []

    # Convert to plot items
    plot_items = []
    for it in fitted:
        # py3dbp item has position and dimension
        pos = getattr(it, "position", [0,0,0])
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
        dx = float(getattr(it, "width"))
        dy = float(getattr(it, "depth"))
        dz = float(getattr(it, "height"))
        plot_items.append({
            "name": str(getattr(it, "name", "item")),
            "x": x, "y": y, "z": z,
            "dx": dx, "dy": dy, "dz": dz
        })

    ok = len(unfitted) == 0
    used_volume = sum([p["dx"]*p["dy"]*p["dz"] for p in plot_items])
    box_volume = bin_dim[0]*bin_dim[1]*bin_dim[2]
    util = (used_volume / box_volume * 100.0) if box_volume > 0 else 0.0

    return {
        "ok": True,
        "pack_ok": ok,
        "bin_dim": bin_dim,
        "empty_weight": empty_weight,
        "total_weight": total_weight + empty_weight,
        "content_weight": total_weight,
        "total_qty": total_qty,
        "util": util,
        "plot_items": plot_items,
        "unfitted_count": len(unfitted),
        "unfitted_names": [getattr(u, "name", "item") for u in unfitted],
    }

def build_report_html(order_name: str, result: dict, fig: go.Figure):
    now = dt.datetime.now()
    safe_order = safe_filename(order_name)
    fname = f"{safe_order}_{now.strftime('%Y%m%d_%H%M')}_總數{result['total_qty']}件.html"

    # Short summary
    warn = ""
    if not result["pack_ok"]:
        warn = f"<div style='margin:10px 0;padding:10px;border:1px solid #FCA5A5;background:#FEE2E2;border-radius:10px;color:#991B1B;font-weight:800;'>注意：有部分商品裝不下（遺漏 {result['unfitted_count']} 個）</div>"

    fig_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{safe_order} 裝箱報告</title>
<style>
body{{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans TC",Arial;margin:20px;color:#111827;}}
.card{{border:1px solid #E5E7EB;border-radius:14px;padding:14px;box-shadow:0 6px 18px rgba(0,0,0,.04);}}
.row{{display:flex;gap:18px;flex-wrap:wrap;}}
.kv{{min-width:240px;}}
.k{{color:#6B7280;font-size:12px;margin-bottom:2px;}}
.v{{font-weight:900;font-size:16px;}}
hr{{border:none;border-top:1px solid #E5E7EB;margin:14px 0;}}
</style>
</head>
<body>
<h2 style="margin:0 0 6px 0;">📦 裝箱報告</h2>
<div style="color:#6B7280;margin-bottom:12px;">訂單：<b>{safe_order}</b>｜時間：{now.strftime('%Y-%m-%d %H:%M')}</div>

<div class="card">
  <div class="row">
    <div class="kv"><div class="k">外箱尺寸 (長×寬×高)</div><div class="v">{result['bin_dim'][0]} × {result['bin_dim'][1]} × {result['bin_dim'][2]}</div></div>
    <div class="kv"><div class="k">內容淨重</div><div class="v">{result['content_weight']:.2f} kg</div></div>
    <div class="kv"><div class="k">本次總重（含空箱）</div><div class="v" style="color:#B91C1C;">{result['total_weight']:.2f} kg</div></div>
    <div class="kv"><div class="k">空間利用率</div><div class="v">{result['util']:.2f}%</div></div>
  </div>
  {warn}
</div>

<hr/>
<div class="card">
  <h3 style="margin:0 0 10px 0;">3D 模擬</h3>
  {fig_html}
</div>

</body></html>
"""
    return fname, html

# -----------------------
# 3D Section UI
# -----------------------
st.markdown('<div class="section-title">3. 裝箱結果與模擬</div>', unsafe_allow_html=True)
st.markdown('<div class="panel">', unsafe_allow_html=True)

run = st.button("🚀 開始計算與 3D 模擬", type="primary", use_container_width=True)

if run:
    with st.spinner("計算中..."):
        result = run_packing(st.session_state.box_df, st.session_state.prod_df)

    if not result.get("ok"):
        st.error(result.get("error") or "計算失敗")
    else:
        st.subheader("訂單裝箱報告")

        colA, colB, colC, colD = st.columns([1.2,1,1,1])
        colA.metric("訂單名稱", safe_filename(st.session_state.order_name))
        colB.metric("內容淨重", f"{result['content_weight']:.2f} kg")
        colC.metric("本次總重(含空箱)", f"{result['total_weight']:.2f} kg")
        colD.metric("空間利用率", f"{result['util']:.2f}%")

        if not result["pack_ok"]:
            st.error(f"注意：有部分商品裝不下（遺漏 {result['unfitted_count']} 個）")

        fig = build_plotly_3d(result["bin_dim"], result["plot_items"])
        st.plotly_chart(fig, use_container_width=True)

        # Export HTML (restore feature + naming rule)
        fname, html = build_report_html(st.session_state.order_name, result, fig)
        st.download_button(
            "⬇️ 下載完整裝箱報告（.html）",
            data=html.encode("utf-8"),
            file_name=fname,
            mime="text/html",
            use_container_width=True,
        )

st.markdown("</div>", unsafe_allow_html=True)
