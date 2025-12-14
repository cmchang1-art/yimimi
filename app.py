# =========================================================
# 3D 裝箱系統（Streamlit Community Cloud 穩定版）
# - Google Sheet 模板：載入 / 儲存 / 刪除
# - UI：左右 50/50 / 上下（垂直）切換（不重複渲染、不會 DuplicateElementId）
# - 表格：只保留一個勾選欄位「選取」（= 參與計算 + 可勾選刪除）
# - 數值：允許小數點（0.5 / 0.05 / 21.3 等）
# - 3D：py3dbp rotation_type=6 自動旋轉最佳擺法
# - 匯出：下載完整裝箱報告 .html，檔名：訂單名_YYYYMMDD_HHMM_共X件.html
# =========================================================

import json
import math
import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any, Optional

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# py3dbp
from py3dbp import Packer, Bin, Item

# requests（Streamlit Cloud 通常可用）
import requests


# -----------------------------
# 基本設定
# -----------------------------
st.set_page_config(page_title="3D 裝箱系統", page_icon="📦", layout="wide")

TITLE = "3D 裝箱系統"

DEFAULT_BOX_DF = pd.DataFrame(
    [
        {
            "選取": True,
            "名稱": "手動箱",
            "長": 35.0,
            "寬": 25.0,
            "高": 20.0,
            "數量": 1,
            "空箱重量": 0.50,
        }
    ]
)

DEFAULT_PROD_DF = pd.DataFrame(
    [
        {"選取": True, "商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.50, "數量": 5},
        {"選取": True, "商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5},
    ]
)

MUTED_COLORS = [
    "rgba(46, 105, 163, 0.85)",  # muted blue
    "rgba(55, 135, 90, 0.85)",   # muted green
    "rgba(184, 106, 60, 0.85)",  # muted orange
    "rgba(120, 120, 120, 0.85)", # muted gray
]

BOX_LINE_COLOR = "rgba(30,30,30,1.0)"


# -----------------------------
# Google Apps Script / Sheet API
# -----------------------------
def _secrets_get(key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(key, default))
    except Exception:
        return default


GAS_URL = _secrets_get("GAS_URL")
GAS_TOKEN = _secrets_get("GAS_TOKEN")
BOX_SHEET = _secrets_get("BOX_SHEET", "box_templates")
PROD_SHEET = _secrets_get("PROD_SHEET", "product_templates")

# 你 Apps Script 用的是：?token=...&action=...&sheet=...&name=...
# action: list/get/upsert/delete


def gas_request(action: str, sheet: str, name: str = "", payload_json: str = "") -> Dict[str, Any]:
    if not GAS_URL or not GAS_TOKEN:
        return {"ok": False, "error": "Missing GAS_URL / GAS_TOKEN in Secrets", "_status": 400}

    params = {
        "token": GAS_TOKEN,
        "action": action,
        "sheet": sheet,
    }
    if name:
        params["name"] = name

    try:
        if action == "upsert":
            resp = requests.post(
                GAS_URL,
                params=params,
                json={"payload_json": payload_json},
                timeout=20,
            )
        else:
            resp = requests.get(GAS_URL, params=params, timeout=20)

        # Apps Script 會回 JSON 文字
        data = resp.json()
        return data
    except Exception as e:
        return {"ok": False, "error": f"Request failed: {e}", "_status": 500}


@st.cache_data(ttl=15)
def gas_list_templates(sheet: str) -> List[str]:
    data = gas_request("list", sheet=sheet)
    if data.get("ok"):
        return list(data.get("items", []))
    return []


def gas_get_template(sheet: str, name: str) -> Optional[str]:
    data = gas_request("get", sheet=sheet, name=name)
    if data.get("ok"):
        return data.get("payload_json", "") or ""
    return None


def gas_upsert_template(sheet: str, name: str, payload_obj: Dict[str, Any]) -> Tuple[bool, str]:
    payload_json = json.dumps(payload_obj, ensure_ascii=False)
    data = gas_request("upsert", sheet=sheet, name=name, payload_json=payload_json)
    if data.get("ok"):
        # 清掉 cache，讓下拉立刻更新
        gas_list_templates.clear()
        return True, "已儲存"
    return False, str(data.get("error", "Unknown error"))


def gas_delete_template(sheet: str, name: str) -> Tuple[bool, str]:
    data = gas_request("delete", sheet=sheet, name=name)
    if data.get("ok"):
        gas_list_templates.clear()
        return True, "已刪除"
    return False, str(data.get("error", "Unknown error"))


# -----------------------------
# Session State / 初始化
# -----------------------------
def init_state():
    if "layout_mode" not in st.session_state:
        st.session_state.layout_mode = "左右 50% / 50%"

    if "order_name" not in st.session_state:
        st.session_state.order_name = f"訂單_{dt.datetime.now():%Y%m%d}"

    if "box_df" not in st.session_state:
        st.session_state.box_df = DEFAULT_BOX_DF.copy()

    if "prod_df" not in st.session_state:
        st.session_state.prod_df = DEFAULT_PROD_DF.copy()

    if "applied_box_template" not in st.session_state:
        st.session_state.applied_box_template = "未選擇"

    if "applied_prod_template" not in st.session_state:
        st.session_state.applied_prod_template = "未選擇"

    if "last_report_html" not in st.session_state:
        st.session_state.last_report_html = ""

    if "last_report_filename" not in st.session_state:
        st.session_state.last_report_filename = ""


init_state()


# -----------------------------
# 工具：表格欄位設定（小數點允許）
# -----------------------------
def number_col(label: str, step: float = 0.01, fmt: str = "%.2f"):
    return st.column_config.NumberColumn(label=label, step=step, format=fmt)


def int_col(label: str):
    return st.column_config.NumberColumn(label=label, step=1, format="%d")


def checkbox_col(label: str):
    return st.column_config.CheckboxColumn(label=label)


def make_editor_height(rows: int) -> int:
    # 8 行以上視覺舒服；每行約 35px，header + padding
    target = max(rows, 8)
    return int(35 * (target + 1) + 10)


# -----------------------------
# 3D / Packing
# -----------------------------
@dataclass
class PackedResult:
    ok: bool
    packer: Optional[Packer]
    bins: List[Bin]
    unfitted: List[Item]
    message: str


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return default
        return float(x)
    except Exception:
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return default
        return int(float(x))
    except Exception:
        return default


def build_packer_from_tables(box_df: pd.DataFrame, prod_df: pd.DataFrame) -> PackedResult:
    # 只用「選取=True 且 數量>0」的箱與商品
    box_df = box_df.copy()
    prod_df = prod_df.copy()

    # 清理
    for c in ["長", "寬", "高", "空箱重量"]:
        if c in box_df.columns:
            box_df[c] = box_df[c].apply(lambda v: _safe_float(v, 0.0))
    if "數量" in box_df.columns:
        box_df["數量"] = box_df["數量"].apply(lambda v: _safe_int(v, 0))

    for c in ["長", "寬", "高", "重量(kg)"]:
        if c in prod_df.columns:
            prod_df[c] = prod_df[c].apply(lambda v: _safe_float(v, 0.0))
    if "數量" in prod_df.columns:
        prod_df["數量"] = prod_df["數量"].apply(lambda v: _safe_int(v, 0))

    selected_boxes = box_df[(box_df["選取"] == True) & (box_df["數量"] > 0)]
    selected_items = prod_df[(prod_df["選取"] == True) & (prod_df["數量"] > 0)]

    if selected_boxes.empty:
        return PackedResult(False, None, [], [], "未選取任何外箱（請至少勾選 1 個外箱且數量>0）")
    if selected_items.empty:
        return PackedResult(False, None, [], [], "未選取任何商品（請至少勾選 1 個商品且數量>0）")

    # 建立 packer
    packer = Packer()

    # 加箱：依體積排序（小箱先放，避免浪費大箱）
    def box_volume(r):
        return r["長"] * r["寬"] * r["高"]

    selected_boxes = selected_boxes.sort_values(by=["長", "寬", "高"], ascending=[True, True, True])
    # 實際建立每一個箱實體（quantity 展開）
    bin_count = 0
    for _, r in selected_boxes.iterrows():
        name = str(r.get("名稱", "")).strip() or f"外箱{bin_count+1}"
        L, W, H = float(r["長"]), float(r["寬"]), float(r["高"])
        qty = int(r["數量"])
        empty_w = float(r.get("空箱重量", 0.0))
        if L <= 0 or W <= 0 or H <= 0 or qty <= 0:
            continue
        for _i in range(qty):
            bin_count += 1
            b = Bin(
                f"{name}#{bin_count}",
                L, W, H,
                max_weight=999999
            )
            # 讓後面報告可以用到空箱重量（py3dbp 原生沒有這欄，我們掛在物件上）
            setattr(b, "_empty_weight", empty_w)
            setattr(b, "_display_name", name)
            packer.add_bin(b)

    if not packer.bins:
        return PackedResult(False, None, [], [], "外箱資料有誤（尺寸/數量不可為 0）")

    # 加商品（quantity 展開），rotation_type=6 開啟 6 種旋轉
    item_count = 0
    for _, r in selected_items.iterrows():
        nm = str(r.get("商品名稱", "")).strip() or "未命名商品"
        L, W, H = float(r["長"]), float(r["寬"]), float(r["高"])
        wt = float(r["重量(kg)"])
        qty = int(r["數量"])
        if L <= 0 or W <= 0 or H <= 0 or qty <= 0:
            continue
        for _i in range(qty):
            item_count += 1
            it = Item(
                f"{nm}#{item_count}",
                L, W, H,
                wt
            )
            it.rotation_type = 6
            setattr(it, "_display_name", nm)
            packer.add_item(it)

    if not packer.items:
        return PackedResult(False, None, [], [], "商品資料有誤（尺寸/數量不可為 0）")

    try:
        # ⚠️ py3dbp 這裡不能帶 fix_point 之類的參數
        packer.pack()
        # packer.bins 內會包含 fitted_items/unfitted_items
        unfitted = list(getattr(packer, "unfitted_items", [])) or []
        return PackedResult(True, packer, list(packer.bins), unfitted, "OK")
    except Exception as e:
        return PackedResult(False, None, [], [], f"3D 計算失敗：{e}")


def _cuboid_mesh(x, y, z, dx, dy, dz, color: str, name: str):
    # 8 vertices
    X = [x, x+dx, x+dx, x,   x, x+dx, x+dx, x]
    Y = [y, y,    y+dy, y+dy, y, y,    y+dy, y+dy]
    Z = [z, z,    z,    z,   z+dz, z+dz, z+dz, z+dz]
    I = [0, 0, 0, 1, 1, 2, 4, 4, 5, 6, 3, 7]
    J = [1, 2, 3, 2, 5, 3, 5, 7, 6, 7, 7, 6]
    K = [2, 3, 1, 5, 6, 7, 7, 6, 4, 4, 0, 2]
    return go.Mesh3d(
        x=X, y=Y, z=Z,
        i=I, j=J, k=K,
        opacity=0.95,
        color=color,
        name=name,
        showscale=False,
        flatshading=True,
        hovertemplate=f"{name}<extra></extra>",
    )


def _wireframe_box(L, W, H):
    # 12 edges
    pts = [
        (0, 0, 0), (L, 0, 0), (L, W, 0), (0, W, 0),
        (0, 0, H), (L, 0, H), (L, W, H), (0, W, H),
    ]
    edges = [
        (0,1),(1,2),(2,3),(3,0),
        (4,5),(5,6),(6,7),(7,4),
        (0,4),(1,5),(2,6),(3,7)
    ]
    xs, ys, zs = [], [], []
    for a,b in edges:
        xs += [pts[a][0], pts[b][0], None]
        ys += [pts[a][1], pts[b][1], None]
        zs += [pts[a][2], pts[b][2], None]
    return go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="lines",
        line=dict(color=BOX_LINE_COLOR, width=6),
        name="外箱",
        hoverinfo="skip",
    )


def render_3d_plot(result: PackedResult) -> Tuple[Optional[go.Figure], Dict[str, Any]]:
    if not result.ok or not result.packer:
        return None, {}

    # 只顯示第一個有裝到東西的箱（避免畫面過亂）
    chosen_bin = None
    for b in result.bins:
        if getattr(b, "items", None):
            if len(b.items) > 0:
                chosen_bin = b
                break
    if chosen_bin is None:
        # 沒有任何 fitted items
        return None, {}

    L, W, H = float(chosen_bin.width), float(chosen_bin.height), float(chosen_bin.depth)
    # 注意：py3dbp 維度命名為 width/height/depth，但代表的是 x/y/z 尺寸（與你輸入長寬高一致即可）
    # 我們以 x=width, y=height, z=depth 來畫

    fig = go.Figure()
    fig.add_trace(_wireframe_box(L, W, H))

    # items
    items = list(chosen_bin.items)
    for idx, it in enumerate(items):
        # it.position: (x,y,z)
        px, py, pz = it.position
        dx, dy, dz = float(it.width), float(it.height), float(it.depth)
        disp = getattr(it, "_display_name", it.name)
        color = MUTED_COLORS[idx % len(MUTED_COLORS)]
        fig.add_trace(_cuboid_mesh(px, py, pz, dx, dy, dz, color, disp))

    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        scene=dict(
            xaxis_title="長",
            yaxis_title="寬",
            zaxis_title="高",
            aspectmode="data",
            xaxis=dict(showgrid=True),
            yaxis=dict(showgrid=True),
            zaxis=dict(showgrid=True),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        height=520,
    )

    # 統計
    total_item_weight = sum(float(i.weight) for i in items)
    empty_w = float(getattr(chosen_bin, "_empty_weight", 0.0))
    total_weight = total_item_weight + empty_w

    used_vol = sum(float(i.width) * float(i.height) * float(i.depth) for i in items)
    box_vol = L * W * H
    util = (used_vol / box_vol * 100.0) if box_vol > 0 else 0.0

    summary = {
        "box_name": getattr(chosen_bin, "_display_name", chosen_bin.name),
        "box_size": (L, W, H),
        "item_count": len(items),
        "unfitted_count": len(result.unfitted),
        "item_weight": total_item_weight,
        "empty_weight": empty_w,
        "total_weight": total_weight,
        "util_percent": util,
        "unfitted_names": [getattr(u, "_display_name", u.name) for u in result.unfitted],
    }
    return fig, summary


def build_html_report(order_name: str, summary: Dict[str, Any], fig: go.Figure) -> str:
    now = dt.datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    boxL, boxW, boxH = summary.get("box_size", (0, 0, 0))
    unf = summary.get("unfitted_names", [])
    unf_html = ""
    if unf:
        # 只列前 200 項避免過大
        items = "".join(f"<li>{st_html_escape(x)}</li>" for x in unf[:200])
        unf_html = f"""
        <div class="warn">
          <b>注意：</b> 有部分商品裝不下（可能是箱型庫存不足或尺寸不合）
          <ul>{items}</ul>
        </div>
        """

    fig_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>裝箱報告 - {st_html_escape(order_name)}</title>
<style>
  body{{font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans TC","Helvetica Neue",Arial,"PingFang TC","Microsoft JhengHei",sans-serif;
       margin:24px; color:#111;}}
  .card{{border:1px solid #e5e7eb; border-radius:12px; padding:16px 18px;}}
  .row{{display:flex; gap:16px; flex-wrap:wrap;}}
  .k{{color:#6b7280; width:110px; display:inline-block;}}
  .v{{font-weight:600;}}
  .warn{{margin-top:12px; border:1px solid #fecaca; background:#fff1f2; padding:12px 14px; border-radius:10px;}}
  hr{{border:none; border-top:1px solid #e5e7eb; margin:18px 0;}}
</style>
</head>
<body>
  <h2>📦 裝箱報告</h2>
  <div class="card">
    <div><span class="k">訂單名稱</span><span class="v">{st_html_escape(order_name)}</span></div>
    <div><span class="k">計算時間</span><span class="v">{ts}（台灣時間）</span></div>
    <div><span class="k">使用外箱</span><span class="v">{st_html_escape(summary.get("box_name",""))}（{boxL:.2f}×{boxW:.2f}×{boxH:.2f}）</span></div>
    <div><span class="k">內容淨重</span><span class="v">{summary.get("item_weight",0):.2f} kg</span></div>
    <div><span class="k">本次總重</span><span class="v" style="color:#b91c1c;">{summary.get("total_weight",0):.2f} kg</span></div>
    <div><span class="k">空間利用率</span><span class="v">{summary.get("util_percent",0):.2f}%</span></div>
    {unf_html}
  </div>
  <hr />
  <div class="card">
    {fig_html}
  </div>
</body>
</html>
"""
    return html


def st_html_escape(s: Any) -> str:
    t = str(s) if s is not None else ""
    return (
        t.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&#39;")
    )


# -----------------------------
# UI：模板區（箱 / 商品）
# -----------------------------
def render_template_block(kind: str):
    """
    kind: "box" or "prod"
    """
    is_box = (kind == "box")
    sheet = BOX_SHEET if is_box else PROD_SHEET
    title = "箱型模板（載入 / 儲存 / 刪除）" if is_box else "商品模板（載入 / 儲存 / 刪除）"
    applied_key = "applied_box_template" if is_box else "applied_prod_template"

    # 一次把所有相關元件放在一起（避免分散）
    st.subheader(title)

    templates = ["(無)"] + gas_list_templates(sheet)

    colA, colB, colC = st.columns([1.25, 1.0, 1.0], gap="large")
    with colA:
        sel = st.selectbox(
            "選擇模板",
            templates,
            index=0,
            key=f"{kind}_tpl_select",
        )
        new_name = st.text_input(
            "另存為模板名稱",
            placeholder="例如：常用A",
            key=f"{kind}_tpl_newname",
        )
        st.caption(f"目前套用：**{st.session_state[applied_key]}**")

    with colB:
        btn_apply = st.button("📥 載入模板", use_container_width=True, key=f"{kind}_btn_load")
        btn_save = st.button("💾 儲存模板", use_container_width=True, key=f"{kind}_btn_save")
        btn_clear = st.button("🧹 清除全部", use_container_width=True, key=f"{kind}_btn_clear")

    with colC:
        del_sel = st.selectbox(
            "要刪除的模板",
            templates,
            index=0,
            key=f"{kind}_tpl_delete_select",
        )
        btn_delete = st.button("🗑️ 刪除模板", use_container_width=True, key=f"{kind}_btn_delete")

    # --- 行為 ---
    if btn_apply:
        if sel == "(無)":
            st.warning("請先選擇要載入的模板")
        else:
            payload = gas_get_template(sheet, sel)
            if payload is None:
                st.error("載入失敗：找不到模板或雲端回傳異常")
            else:
                try:
                    obj = json.loads(payload)
                    df = pd.DataFrame(obj.get("rows", []))
                    # 確保必要欄位存在
                    if is_box:
                        df = normalize_box_df(df)
                        st.session_state.box_df = df
                    else:
                        df = normalize_prod_df(df)
                        st.session_state.prod_df = df
                    st.session_state[applied_key] = sel
                    st.success(f"已載入：{sel}")
                except Exception as e:
                    st.error(f"載入解析失敗：{e}")

    if btn_save:
        name = (new_name or "").strip()
        if not name:
            st.warning("請輸入「另存為模板名稱」")
        else:
            if is_box:
                payload_obj = {"rows": st.session_state.box_df.to_dict(orient="records")}
            else:
                payload_obj = {"rows": st.session_state.prod_df.to_dict(orient="records")}
            ok, msg = gas_upsert_template(sheet, name, payload_obj)
            if ok:
                st.session_state[applied_key] = name
                st.success(f"已儲存：{name}")
            else:
                st.error(f"儲存失敗：{msg}")

    if btn_delete:
        if del_sel == "(無)":
            st.warning("請先選擇要刪除的模板")
        else:
            ok, msg = gas_delete_template(sheet, del_sel)
            if ok:
                # 若刪的是目前套用，改回未選擇
                if st.session_state[applied_key] == del_sel:
                    st.session_state[applied_key] = "未選擇"
                st.success(f"已刪除：{del_sel}")
            else:
                st.error(f"刪除失敗：{msg}")

    if btn_clear:
        if is_box:
            st.session_state.box_df = DEFAULT_BOX_DF.copy()
            st.session_state[applied_key] = "未選擇"
        else:
            st.session_state.prod_df = DEFAULT_PROD_DF.copy()
            st.session_state[applied_key] = "未選擇"
        st.success("已清除並恢復預設")


def normalize_box_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["選取", "名稱", "長", "寬", "高", "數量", "空箱重量"]
    for c in cols:
        if c not in df.columns:
            # 缺欄就補
            df[c] = True if c == "選取" else (0.0 if c in ["長", "寬", "高", "空箱重量"] else (1 if c == "數量" else ""))
    df = df[cols].copy()
    # 型別整理
    df["選取"] = df["選取"].astype(bool)
    for c in ["長", "寬", "高", "空箱重量"]:
        df[c] = df[c].apply(lambda v: _safe_float(v, 0.0))
    df["數量"] = df["數量"].apply(lambda v: _safe_int(v, 0))
    df["名稱"] = df["名稱"].astype(str)
    return df


def normalize_prod_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["選取", "商品名稱", "長", "寬", "高", "重量(kg)", "數量"]
    for c in cols:
        if c not in df.columns:
            df[c] = True if c == "選取" else (0.0 if c in ["長", "寬", "高", "重量(kg)"] else (1 if c == "數量" else ""))
    df = df[cols].copy()
    df["選取"] = df["選取"].astype(bool)
    for c in ["長", "寬", "高", "重量(kg)"]:
        df[c] = df[c].apply(lambda v: _safe_float(v, 0.0))
    df["數量"] = df["數量"].apply(lambda v: _safe_int(v, 0))
    df["商品名稱"] = df["商品名稱"].astype(str)
    return df


# -----------------------------
# UI：表格區（只保留「選取」一個勾選）
# -----------------------------
def render_box_table():
    st.subheader("箱型表格（勾選=參與計算；勾選後可刪除）")

    df = normalize_box_df(st.session_state.box_df)

    edited = st.data_editor(
        df,
        key="box_editor",
        use_container_width=True,
        num_rows="dynamic",
        height=make_editor_height(len(df)),
        column_config={
            "選取": checkbox_col("選取"),
            "名稱": st.column_config.TextColumn("名稱"),
            "長": number_col("長", step=0.01, fmt="%.2f"),
            "寬": number_col("寬", step=0.01, fmt="%.2f"),
            "高": number_col("高", step=0.01, fmt="%.2f"),
            "數量": int_col("數量"),
            "空箱重量": number_col("空箱重量", step=0.01, fmt="%.2f"),
        },
    )

    st.session_state.box_df = normalize_box_df(edited)

    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        if st.button("🗑️ 刪除勾選", use_container_width=True, key="box_delete_selected"):
            d = st.session_state.box_df.copy()
            d = d[d["選取"] != True].reset_index(drop=True)
            if d.empty:
                d = DEFAULT_BOX_DF.copy()
            st.session_state.box_df = normalize_box_df(d)
            st.success("已刪除勾選外箱（若全部刪光，已恢復預設）")

    with col2:
        if st.button("✅ 套用變更（外箱表格）", use_container_width=True, key="box_apply_changes"):
            # 這顆主要是讓使用者「有按下去的明確感」，其實資料已即時更新
            st.success("外箱表格已套用（已即時更新）")


def render_prod_table():
    st.subheader("商品表格（數量>0 才會參與計算；勾選後可刪除）")

    df = normalize_prod_df(st.session_state.prod_df)

    edited = st.data_editor(
        df,
        key="prod_editor",
        use_container_width=True,
        num_rows="dynamic",
        height=make_editor_height(len(df)),
        column_config={
            "選取": checkbox_col("選取"),
            "商品名稱": st.column_config.TextColumn("商品名稱"),
            "長": number_col("長", step=0.01, fmt="%.2f"),
            "寬": number_col("寬", step=0.01, fmt="%.2f"),
            "高": number_col("高", step=0.01, fmt="%.2f"),
            "重量(kg)": number_col("重量(kg)", step=0.01, fmt="%.2f"),
            "數量": int_col("數量"),
        },
    )

    st.session_state.prod_df = normalize_prod_df(edited)

    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        if st.button("🗑️ 刪除勾選", use_container_width=True, key="prod_delete_selected"):
            d = st.session_state.prod_df.copy()
            d = d[d["選取"] != True].reset_index(drop=True)
            if d.empty:
                d = DEFAULT_PROD_DF.copy()
            st.session_state.prod_df = normalize_prod_df(d)
            st.success("已刪除勾選商品（若全部刪光，已恢復預設）")

    with col2:
        if st.button("✅ 套用變更（商品表格）", use_container_width=True, key="prod_apply_changes"):
            st.success("商品表格已套用（已即時更新）")


# -----------------------------
# UI：左 / 右區
# -----------------------------
def render_left():
    st.markdown("### 1. 訂單與外箱")
    st.text_input("訂單名稱", key="order_name")

    # 箱型模板 + 表格
    render_template_block("box")
    st.divider()
    render_box_table()


def render_right():
    st.markdown("### 2. 商品清單")
    # 商品模板 + 表格
    render_template_block("prod")
    st.divider()
    render_prod_table()


# -----------------------------
# UI：3D 結果與匯出
# -----------------------------
def render_result_area():
    st.markdown("### 3. 裝箱結果與模擬")

    # 計算按鈕（唯一）
    if st.button("🚀 開始計算與 3D 模擬", use_container_width=True, key="btn_run_3d"):
        with st.spinner("計算中..."):
            result = build_packer_from_tables(st.session_state.box_df, st.session_state.prod_df)

        if not result.ok:
            st.error(result.message)
            st.session_state.last_report_html = ""
            st.session_state.last_report_filename = ""
            return

        fig, summary = render_3d_plot(result)
        if fig is None:
            # 沒裝到任何東西
            st.warning("沒有任何商品被成功裝入外箱（請檢查尺寸或外箱是否足夠）")
            st.session_state.last_report_html = ""
            st.session_state.last_report_filename = ""
            return

        # 報告卡
        order = st.session_state.order_name
        now = dt.datetime.now()
        ts_name = now.strftime("%Y%m%d_%H%M")
        total_count = int(summary.get("item_count", 0))
        filename = f"{order}_{ts_name}_共{total_count}件.html"

        boxL, boxW, boxH = summary.get("box_size", (0, 0, 0))
        st.markdown("#### 訂單裝箱報告")
        c1, c2, c3 = st.columns([1.2, 1, 1], gap="large")
        with c1:
            st.write(f"**訂單名稱：** {order}")
            st.write(f"**使用外箱：** {summary.get('box_name','')}（{boxL:.2f}×{boxW:.2f}×{boxH:.2f}）")
            st.write(f"**內容淨重：** {summary.get('item_weight',0):.2f} kg")
            st.write(f"**本次總重：** **{summary.get('total_weight',0):.2f} kg**")
            st.write(f"**空間利用率：** {summary.get('util_percent',0):.2f}%")

        with c2:
            if summary.get("unfitted_count", 0) > 0:
                st.error("注意：有部分商品裝不下！")
                for nm in summary.get("unfitted_names", [])[:50]:
                    st.write(f"- {nm}")
            else:
                st.success("全部商品已成功裝入")

        with c3:
            # 先生成 HTML
            html = build_html_report(order, summary, fig)
            st.session_state.last_report_html = html
            st.session_state.last_report_filename = filename

            st.download_button(
                "⬇️ 下載完整裝箱報告（.html）",
                data=html.encode("utf-8"),
                file_name=filename,
                mime="text/html",
                use_container_width=True,
                key="btn_download_html",
            )

        st.plotly_chart(fig, use_container_width=True)

    # 若使用者尚未按計算，但之前算過，保留下載
    if st.session_state.last_report_html:
        st.download_button(
            "⬇️ 下載完整裝箱報告（.html）",
            data=st.session_state.last_report_html.encode("utf-8"),
            file_name=st.session_state.last_report_filename or "裝箱報告.html",
            mime="text/html",
            use_container_width=True,
            key="btn_download_html_cached",
        )


# -----------------------------
# 主畫面
# -----------------------------
st.markdown(f"## 📦 {TITLE}")

layout_mode = st.radio(
    "版面配置",
    ["左右 50% / 50%", "上下（垂直）"],
    key="layout_mode",
    horizontal=True,
)

# 用 layout 控制容器，不重複渲染（避免 DuplicateElementId）
if layout_mode == "左右 50% / 50%":
    colL, colR = st.columns(2, gap="large")
    with colL:
        render_left()
    with colR:
        render_right()
else:
    render_left()
    st.divider()
    render_right()

st.divider()
render_result_area()
