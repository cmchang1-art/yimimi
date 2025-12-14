# 3D 裝箱系統（Streamlit Community Cloud + Google Sheet 模板）
# - 單一「選取」欄：勾選=參與計算；也可用於刪除勾選列
# - 50/50 與 垂直 排版切換
# - Google Sheet（Apps Script WebApp）保存/載入/刪除模板
# - 3D 裝箱：多策略嘗試，改善旋轉/排序導致的誤判
# ============================================================

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

try:
    from py3dbp import Packer, Bin, Item
except Exception:
    Packer = Bin = Item = None  # type: ignore

import urllib.request
import urllib.parse

# ----------------------------
# 基本設定
# ----------------------------
st.set_page_config(page_title="3D裝箱系統", page_icon="📦", layout="wide")

DEFAULT_BOX_COLS = ["選取", "名稱", "長", "寬", "高", "數量", "空箱重量"]
DEFAULT_PROD_COLS = ["選取", "商品名稱", "長", "寬", "高", "重量(kg)", "數量"]

# Google Apps Script WebApp（從 Secrets 讀）
GAS_URL = st.secrets.get("GAS_URL", "").strip()
GAS_TOKEN = st.secrets.get("GAS_TOKEN", "").strip()
SHEET_BOX = st.secrets.get("SHEET_BOX", "box_templates")
SHEET_PROD = st.secrets.get("SHEET_PROD", "product_templates")

# 視覺：較專業、低飽和
PALETTE = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2", "#FF9DA6", "#9D755D"]

# ----------------------------
# CSS（按鈕、卡片、間距）
# ----------------------------
st.markdown(
    """
<style>
.block-container { padding-top: 1.5rem; }
h1,h2,h3 { letter-spacing: .2px; }
.section-title { font-size: 1.2rem; font-weight: 700; margin: .2rem 0 .6rem; }
.small-hint { color: #6b7280; font-size: .9rem; margin-top: .2rem; }
.card {
  border: 1px solid rgba(0,0,0,.08);
  border-radius: 14px;
  padding: 14px 14px 10px 14px;
  background: rgba(255,255,255,.7);
}
hr { margin: 1.2rem 0; }
</style>
""",
    unsafe_allow_html=True,
)

# ----------------------------
# 工具：型別與清洗
# ----------------------------
def _ensure_df(df: Any, cols: List[str]) -> pd.DataFrame:
    if isinstance(df, pd.DataFrame):
        out = df.copy()
    else:
        out = pd.DataFrame(df)
    for c in cols:
        if c not in out.columns:
            out[c] = "" if c != "選取" else False
    return out[cols]


def _to_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    s = str(x).strip().lower()
    return s in ("1", "true", "t", "yes", "y", "on", "✓", "勾選")


def _to_float(x: Any, default: float = 0.0) -> float:
    # ✅ 關鍵：把 Decimal / 任何型別都安全轉成 float，避免 decimal + float 直接爆掉
    if x is None:
        return default
    try:
        return float(x)
    except Exception:
        try:
            s = str(x).strip().replace(",", "")
            if s == "":
                return default
            return float(s)
        except Exception:
            return default


def norm_box_df(df: Any) -> pd.DataFrame:
    d = _ensure_df(df, DEFAULT_BOX_COLS)
    d["選取"] = d["選取"].apply(_to_bool)
    d["名稱"] = d["名稱"].astype(str).fillna("")
    for c in ["長", "寬", "高", "數量", "空箱重量"]:
        d[c] = d[c].apply(_to_float)
    d["數量"] = d["數量"].apply(lambda v: int(v) if v and v > 0 else 0)
    return d


def norm_prod_df(df: Any) -> pd.DataFrame:
    d = _ensure_df(df, DEFAULT_PROD_COLS)
    d["選取"] = d["選取"].apply(_to_bool)
    d["商品名稱"] = d["商品名稱"].astype(str).fillna("")
    for c in ["長", "寬", "高", "重量(kg)", "數量"]:
        d[c] = d[c].apply(_to_float)
    d["數量"] = d["數量"].apply(lambda v: int(v) if v and v > 0 else 0)
    return d


def default_box_df() -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "選取": True,
            "名稱": "手動箱",
            "長": 35.0,
            "寬": 25.0,
            "高": 20.0,
            "數量": 1,
            "空箱重量": 0.50,
        }],
        columns=DEFAULT_BOX_COLS,
    )


def default_prod_df() -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "選取": True,
            "商品名稱": "禮盒(米餅)",
            "長": 21.0,
            "寬": 14.0,
            "高": 8.5,
            "重量(kg)": 0.50,
            "數量": 5,
        }],
        columns=DEFAULT_PROD_COLS,
    )

# ----------------------------
# Google Sheet API（Apps Script WebApp）— 不亂改你的 GAS 規格
# ----------------------------
def _gas_enabled() -> bool:
    return bool(GAS_URL and GAS_TOKEN)


def gas_call(action: str, sheet: str, name: str = "", payload_json: str = "") -> Dict[str, Any]:
    if not _gas_enabled():
        return {"ok": False, "error": "Missing GAS_URL/GAS_TOKEN in Streamlit Secrets", "_status": 400}

    params = {"action": action, "sheet": sheet, "token": GAS_TOKEN}
    if name:
        params["name"] = name

    url = GAS_URL + "?" + urllib.parse.urlencode(params)

    try:
        if action in ("upsert",):
            data = json.dumps({"payload_json": payload_json}).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        else:
            with urllib.request.urlopen(url, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"{e}", "_status": 500}


@st.cache_data(ttl=30, show_spinner=False)
def gas_list_cached(sheet: str) -> List[str]:
    res = gas_call("list", sheet=sheet)
    if res.get("ok"):
        return list(res.get("items", []))
    return []


def gas_list(sheet: str) -> List[str]:
    return gas_list_cached(sheet)


def gas_get(sheet: str, name: str) -> Optional[str]:
    res = gas_call("get", sheet=sheet, name=name)
    if res.get("ok"):
        return res.get("payload_json", "") or ""
    return None


def gas_upsert(sheet: str, name: str, payload_json: str) -> Dict[str, Any]:
    return gas_call("upsert", sheet=sheet, name=name, payload_json=payload_json)


def gas_delete(sheet: str, name: str) -> Dict[str, Any]:
    return gas_call("delete", sheet=sheet, name=name)

# ----------------------------
# 3D 裝箱（多策略）
# ----------------------------
@dataclass
class PackedResult:
    fitted_items: List[Any]
    unfitted_items: List[Any]
    bin: Any
    utilization: float


def _volume(l: float, w: float, h: float) -> float:
    # data_editor 可能回傳 Decimal，統一轉 float 避免 Decimal/float 運算錯誤
    lf = _to_float(l); wf = _to_float(w); hf = _to_float(h)
    return max(lf, 0.0) * max(wf, 0.0) * max(hf, 0.0)


def try_pack_once(bin_dims: Tuple[float, float, float], items: List[Tuple[str, float, float, float, float]], order: str) -> PackedResult:
    if Packer is None:
        raise RuntimeError("py3dbp 未安裝或匯入失敗，請確認 requirements.txt")

    L, W, H = bin_dims
    packer = Packer()
    packer.add_bin(Bin("box", L, W, H, 999999))

    def key_volume(x): return _volume(x[1], x[2], x[3])
    def key_maxedge(x): return max(x[1], x[2], x[3])
    def key_minedge(x): return min(x[1], x[2], x[3])

    if order == "volume_desc":
        items2 = sorted(items, key=key_volume, reverse=True)
    elif order == "maxedge_desc":
        items2 = sorted(items, key=key_maxedge, reverse=True)
    elif order == "minedge_desc":
        items2 = sorted(items, key=key_minedge, reverse=True)
    else:
        items2 = items[:]

    for (name, l, w, h, weight) in items2:
        packer.add_item(Item(name, l, w, h, weight))

    packer.pack()
    b = packer.bins[0]
    fitted = b.items
    unfitted = b.unfitted_items

    fitted_vol = sum(_volume(i.width, i.height, i.depth) for i in fitted)
    util = fitted_vol / _volume(L, W, H) if _volume(L, W, H) > 0 else 0.0
    return PackedResult(fitted_items=fitted, unfitted_items=unfitted, bin=b, utilization=util)


def best_pack(bin_dims: Tuple[float, float, float], items: List[Tuple[str, float, float, float, float]]) -> PackedResult:
    candidates: List[PackedResult] = []
    for order in ["volume_desc", "maxedge_desc", "minedge_desc", "none"]:
        candidates.append(try_pack_once(bin_dims, items, order=order))
    candidates.sort(key=lambda r: (len(r.unfitted_items), -r.utilization))
    return candidates[0]


def make_plotly_3d(bin_dims: Tuple[float, float, float], packed: PackedResult) -> go.Figure:
    L, W, H = bin_dims
    fig = go.Figure()

    edges = [
        ((0, 0, 0), (L, 0, 0)), ((0, 0, 0), (0, W, 0)), ((0, 0, 0), (0, 0, H)),
        ((L, W, 0), (0, W, 0)), ((L, W, 0), (L, 0, 0)), ((L, W, 0), (L, W, H)),
        ((L, 0, H), (0, 0, H)), ((L, 0, H), (L, 0, 0)), ((L, 0, H), (L, W, H)),
        ((0, W, H), (0, 0, H)), ((0, W, H), (0, W, 0)), ((0, W, H), (L, W, H)),
    ]
    for (a, b) in edges:
        fig.add_trace(go.Scatter3d(
            x=[a[0], b[0]], y=[a[1], b[1]], z=[a[2], b[2]],
            mode="lines",
            line=dict(width=6, color="rgba(0,0,0,0.55)"),
            showlegend=False
        ))

    def add_box(x0, y0, z0, dx, dy, dz, color, name):
        x = [x0, x0+dx, x0+dx, x0, x0, x0+dx, x0+dx, x0]
        y = [y0, y0, y0+dy, y0+dy, y0, y0, y0+dy, y0+dy]
        z = [z0, z0, z0, z0, z0+dz, z0+dz, z0+dz, z0+dz]
        I = [0,0,0,1,1,2,4,4,5,5,6,7]
        J = [1,2,4,2,5,3,5,6,6,7,3,4]
        K = [2,3,5,5,6,0,6,7,7,4,4,5]
        fig.add_trace(go.Mesh3d(
            x=x, y=y, z=z, i=I, j=J, k=K,
            color=color, opacity=0.85,
            name=name, flatshading=True
        ))

    for idx, it in enumerate(packed.fitted_items):
        x0, y0, z0 = ( _to_float(it.position[0]), _to_float(it.position[1]), _to_float(it.position[2]) )
        add_box(x0, y0, z0, _to_float(it.width), _to_float(it.height), _to_float(it.depth), PALETTE[idx % len(PALETTE)], it.name)

    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        scene=dict(xaxis_title="x", yaxis_title="y", zaxis_title="z", aspectmode="data"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


def build_report_html(order_name: str, box_dims: Tuple[float,float,float], box_weight: float, prod_df: pd.DataFrame, packed: PackedResult, fig: go.Figure) -> Tuple[str, str]:
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M")
    ymd_hm = now.strftime("%Y%m%d_%H%M")

    total_qty = int(prod_df["數量"].sum())
    fname = f"{order_name}_{ymd_hm}_總數{total_qty}件.html"

    L,W,H = box_dims
    unfitted_names = [it.name for it in packed.unfitted_items]
    html_fig = fig.to_html(include_plotlyjs="cdn", full_html=False)

    rows = []
    for _, r in prod_df.iterrows():
        rows.append(f"<tr><td>{r['商品名稱']}</td><td>{r['長']}</td><td>{r['寬']}</td><td>{r['高']}</td><td>{r['重量(kg)']}</td><td>{r['數量']}</td></tr>")
    table_html = "<table border='1' cellpadding='6' cellspacing='0'><tr><th>商品</th><th>長</th><th>寬</th><th>高</th><th>重量</th><th>數量</th></tr>" + "".join(rows) + "</table>"

    warn_html = ""
    if unfitted_names:
        warn_html = "<div style='padding:10px;border:1px solid #fca5a5;background:#fee2e2;border-radius:10px;margin:10px 0;'>" \
                    "<b>注意：</b>有部分商品裝不下（可能是箱型庫存不足或尺寸不足）<br/>" + \
                    "<br/>".join([f"• {n}" for n in unfitted_names]) + "</div>"

    html = f"""
<!doctype html>
<html><head><meta charset="utf-8"/>
<title>裝箱報告 - {order_name}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,'Noto Sans TC',sans-serif;margin:24px;}}
h1{{margin:0 0 10px;}}
.meta{{color:#374151;margin-bottom:12px;}}
.card{{border:1px solid #e5e7eb;border-radius:14px;padding:14px;margin:12px 0;}}
</style>
</head>
<body>
<h1>訂單裝箱報告</h1>
<div class="meta">訂單：<b>{order_name}</b>｜生成時間：{ts}</div>

<div class="card">
<b>外箱</b><br/>
尺寸：{L} × {W} × {H} cm<br/>
空箱重量：{box_weight} kg<br/>
空間利用率：{packed.utilization*100:.2f}%
</div>

{warn_html}

<div class="card">
<b>商品清單</b><br/>
{table_html}
</div>

<div class="card">
<b>3D 模擬</b><br/>
{html_fig}
</div>

</body></html>
"""
    return fname, html

# ----------------------------
# Session init
# ----------------------------
if "box_df" not in st.session_state:
    st.session_state.box_df = default_box_df()
if "prod_df" not in st.session_state:
    st.session_state.prod_df = default_prod_df()

if "box_current_tpl" not in st.session_state:
    st.session_state.box_current_tpl = ""
if "prod_current_tpl" not in st.session_state:
    st.session_state.prod_current_tpl = ""

if "layout_mode" not in st.session_state:
    st.session_state.layout_mode = "左右 50% / 50%"

# ----------------------------
# Header
# ----------------------------
st.markdown("## 📦 3D裝箱系統")

layout_mode = st.radio(
    "版面配置",
    ["左右 50% / 50%", "上下（垂直）"],
    horizontal=True,
    key="layout_mode_radio",
    index=0 if st.session_state.layout_mode == "左右 50% / 50%" else 1,
)
st.session_state.layout_mode = layout_mode

# ----------------------------
# UI：模板控制（按你要求「不要亂拆」→ 三欄固定排版）
# ----------------------------
def template_block(prefix: str, title: str, sheet: str, current_name_key: str, table_kind: str) -> None:
    st.markdown(f"<div class='section-title'>{title}（載入 / 儲存 / 刪除）</div>", unsafe_allow_html=True)

    if not _gas_enabled():
        st.info("尚未設定 Streamlit Secrets（GAS_URL / GAS_TOKEN）。模板功能會停用。")
        return

    names = ["(無)"] + gas_list(sheet)

    c1, c2, c3 = st.columns([1.2, 1.2, 1.2], gap="small")

    with c1:
        sel = st.selectbox("選擇模板", names, key=f"{prefix}_tpl_sel")
        save_name = st.text_input("另存為模板名稱", key=f"{prefix}_tpl_saveas", placeholder="例如：常用A")
        cur = st.session_state.get(current_name_key, "")
        st.caption(f"目前套用： {cur or '未選擇'}")

    with c2:
        st.write("")
        st.write("")
        load_btn = st.button("⬇️ 載入模板", key=f"{prefix}_btn_load", use_container_width=True)
        save_btn = st.button("💾 儲存模板", key=f"{prefix}_btn_save", use_container_width=True)
        overwrite_same = st.checkbox("覆蓋同名", value=False, key=f"{prefix}_overwrite")

    with c3:
        del_sel = st.selectbox("要刪除的模板", names, key=f"{prefix}_tpl_del")
        del_btn = st.button("🗑️ 刪除模板", key=f"{prefix}_btn_del", use_container_width=True)

    if load_btn:
        if sel and sel != "(無)":
            payload = gas_get(sheet, sel)
            if payload is None:
                st.error("載入失敗：找不到模板或雲端連線問題")
            else:
                try:
                    data = json.loads(payload) if payload else {}
                    if table_kind == "box":
                        st.session_state.box_df = norm_box_df(data.get("rows", []))
                    else:
                        st.session_state.prod_df = norm_prod_df(data.get("rows", []))
                    st.session_state[current_name_key] = sel
                    st.success(f"已載入：{sel}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"載入解析失敗：{e}")
        else:
            st.warning("請先選擇要載入的模板")

    if save_btn:
        name = (save_name or "").strip()
        if not name:
            st.warning("請輸入要儲存的模板名稱")
        else:
            # 同名檢查（避免不小心覆蓋）
            existing = set(tpl_items)
            if name in existing and not overwrite_same:
                st.error("同名模板已存在，請更換名稱或勾選「覆蓋同名」")
            else:
                rows = (st.session_state.box_df if table_kind == "box" else st.session_state.prod_df).to_dict(orient="records")
            payload = json.dumps({"rows": rows}, ensure_ascii=False)
            res = gas_upsert(sheet, name, payload)
            if res.get("ok"):
                st.session_state[current_name_key] = name
                st.success(f"已儲存：{name}")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(f"儲存失敗：{res.get('error','請確認雲端連線 / 權限')}")

    if del_btn:
        if del_sel and del_sel != "(無)":
            res = gas_delete(sheet, del_sel)
            if res.get("ok"):
                st.success(f"已刪除：{del_sel}")
                if st.session_state.get(current_name_key) == del_sel:
                    st.session_state[current_name_key] = ""
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(f"刪除失敗：{res.get('error','請確認雲端連線 / 權限')}")
        else:
            st.warning("請先選擇要刪除的模板")
