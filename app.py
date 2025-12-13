import os
import json
import math
import datetime
from typing import Dict, Any, Tuple, List

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import requests

# 3D packing
from py3dbp import Packer, Bin, Item


# =========================================================
# Page / Theme
# =========================================================
st.set_page_config(
    page_title="3D裝箱系統",
    page_icon="📦",
    layout="wide",
)

# 你要的按鈕分級色系（用 CSS 盡量穩定套用）
# 注意：Streamlit 的 button 難以「100% 精準」針對每個 key 上色（DOM 會變）
# 我採用「在固定區塊內」的按鈕順序上色，並把按鈕都集中在同一區塊，穩定性最高。
CSS = """
<style>
/* 全站字體細節 */
html, body, [class*="css"]  { font-family: "Inter", "Noto Sans TC", system-ui, -apple-system, "Segoe UI", sans-serif; }

/* 卡片感 */
.block-container { padding-top: 1.2rem; }

/* Data editor 更清楚 */
div[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; border: 1px solid rgba(0,0,0,.08); }
div[data-testid="stDataFrame"] thead tr th { background: rgba(0,0,0,.03) !important; }

/* 讓 3D 區塊不會全白看不到（保底） */
.plotly { background: white !important; }

/* ---- 按鈕色票（淡色系） ---- */
/* 我把每組操作按鈕都放在同一個「操作列」容器，並固定順序：
   新增(淡綠) / 刪除(淡紅) / 儲存(淡藍) / 載入(淡灰)
*/
#btnbar-ops div[data-testid="stButton"] button {
  border-radius: 12px !important;
  border: 1px solid rgba(0,0,0,.10) !important;
  font-weight: 600 !important;
  padding: .55rem .9rem !important;
}

/* 新增 */
#btnbar-ops div[data-testid="stButton"]:nth-of-type(1) button {
  background: #E9F7EF !important;
  color: #1E6B3A !important;
}
/* 刪除 */
#btnbar-ops div[data-testid="stButton"]:nth-of-type(2) button {
  background: #FDECEC !important;
  color: #8A1F1F !important;
}
/* 儲存 */
#btnbar-ops div[data-testid="stButton"]:nth-of-type(3) button {
  background: #EAF2FF !important;
  color: #1E4C99 !important;
}
/* 載入 */
#btnbar-ops div[data-testid="stButton"]:nth-of-type(4) button {
  background: #F2F4F7 !important;
  color: #374151 !important;
}

/* 主要動作：開始計算 -> 淡綠 */
#btnbar-run div[data-testid="stButton"] button {
  background: #E9F7EF !important;
  color: #1E6B3A !important;
  border-radius: 14px !important;
  border: 1px solid rgba(0,0,0,.10) !important;
  font-weight: 800 !important;
  padding: .7rem 1.1rem !important;
}

/* 下載報告按鈕不要黑底 */
div[data-testid="stDownloadButton"] button{
  background: #F2F4F7 !important;
  color: #111827 !important;
  border-radius: 12px !important;
  border: 1px solid rgba(0,0,0,.10) !important;
  font-weight: 700 !important;
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# =========================================================
# Google Apps Script (WebApp) Storage
# =========================================================
def get_secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, default)
    except Exception:
        return os.environ.get(name, default)


GAS_URL = get_secret("GAS_URL", "").strip()
TOKEN = get_secret("TOKEN", "").strip()


def gas_call(payload: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    """
    透過 Apps Script WebApp 讀寫資料。
    你 Apps Script 端只要回 JSON：
      { ok: true, data: ... } 或 { ok:false, error:"..." }
    """
    if not GAS_URL:
        return {"ok": False, "error": "尚未設定 GAS_URL（Streamlit Secrets）"}

    payload = dict(payload)
    if TOKEN:
        payload["token"] = TOKEN

    try:
        r = requests.post(GAS_URL, json=payload, timeout=timeout)
        # 有些 WebApp 會回 text/plain
        try:
            return r.json()
        except Exception:
            return json.loads(r.text)
    except Exception as e:
        return {"ok": False, "error": f"連線 Apps Script 失敗：{e}"}


def storage_list_templates(kind: str) -> List[str]:
    res = gas_call({"action": "list", "kind": kind})
    if res.get("ok"):
        return res.get("names", []) or []
    return []


def storage_load_template(kind: str, name: str) -> Dict[str, Any]:
    res = gas_call({"action": "load", "kind": kind, "name": name})
    if res.get("ok"):
        return res.get("data", {}) or {}
    raise RuntimeError(res.get("error", "載入失敗"))


def storage_save_template(kind: str, name: str, data: Dict[str, Any]) -> None:
    res = gas_call({"action": "save", "kind": kind, "name": name, "data": data})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "儲存失敗"))


def storage_delete_template(kind: str, name: str) -> None:
    res = gas_call({"action": "delete", "kind": kind, "name": name})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "刪除失敗"))


# =========================================================
# Stable schema helpers (防止 LIST/型別漂移)
# =========================================================
BOX_COLS = ["使用", "名稱", "長", "寬", "高", "數量", "空箱重量"]
PROD_COLS = ["啟用", "商品名稱", "長", "寬", "高", "重量(kg)", "數量"]

def _to_bool(x) -> bool:
    if isinstance(x, bool):
        return x
    if x is None:
        return False
    if isinstance(x, (int, float)):
        return bool(x)
    s = str(x).strip().lower()
    return s in ("1", "true", "yes", "y", "on", "是", "勾選")

def coerce_box_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in BOX_COLS:
        if c not in df.columns:
            df[c] = None

    df["使用"] = df["使用"].apply(_to_bool)
    df["名稱"] = df["名稱"].fillna("").astype(str)

    for c in ["長", "寬", "高", "空箱重量"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    df["數量"] = pd.to_numeric(df["數量"], errors="coerce").fillna(0).astype(int)
    return df[BOX_COLS]

def coerce_prod_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in PROD_COLS:
        if c not in df.columns:
            df[c] = None

    df["啟用"] = df["啟用"].apply(_to_bool)
    df["商品名稱"] = df["商品名稱"].fillna("").astype(str)

    for c in ["長", "寬", "高", "重量(kg)"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    df["數量"] = pd.to_numeric(df["數量"], errors="coerce").fillna(0).astype(int)
    return df[PROD_COLS]


def ensure_session_defaults():
    if "layout_mode" not in st.session_state:
        st.session_state.layout_mode = "左右 50% / 50%"

    if "order_name" not in st.session_state:
        st.session_state.order_name = f"訂單_{datetime.date.today().strftime('%Y%m%d')}"

    if "manual_box" not in st.session_state:
        st.session_state.manual_box = True

    if "manual_box_dim" not in st.session_state:
        st.session_state.manual_box_dim = {"長": 35.0, "寬": 25.0, "高": 20.0, "空箱重量": 0.5, "數量": 1, "名稱": "手動箱"}

    if "box_df" not in st.session_state:
        st.session_state.box_df = coerce_box_df(pd.DataFrame([{
            "使用": True, "名稱": "A款", "長": 45.0, "寬": 30.0, "高": 30.0, "數量": 1, "空箱重量": 0.5
        }]))

    if "prod_df" not in st.session_state:
        st.session_state.prod_df = coerce_prod_df(pd.DataFrame([
            {"啟用": True, "商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.50, "數量": 5},
            {"啟用": True, "商品名稱": "紙袋",     "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5},
        ]))

    if "last_pack_result" not in st.session_state:
        st.session_state.last_pack_result = None


ensure_session_defaults()


# =========================================================
# UI Helpers
# =========================================================
def section_title(num: str, title: str):
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:.6rem;margin:1.0rem 0 .4rem 0;">
          <div style="width:4px;height:18px;background:#ff4d4f;border-radius:99px;"></div>
          <div style="font-weight:800;font-size:1.05rem;">{num}. {title}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


# =========================================================
# 3D Packing (py3dbp) + Plotly render
# =========================================================
def build_items_from_prod_df(prod_df: pd.DataFrame) -> List[Item]:
    items: List[Item] = []
    prod_df = coerce_prod_df(prod_df)
    for _, r in prod_df.iterrows():
        if (not bool(r["啟用"])) or int(r["數量"]) <= 0:
            continue
        name = str(r["商品名稱"]).strip() or "未命名"
        L, W, H = float(r["長"]), float(r["寬"]), float(r["高"])
        wt = float(r["重量(kg)"])
        qty = int(r["數量"])
        # py3dbp：每顆 item 一個實體
        for i in range(qty):
            items.append(Item(f"{name}#{i+1}", L, W, H, wt))
    return items


def pick_bins_from_box_setting() -> List[Dict[str, Any]]:
    """
    回傳可用箱型清單（包含手動箱 + 勾選箱型）。
    """
    bins: List[Dict[str, Any]] = []
    if st.session_state.manual_box:
        d = st.session_state.manual_box_dim
        bins.append({
            "name": d["名稱"],
            "L": float(d["長"]), "W": float(d["寬"]), "H": float(d["高"]),
            "empty_wt": float(d["空箱重量"]),
            "qty": int(d["數量"]),
        })

    df = coerce_box_df(st.session_state.box_df)
    for _, r in df.iterrows():
        if (not bool(r["使用"])) or int(r["數量"]) <= 0:
            continue
        bins.append({
            "name": str(r["名稱"]).strip() or "未命名箱",
            "L": float(r["長"]), "W": float(r["寬"]), "H": float(r["高"]),
            "empty_wt": float(r["空箱重量"]),
            "qty": int(r["數量"]),
        })
    return bins


def run_packing(bin_spec: Dict[str, Any], items: List[Item]) -> Dict[str, Any]:
    """
    使用 py3dbp 裝箱，會自動嘗試旋轉（直/橫/平），比你目前的「平面」智慧很多。
    """
    packer = Packer()
    max_weight = 999999

    # 建 bin（單箱）
    b = Bin(bin_spec["name"], bin_spec["L"], bin_spec["W"], bin_spec["H"], max_weight)
    packer.add_bin(b)

    # items
    for it in items:
        packer.add_item(it)

    # pack：bigger_first 對「省空間」通常更好
    packer.pack(bigger_first=True, distribute_items=False, fix_point=True)

    packed_bin = packer.bins[0]
    fitted = packed_bin.items
    unfitted = packed_bin.unfitted_items

    # 估算利用率（以 item 體積 / 箱體積）
    bin_vol = bin_spec["L"] * bin_spec["W"] * bin_spec["H"]
    used_vol = sum((it.width * it.height * it.depth) for it in fitted)
    utilization = (used_vol / bin_vol) * 100 if bin_vol > 0 else 0

    # 重量
    items_wt = sum(it.weight for it in fitted)
    total_wt = items_wt + float(bin_spec["empty_wt"])

    return {
        "bin": bin_spec,
        "fitted": fitted,
        "unfitted": unfitted,
        "utilization": utilization,
        "items_weight": items_wt,
        "total_weight": total_wt,
    }


def best_single_box_plan(items: List[Item], bins: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    在你「可用箱型」中，挑一個最能裝的（優先：unfitted 最少 → utilization 最大）。
    """
    best = None
    for b in bins:
        if b["L"] <= 0 or b["W"] <= 0 or b["H"] <= 0:
            continue
        result = run_packing(b, items)
        score = (len(result["unfitted"]), -result["utilization"])  # unfitted 少優先，其次利用率高
        if best is None:
            best = (score, result)
        else:
            if score < best[0]:
                best = (score, result)
    if best is None:
        return {"error": "沒有可用箱型（尺寸需 > 0 且需勾選使用/手動箱）"}
    return best[1]


def plot_packing_3d(pack_result: Dict[str, Any]) -> go.Figure:
    """
    Plotly 3D：畫箱體線框 + 已裝入 items（半透明）
    """
    b = pack_result["bin"]
    L, W, H = b["L"], b["W"], b["H"]

    fig = go.Figure()

    # 箱體線框
    # 8 vertices
    verts = [
        (0,0,0), (L,0,0), (L,W,0), (0,W,0),
        (0,0,H), (L,0,H), (L,W,H), (0,W,H)
    ]
    edges = [
        (0,1),(1,2),(2,3),(3,0),
        (4,5),(5,6),(6,7),(7,4),
        (0,4),(1,5),(2,6),(3,7)
    ]
    for i,j in edges:
        x0,y0,z0 = verts[i]
        x1,y1,z1 = verts[j]
        fig.add_trace(go.Scatter3d(
            x=[x0,x1], y=[y0,y1], z=[z0,z1],
            mode="lines",
            line=dict(width=6),
            name="外箱",
            showlegend=False
        ))

    # items
    # py3dbp item 的 position 是 (x,y,z) ；尺寸在 it.width/height/depth（注意它的命名）
    # 在 py3dbp 中：width/height/depth 對應 (x,y,z) 方向
    # 我們直接畫長方體
    def add_box(x,y,z, dx,dy,dz, label):
        # 8 vertices
        v = [
            (x,y,z),
            (x+dx,y,z),
            (x+dx,y+dy,z),
            (x,y+dy,z),
            (x,y,z+dz),
            (x+dx,y,z+dz),
            (x+dx,y+dy,z+dz),
            (x,y+dy,z+dz),
        ]
        # 6 faces (as triangles)
        faces = [
            (0,1,2),(0,2,3),  # bottom
            (4,5,6),(4,6,7),  # top
            (0,1,5),(0,5,4),  # side
            (1,2,6),(1,6,5),
            (2,3,7),(2,7,6),
            (3,0,4),(3,4,7),
        ]
        X=[p[0] for p in v]
        Y=[p[1] for p in v]
        Z=[p[2] for p in v]
        I=[f[0] for f in faces]
        J=[f[1] for f in faces]
        K=[f[2] for f in faces]
        fig.add_trace(go.Mesh3d(
            x=X,y=Y,z=Z,
            i=I,j=J,k=K,
            opacity=0.55,
            name=label,
            hovertext=label,
            hoverinfo="text",
            showlegend=False
        ))

    fitted = pack_result["fitted"]
    # 顏色交給 plotly 自動（避免你那邊又被顏色干擾）
    for it in fitted:
        pos = it.position
        x,y,z = float(pos[0]), float(pos[1]), float(pos[2])
        dx,dy,dz = float(it.width), float(it.height), float(it.depth)
        add_box(x,y,z, dx,dy,dz, it.name)

    fig.update_layout(
        margin=dict(l=10,r=10,t=10,b=10),
        scene=dict(
            xaxis_title="x",
            yaxis_title="y",
            zaxis_title="z",
            aspectmode="data",
            bgcolor="white"
        ),
        height=520
    )
    return fig


# =========================================================
# Main UI
# =========================================================
st.title("📦 3D裝箱系統")
st.caption("穩定版（Form 套用避免跳回 / 3D 改用 py3dbp 自動旋轉判斷）")

# Layout switch (你要的那種切換)
section_title("版面配置", "")
layout = st.radio(
    " ",
    ["左右 50% / 50%", "上下（垂直）"],
    horizontal=True,
    key="layout_mode"
)

# decide containers
if layout == "左右 50% / 50%":
    left, right = st.columns([1,1], gap="large")
else:
    left = st.container()
    right = st.container()

# ------------------------
# Left: 訂單與外箱
# ------------------------
with left:
    section_title("1", "訂單與外箱設定")

    st.session_state.order_name = st.text_input("訂單名稱", value=st.session_state.order_name)

    # 手動箱
    st.subheader("外箱尺寸（cm）- 手動 Key in（可選擇是否參與裝箱）")
    c1, c2, c3 = st.columns(3)
    st.session_state.manual_box_dim["長"] = c1.number_input("長", min_value=0.0, value=float(st.session_state.manual_box_dim["長"]), step=0.5)
    st.session_state.manual_box_dim["寬"] = c2.number_input("寬", min_value=0.0, value=float(st.session_state.manual_box_dim["寬"]), step=0.5)
    st.session_state.manual_box_dim["高"] = c3.number_input("高", min_value=0.0, value=float(st.session_state.manual_box_dim["高"]), step=0.5)

    st.session_state.manual_box_dim["空箱重量"] = st.number_input("空箱重量 (kg)", min_value=0.0, value=float(st.session_state.manual_box_dim["空箱重量"]), step=0.05)

    c4, c5, c6 = st.columns([0.22, 0.18, 0.60])
    st.session_state.manual_box = c4.checkbox("使用手動箱", value=bool(st.session_state.manual_box))
    st.session_state.manual_box_dim["數量"] = c5.number_input("手動箱數量", min_value=0, value=int(st.session_state.manual_box_dim["數量"]), step=1)
    st.session_state.manual_box_dim["名稱"] = c6.text_input("手動箱命名", value=st.session_state.manual_box_dim["名稱"])

    st.divider()

    section_title("", "箱型管理（新增 / 修改 / 刪除 / 勾選使用）")
    st.caption("✅ 勾選「使用」才會參與裝箱；刪除用「勾選列 → 刪除勾選箱型」")

    # Box Editor form（穩定：不會跳回）
    with st.form("box_editor_form", clear_on_submit=False):
        box_df = coerce_box_df(st.session_state.box_df)

        edited_box = st.data_editor(
            box_df,
            use_container_width=True,
            num_rows="dynamic",
            hide_index=True,
            key="box_editor",
            column_config={
                "使用": st.column_config.CheckboxColumn("使用"),
                "名稱": st.column_config.TextColumn("名稱"),
                "長": st.column_config.NumberColumn("長", min_value=0.0, step=0.5),
                "寬": st.column_config.NumberColumn("寬", min_value=0.0, step=0.5),
                "高": st.column_config.NumberColumn("高", min_value=0.0, step=0.5),
                "數量": st.column_config.NumberColumn("數量", min_value=0, step=1),
                "空箱重量": st.column_config.NumberColumn("空箱重量", min_value=0.0, step=0.05),
            }
        )

        # 操作列：新增/刪除/儲存/載入（照你要的分級色）
        st.markdown('<div id="btnbar-ops">', unsafe_allow_html=True)
        b1, b2, b3, b4 = st.columns([1,1,1,1], gap="small")

        add_box = b1.form_submit_button("➕ 新增一列箱型")
        del_box = b2.form_submit_button("🗑️ 刪除勾選箱型")
        save_box_tpl = b3.form_submit_button("💾 儲存箱型模板")
        load_box_tpl = b4.form_submit_button("📥 載入箱型模板")
        st.markdown("</div>", unsafe_allow_html=True)

        apply_box = st.form_submit_button("✅ 套用變更（外箱表格）")

    # 這裡統一處理 form actions（避免按兩次）
    edited_box = coerce_box_df(pd.DataFrame(edited_box))

    if apply_box:
        st.session_state.box_df = edited_box
        st.toast("已套用外箱表格變更", icon="✅")
        st.rerun()

    if add_box:
        df = edited_box.copy()
        df.loc[len(df)] = {
            "使用": True, "名稱": "新箱型", "長": 0.0, "寬": 0.0, "高": 0.0, "數量": 1, "空箱重量": 0.0
        }
        st.session_state.box_df = coerce_box_df(df)
        st.toast("已新增一列箱型", icon="➕")
        st.rerun()

    if del_box:
        df = edited_box.copy()
        # 以「使用」勾選作為刪除（你說最左邊勾選刪除）
        kept = df[df["使用"] == False].copy()
        # 若全刪光，留一列避免空表造成困惑
        if len(kept) == 0:
            kept = coerce_box_df(pd.DataFrame([{
                "使用": False, "名稱": "（已清空）", "長": 0.0, "寬": 0.0, "高": 0.0, "數量": 0, "空箱重量": 0.0
            }]))
        st.session_state.box_df = coerce_box_df(kept)
        st.toast("已刪除勾選的箱型（使用=True 的列）", icon="🗑️")
        st.rerun()

    # Templates (Box)
    st.subheader("箱型模板（載入 / 儲存 / 刪除）")
    colA, colB = st.columns([1,1])
    box_tpl_names = storage_list_templates("box") if GAS_URL else []
    sel_box_tpl = colA.selectbox("選擇模板", ["(無)"] + box_tpl_names, index=0, key="sel_box_tpl")
    new_box_tpl_name = colB.text_input("另存為模板名稱", value="", placeholder="例如：常用箱型A")

    if save_box_tpl:
        if not new_box_tpl_name.strip():
            st.warning("請輸入模板名稱")
        else:
            with st.status("儲存中...", expanded=False):
                try:
                    storage_save_template("box", new_box_tpl_name.strip(), {"rows": st.session_state.box_df.to_dict("records")})
                    st.success("箱型模板已儲存")
                except Exception as e:
                    st.error(str(e))

    if load_box_tpl:
        if sel_box_tpl == "(無)":
            st.warning("請先選擇要載入的模板")
        else:
            with st.status("讀入中...", expanded=False):
                try:
                    data = storage_load_template("box", sel_box_tpl)
                    rows = data.get("rows", [])
                    st.session_state.box_df = coerce_box_df(pd.DataFrame(rows))
                    st.success("箱型模板已載入")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    # 刪除模板
    del_name = st.selectbox("要刪除的模板", ["(無)"] + box_tpl_names, index=0, key="del_box_tpl")
    if st.button("🗑️ 刪除箱型模板"):
        if del_name == "(無)":
            st.warning("請先選擇要刪除的模板")
        else:
            with st.status("刪除中...", expanded=False):
                try:
                    storage_delete_template("box", del_name)
                    st.success("已刪除模板")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))


# ------------------------
# Right: 商品清單
# ------------------------
with right:
    section_title("2", "商品清單（直接編輯表格）")
    st.caption("✅ 勾選「啟用」才會納入裝箱；刪除用「勾選列 → 刪除勾選商品列」")

    with st.form("prod_editor_form", clear_on_submit=False):
        prod_df = coerce_prod_df(st.session_state.prod_df)

        edited_prod = st.data_editor(
            prod_df,
            use_container_width=True,
            num_rows="dynamic",
            hide_index=True,
            key="prod_editor",
            column_config={
                "啟用": st.column_config.CheckboxColumn("啟用"),
                "商品名稱": st.column_config.TextColumn("商品名稱"),
                "長": st.column_config.NumberColumn("長", min_value=0.0, step=0.5),
                "寬": st.column_config.NumberColumn("寬", min_value=0.0, step=0.5),
                "高": st.column_config.NumberColumn("高", min_value=0.0, step=0.5),
                "重量(kg)": st.column_config.NumberColumn("重量(kg)", min_value=0.0, step=0.05),
                "數量": st.column_config.NumberColumn("數量", min_value=0, step=1),
            }
        )

        st.markdown('<div id="btnbar-ops">', unsafe_allow_html=True)
        p1, p2, p3, p4 = st.columns([1,1,1,1], gap="small")
        add_prod = p1.form_submit_button("➕ 新增一列商品")
        del_prod = p2.form_submit_button("🗑️ 刪除勾選商品列")
        save_prod_tpl = p3.form_submit_button("💾 儲存商品模板")
        load_prod_tpl = p4.form_submit_button("📥 載入商品模板")
        st.markdown("</div>", unsafe_allow_html=True)

        apply_prod = st.form_submit_button("✅ 套用變更（商品表格）")

    edited_prod = coerce_prod_df(pd.DataFrame(edited_prod))

    if apply_prod:
        st.session_state.prod_df = edited_prod
        st.toast("已套用商品表格變更", icon="✅")
        st.rerun()

    if add_prod:
        df = edited_prod.copy()
        df.loc[len(df)] = {
            "啟用": True, "商品名稱": "新商品", "長": 0.0, "寬": 0.0, "高": 0.0, "重量(kg)": 0.0, "數量": 1
        }
        st.session_state.prod_df = coerce_prod_df(df)
        st.toast("已新增一列商品", icon="➕")
        st.rerun()

    if del_prod:
        df = edited_prod.copy()
        kept = df[df["啟用"] == False].copy()
        if len(kept) == 0:
            kept = coerce_prod_df(pd.DataFrame([{
                "啟用": False, "商品名稱": "（已清空）", "長": 0.0, "寬": 0.0, "高": 0.0, "重量(kg)": 0.0, "數量": 0
            }]))
        st.session_state.prod_df = coerce_prod_df(kept)
        st.toast("已刪除勾選的商品列（啟用=True 的列）", icon="🗑️")
        st.rerun()

    # Templates (Product)
    st.subheader("商品模板（載入 / 儲存 / 刪除）")
    colA, colB = st.columns([1,1])
    prod_tpl_names = storage_list_templates("product") if GAS_URL else []
    sel_prod_tpl = colA.selectbox("選擇模板", ["(無)"] + prod_tpl_names, index=0, key="sel_prod_tpl")
    new_prod_tpl_name = colB.text_input("另存為模板名稱", value="", placeholder="例如：常用商品組合A")

    if save_prod_tpl:
        if not new_prod_tpl_name.strip():
            st.warning("請輸入模板名稱")
        else:
            with st.status("儲存中...", expanded=False):
                try:
                    storage_save_template("product", new_prod_tpl_name.strip(), {"rows": st.session_state.prod_df.to_dict("records")})
                    st.success("商品模板已儲存")
                except Exception as e:
                    st.error(str(e))

    if load_prod_tpl:
        if sel_prod_tpl == "(無)":
            st.warning("請先選擇要載入的模板")
        else:
            with st.status("讀入中...", expanded=False):
                try:
                    data = storage_load_template("product", sel_prod_tpl)
                    rows = data.get("rows", [])
                    st.session_state.prod_df = coerce_prod_df(pd.DataFrame(rows))
                    st.success("商品模板已載入")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    del_name = st.selectbox("要刪除的模板", ["(無)"] + prod_tpl_names, index=0, key="del_prod_tpl")
    if st.button("🗑️ 刪除商品模板"):
        if del_name == "(無)":
            st.warning("請先選擇要刪除的模板")
        else:
            with st.status("刪除中...", expanded=False):
                try:
                    storage_delete_template("product", del_name)
                    st.success("已刪除模板")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))


# =========================================================
# Packing result section
# =========================================================
st.divider()
section_title("3", "裝箱結果與模擬")

st.markdown('<div id="btnbar-run">', unsafe_allow_html=True)
run_btn = st.button("🚀 開始計算與 3D 模擬", use_container_width=True)
st.markdown("</div>", unsafe_allow_html=True)

if run_btn:
    with st.status("計算中...", expanded=False):
        try:
            items = build_items_from_prod_df(st.session_state.prod_df)
            bins = pick_bins_from_box_setting()

            if len(items) == 0:
                st.session_state.last_pack_result = {"error": "沒有啟用的商品（或數量為 0）"}
            elif len(bins) == 0:
                st.session_state.last_pack_result = {"error": "沒有可用箱型（請勾選使用或啟用手動箱）"}
            else:
                # 先挑出最好的單箱方案（如果你要多箱拆箱，我之後也可以再加）
                result = best_single_box_plan(items, bins)
                st.session_state.last_pack_result = result

            st.success("完成")
        except Exception as e:
            st.session_state.last_pack_result = {"error": str(e)}
            st.error(str(e))

# Show result
result = st.session_state.last_pack_result
if result:
    if result.get("error"):
        st.error("❌ " + result["error"])
    else:
        b = result["bin"]
        fitted = result["fitted"]
        unfitted = result["unfitted"]

        # 報告
        st.subheader("🧾 訂單裝箱報告")
        c1, c2 = st.columns([1, 2])
        with c1:
            st.write("**訂單名稱**：", st.session_state.order_name)
            st.write("**計算時間**：", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S（台灣時間）"))
            st.write("**使用外箱**：", f"{b['name']} ({b['L']}×{b['W']}×{b['H']}) × 1 箱")
            st.write("**內容淨重**：", f"{result['items_weight']:.2f} kg")
            st.write("**本次總重**：", f"{result['total_weight']:.2f} kg")
            st.write("**空間利用率**：", f"{result['utilization']:.2f}%")

        with c2:
            if len(unfitted) > 0:
                st.warning("⚠️ 注意：有部分商品裝不下！（可能是箱型庫存不足或尺寸不足）")
                st.write("未裝入：")
                st.write([it.name for it in unfitted])
            else:
                st.success("✅ 全部商品皆可裝入")

        # 下載報告（HTML）
        report = {
            "order_name": st.session_state.order_name,
            "time": datetime.datetime.now().isoformat(),
            "bin": b,
            "utilization": result["utilization"],
            "items_weight": result["items_weight"],
            "total_weight": result["total_weight"],
            "fitted": [{"name": it.name, "pos": it.position, "size": [it.width, it.height, it.depth], "weight": it.weight} for it in fitted],
            "unfitted": [it.name for it in unfitted],
        }
        html = f"""
        <html><meta charset="utf-8"><body style="font-family:Arial;line-height:1.6">
        <h2>3D裝箱報告</h2>
        <pre>{json.dumps(report, ensure_ascii=False, indent=2)}</pre>
        </body></html>
        """
        st.download_button(
            "⬇️ 下載完整裝箱報告（.html）",
            data=html.encode("utf-8"),
            file_name=f"{st.session_state.order_name}_packing_report.html",
            mime="text/html",
            use_container_width=True
        )

        # 3D
        fig = plot_packing_3d(result)
        st.plotly_chart(fig, use_container_width=True)
