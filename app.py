# -*- coding: utf-8 -*-
"""3D裝箱系統（最穩定版｜Streamlit Community Cloud + Google Sheet）

你目前用的是 Streamlit Community Cloud（官方雲端託管）。
本版重點：
- UI：恢復你原本「左右50/50」與「上下(垂直)」切換的版面呈現（如你圖1那種）
- 表格：只保留一個勾選欄「選取」（同時代表：參與裝箱 + 供刪除所選），不再出現多個勾選造成混淆
- 小數點：長寬高、重量、空箱重量都可輸入 0.5 / 0.05 這類小數
- 表格高度：至少顯示約 8 行
- Google Sheet：不亂改你的 Apps Script / Sheet；用你提供的 action=list/get/upsert/delete 介面
- 3D：py3dbp 旋轉判斷（不傳 fix_point 以避免報錯），並做多策略排序/嘗試，提升放置成功率
- 匯出：恢復「下載完整裝箱報告(.html)」，檔名：{訂單名}_{YYYYMMDD}_{HHMM}_總數{X}件.html
- 避免 StreamlitDuplicateElementId：所有按鈕/元件都加上唯一 key

需要設定 Streamlit Secrets：
- GAS_URL   : 你的 Apps Script Web App exec URL
- GAS_TOKEN : 你的 TOKEN
- GAS_SHEET_BOX   : (可選) 外箱模板所在的 Sheet 名稱（預設 box_state）
- GAS_SHEET_PRODUCT: (可選) 商品模板所在的 Sheet 名稱（預設 product_state）

注意：
- Apps Script 必須是「部署為 Web App」並允許匿名存取（或至少讓 Streamlit 能呼叫），
  但你已有 token 驗證，所以安全性以 token 為準。
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# -----------------------------
# 基本設定
# -----------------------------
APP_TITLE = "3D裝箱系統"

DEFAULT_BOX_SHEET = "box_state"      # 你已經確認 list 有看到 box_state
DEFAULT_PROD_SHEET = "product_state" # 若你實際 sheet 名稱不同，去 Secrets 改

# DataEditor 欄位
BOX_COLS = ["選取", "名稱", "長", "寬", "高", "數量", "空箱重量"]
PROD_COLS = ["選取", "商品名稱", "長", "寬", "高", "重量(kg)", "數量"]

# -----------------------------
# CSS（按鈕與版面一致、專業配色）
# -----------------------------
CSS = """
<style>
main .block-container { padding-top: 1.2rem; padding-bottom: 2.2rem; }
hr { margin: 1rem 0 1.25rem 0; }

/* 卡片感 */
.card { border: 1px solid #e5e7eb; border-radius: 14px; padding: 14px 14px 6px 14px; background: #fff; }
.card h3 { margin: 0 0 .5rem 0; }

/* 表格 */
div[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; }

/* 按鈕配色（柔和、專業、不要太花） */
.btn-green div[data-testid="stButton"] button, .btn-green div[data-testid="stFormSubmitButton"] button{
  background: #E8F5E9 !important; color: #1B5E20 !important; border: 1px solid #C8E6C9 !important;
}
.btn-blue div[data-testid="stButton"] button, .btn-blue div[data-testid="stFormSubmitButton"] button{
  background: #E3F2FD !important; color: #0D47A1 !important; border: 1px solid #BBDEFB !important;
}
.btn-red div[data-testid="stButton"] button, .btn-red div[data-testid="stFormSubmitButton"] button{
  background: #FFEBEE !important; color: #B71C1C !important; border: 1px solid #FFCDD2 !important;
}
.btn-gray div[data-testid="stButton"] button, .btn-gray div[data-testid="stFormSubmitButton"] button{
  background: #F5F5F5 !important; color: #263238 !important; border: 1px solid #E0E0E0 !important;
}

/* 統一按鈕樣式 */
div[data-testid="stButton"] button, div[data-testid="stFormSubmitButton"] button{
  border-radius: 10px !important; font-weight: 700 !important;
}

.small-hint { color: #6b7280; font-size: .9rem; }
.badge { display:inline-block; padding:.15rem .55rem; border-radius: 999px; border:1px solid #e5e7eb; background:#fafafa; font-size:.85rem; }
</style>
"""

# -----------------------------
# Google Sheet / Apps Script 儲存
# -----------------------------
@dataclass
class CloudConfig:
    url: str
    token: str
    sheet_box: str
    sheet_product: str

class CloudStore:
    """對應你提供的 Apps Script：action=list/get/upsert/delete + 參數 sheet/name/token"""

    def __init__(self, cfg: CloudConfig):
        self.cfg = cfg

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        import requests
        params = dict(params)
        params["token"] = self.cfg.token
        r = requests.get(self.cfg.url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def _post(self, params: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
        import requests
        params = dict(params)
        params["token"] = self.cfg.token
        r = requests.post(self.cfg.url, params=params, json=body, timeout=25)
        r.raise_for_status()
        return r.json()

    def list_names(self, sheet: str) -> List[str]:
        res = self._get({"action": "list", "sheet": sheet})
        if res.get("ok") and isinstance(res.get("items"), list):
            return [str(x) for x in res["items"]]
        return []

    def get_payload(self, sheet: str, name: str) -> Optional[str]:
        res = self._get({"action": "get", "sheet": sheet, "name": name})
        if res.get("ok"):
            return str(res.get("payload_json") or "")
        return None

    def upsert_payload(self, sheet: str, name: str, payload_json: str) -> Tuple[bool, str]:
        res = self._post({"action": "upsert", "sheet": sheet, "name": name}, {"payload_json": payload_json})
        if res.get("ok"):
            return True, "已儲存"
        return False, str(res.get("error") or "儲存失敗")

    def delete_name(self, sheet: str, name: str) -> Tuple[bool, str]:
        res = self._get({"action": "delete", "sheet": sheet, "name": name})
        if res.get("ok"):
            return True, "已刪除"
        return False, str(res.get("error") or "刪除失敗")

# -----------------------------
# py3dbp（裝箱）
# -----------------------------
try:
    from py3dbp import Packer, Bin, Item
except Exception:
    Packer = Bin = Item = None


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


def _normalize_df(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    # 確保欄位齊全
    for c in cols:
        if c not in df.columns:
            df[c] = "" if c not in ("選取",) else False
    df = df[cols].copy()

    # dtype
    if "選取" in df.columns:
        df["選取"] = df["選取"].fillna(False).astype(bool)

    # 文字欄
    for c in ("名稱", "商品名稱"):
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str)

    # 數字欄：保持 float，才能輸入 0.5
    for c in ("長", "寬", "高", "重量(kg)", "數量", "空箱重量"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
            if c == "數量":
                df[c] = df[c].fillna(0).astype(int)
            else:
                df[c] = df[c].fillna(0.0).astype(float)

    return df


def _expand_items(prod_df: pd.DataFrame) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for _, r in prod_df.iterrows():
        if not bool(r.get("選取", False)):
            continue
        qty = _safe_int(r.get("數量"), 0)
        if qty <= 0:
            continue
        name = str(r.get("商品名稱") or "商品").strip() or "商品"
        L = _safe_float(r.get("長"), 0)
        W = _safe_float(r.get("寬"), 0)
        H = _safe_float(r.get("高"), 0)
        wt = _safe_float(r.get("重量(kg)"), 0)
        if min(L, W, H) <= 0:
            continue
        for i in range(qty):
            items.append({"name": name, "L": L, "W": W, "H": H, "weight": wt, "idx": i + 1})
    return items


def _collect_bins(box_df: pd.DataFrame) -> List[Dict[str, Any]]:
    bins: List[Dict[str, Any]] = []
    for _, r in box_df.iterrows():
        if not bool(r.get("選取", False)):
            continue
        qty = _safe_int(r.get("數量"), 0)
        if qty <= 0:
            continue
        name = str(r.get("名稱") or "外箱").strip() or "外箱"
        L = _safe_float(r.get("長"), 0)
        W = _safe_float(r.get("寬"), 0)
        H = _safe_float(r.get("高"), 0)
        empty_w = _safe_float(r.get("空箱重量"), 0)
        if min(L, W, H) <= 0:
            continue
        for i in range(qty):
            bins.append({"name": name, "L": L, "W": W, "H": H, "empty_w": empty_w, "idx": i + 1})
    return bins


def _pack_with_py3dbp(one_bin: Dict[str, Any], items: List[Dict[str, Any]], strategy: str) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """回傳：已放入的 items（py3dbp Item objects）、未放入的 items(dict)"""
    if Packer is None:
        raise RuntimeError("py3dbp 未安裝（requirements.txt 請加入 py3dbp）")

    # 多策略：改變 item 排序，提升放入率（py3dbp 自己會旋轉，但排序影響結果很大）
    def sort_key(it: Dict[str, Any]):
        L, W, H = it["L"], it["W"], it["H"]
        vol = L * W * H
        longest = max(L, W, H)
        base_area = sorted([L, W, H])[1] * sorted([L, W, H])[2]
        if strategy == "vol_desc":
            return (-vol, -longest, -base_area)
        if strategy == "long_desc":
            return (-longest, -vol, -base_area)
        if strategy == "base_desc":
            return (-base_area, -vol, -longest)
        return (-vol,)

    items_sorted = sorted(items, key=sort_key)

    packer = Packer()
    b = Bin(one_bin["name"], one_bin["L"], one_bin["W"], one_bin["H"], 999999)
    packer.add_bin(b)

    for k, it in enumerate(items_sorted):
        # 這裡不限制 rotation_type，讓 py3dbp 自己做最有利旋轉
        item = Item(f"{it['name']}#{k+1}", it["L"], it["W"], it["H"], it["weight"])
        packer.add_item(item)

    # 相容 pack() 參數：不同版本可能不接受某些 kwargs
    import inspect

    sig = inspect.signature(packer.pack)
    kwargs: Dict[str, Any] = {}
    if "bigger_first" in sig.parameters:
        kwargs["bigger_first"] = True
    if "distribute_items" in sig.parameters:
        kwargs["distribute_items"] = False
    if "number_of_decimals" in sig.parameters:
        kwargs["number_of_decimals"] = 2

    packer.pack(**kwargs)

    placed = list(packer.bins[0].items) if packer.bins else []

    # 建立未放入清單（依 name#序號 比對）
    placed_names = set(getattr(x, "name", "") for x in placed)
    unfit: List[Dict[str, Any]] = []
    for k, it in enumerate(items_sorted):
        nm = f"{it['name']}#{k+1}"
        if nm not in placed_names:
            unfit.append(it)
    return placed, unfit


def pack_order(box_df: pd.DataFrame, prod_df: pd.DataFrame) -> Dict[str, Any]:
    """最穩定的「單外箱」裝箱：目前 UI 是手動箱（通常只有一種箱），
    但仍支援多箱：會逐箱嘗試把剩餘商品放進去。
    """
    bins = _collect_bins(box_df)
    items = _expand_items(prod_df)

    if not bins:
        return {"ok": False, "error": "請至少勾選 1 個外箱（且數量>0）"}
    if not items:
        return {"ok": False, "error": "請至少勾選 1 個商品（且數量>0）"}

    # 逐箱裝入
    remaining = items
    packed_bins: List[Dict[str, Any]] = []

    strategies = ["vol_desc", "base_desc", "long_desc"]

    for b in bins:
        if not remaining:
            break

        best = None
        best_unfit = None
        best_strategy = None

        # 同一個箱，嘗試不同排序策略，挑「未放入最少」的
        for s in strategies:
            placed, unfit = _pack_with_py3dbp(b, remaining, s)
            if best is None or len(unfit) < len(best_unfit):
                best = placed
                best_unfit = unfit
                best_strategy = s
            if len(unfit) == 0:
                break

        packed_bins.append({
            "box": b,
            "strategy": best_strategy,
            "placed": best,
        })

        remaining = best_unfit or []

    return {
        "ok": True,
        "packed_bins": packed_bins,
        "remaining": remaining,
        "total_items": len(items),
    }

# -----------------------------
# 3D Plotly
# -----------------------------

def _cuboid_vertices(x, y, z, dx, dy, dz):
    # 8 points
    return [
        (x, y, z),
        (x + dx, y, z),
        (x + dx, y + dy, z),
        (x, y + dy, z),
        (x, y, z + dz),
        (x + dx, y, z + dz),
        (x + dx, y + dy, z + dz),
        (x, y + dy, z + dz),
    ]


def _add_box_wireframe(fig: go.Figure, L: float, W: float, H: float):
    # 黑色框線
    corners = _cuboid_vertices(0, 0, 0, L, W, H)
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7)
    ]
    for a, b in edges:
        xa, ya, za = corners[a]
        xb, yb, zb = corners[b]
        fig.add_trace(go.Scatter3d(
            x=[xa, xb], y=[ya, yb], z=[za, zb],
            mode="lines",
            line=dict(width=6, color="#111827"),
            showlegend=False,
            hoverinfo="skip",
        ))


def _add_item_mesh(fig: go.Figure, x, y, z, dx, dy, dz, label: str, color: str):
    v = _cuboid_vertices(x, y, z, dx, dy, dz)
    # cube faces via Mesh3d triangles
    # vertices indices
    I = [0, 0, 0, 1, 1, 2, 4, 4, 5, 6, 3, 2]
    J = [1, 2, 3, 2, 5, 3, 5, 7, 6, 7, 7, 6]
    K = [2, 3, 1, 5, 6, 7, 6, 6, 7, 4, 0, 4]

    fig.add_trace(go.Mesh3d(
        x=[p[0] for p in v],
        y=[p[1] for p in v],
        z=[p[2] for p in v],
        i=I, j=J, k=K,
        opacity=0.78,
        color=color,
        name=label,
        hovertemplate=f"{label}<br>x:%{{x:.1f}} y:%{{y:.1f}} z:%{{z:.1f}}<extra></extra>",
    ))


def build_3d_figure(packed_bins: List[Dict[str, Any]]) -> Optional[go.Figure]:
    if not packed_bins:
        return None

    # 只顯示第一箱（你原本 UI 也是單一視覺），需要多箱再擴充
    b = packed_bins[0]["box"]
    placed = packed_bins[0]["placed"]

    L, W, H = b["L"], b["W"], b["H"]

    fig = go.Figure()
    _add_box_wireframe(fig, L, W, H)

    # 專業、不要太花：用固定兩三個色系循環（深一點，清楚）
    palette = ["#D97706", "#0F766E", "#1D4ED8", "#7C3AED", "#B91C1C", "#374151"]

    for idx, it in enumerate(placed):
        # py3dbp item 可能有 position/width/height/depth
        try:
            x, y, z = it.position
        except Exception:
            x, y, z = (0, 0, 0)

        dx = float(getattr(it, "width", 0) or 0)
        dy = float(getattr(it, "height", 0) or 0)
        dz = float(getattr(it, "depth", 0) or 0)

        color = palette[idx % len(palette)]
        _add_item_mesh(fig, x, y, z, dx, dy, dz, getattr(it, "name", f"item{idx+1}"), color)

    fig.update_layout(
        scene=dict(
            xaxis_title="x",
            yaxis_title="y",
            zaxis_title="z",
            xaxis=dict(range=[0, L], backgroundcolor="#ffffff", gridcolor="#e5e7eb"),
            yaxis=dict(range=[0, W], backgroundcolor="#ffffff", gridcolor="#e5e7eb"),
            zaxis=dict(range=[0, H], backgroundcolor="#ffffff", gridcolor="#e5e7eb"),
            aspectmode="data",
        ),
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h"),
        height=520,
    )
    return fig

# -----------------------------
# 匯出 HTML 報告
# -----------------------------

def make_report_html(order_name: str, result: Dict[str, Any], fig: Optional[go.Figure]) -> Tuple[str, str]:
    now = dt.datetime.now()
    ymd = now.strftime("%Y%m%d")
    hm = now.strftime("%H%M")
    total = int(result.get("total_items", 0))
    safe_order = (order_name or "訂單").strip().replace(" ", "_")
    filename = f"{safe_order}_{ymd}_{hm}_總數{total}件.html"

    # 基本摘要
    packed_bins = result.get("packed_bins", [])
    remaining = result.get("remaining", [])

    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Plotly fig
    plot_html = ""
    if fig is not None:
        import plotly.io as pio
        plot_html = pio.to_html(fig, include_plotlyjs="cdn", full_html=False)

    rem_lines = "".join([f"<li>{esc(r['name'])} (L{r['L']}, W{r['W']}, H{r['H']})</li>" for r in remaining])

    box_desc = ""
    if packed_bins:
        b = packed_bins[0]["box"]
        box_desc = f"{esc(b['name'])} ({b['L']}×{b['W']}×{b['H']})"

    html = f"""<!doctype html>
<html lang='zh-Hant'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{esc(order_name)} 裝箱報告</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans TC', Arial, sans-serif; margin: 24px; color:#111827; }}
  .card {{ border:1px solid #e5e7eb; border-radius:14px; padding:14px 16px; margin-bottom:16px; }}
  .muted {{ color:#6b7280; }}
  .bad {{ background:#FEF2F2; border-color:#FECACA; }}
  h1 {{ margin:0 0 8px 0; }}
  ul {{ margin: 6px 0 0 18px; }}
</style>
</head>
<body>
  <h1>訂單裝箱報告</h1>
  <div class='card'>
    <div><b>訂單名稱：</b>{esc(order_name)}</div>
    <div><b>產生時間：</b>{now.strftime('%Y-%m-%d %H:%M:%S')}</div>
    <div><b>外箱：</b>{box_desc}</div>
    <div><b>商品總件數：</b>{total}</div>
    <div class='muted'><b>未裝入：</b>{len(remaining)} 件</div>
  </div>

  {'<div class="card bad"><b>注意：</b>部分商品裝不下（可能是箱型不足或尺寸不合）<ul>'+rem_lines+'</ul></div>' if remaining else ''}

  <div class='card'>
    <h3 style='margin:0 0 10px 0;'>3D 裝箱視覺</h3>
    {plot_html}
  </div>
</body>
</html>"""

    return filename, html

# -----------------------------
# UI Helpers
# -----------------------------

def number_col(label: str, key: str, step: float = 0.01, fmt: str = "%.2f"):
    return st.column_config.NumberColumn(label, step=step, format=fmt)


def checkbox_col(label: str):
    return st.column_config.CheckboxColumn(label)


def _df_to_payload(df: pd.DataFrame) -> str:
    # 只存必要欄位，避免 dtype 問題
    return df.to_json(orient="records", force_ascii=False)


def _payload_to_df(payload: str, kind: str) -> pd.DataFrame:
    if not payload:
        return pd.DataFrame(columns=BOX_COLS if kind == "box" else PROD_COLS)
    try:
        data = json.loads(payload)
        df = pd.DataFrame(data)
    except Exception:
        df = pd.DataFrame(columns=BOX_COLS if kind == "box" else PROD_COLS)

    if kind == "box":
        return _normalize_df(df, BOX_COLS)
    return _normalize_df(df, PROD_COLS)


def _ensure_session_defaults():
    if "layout_mode" not in st.session_state:
        st.session_state.layout_mode = "左右"  # 或 "上下"
    if "order_name" not in st.session_state:
        st.session_state.order_name = f"訂單_{dt.datetime.now().strftime('%Y%m%d')}"

    if "box_df" not in st.session_state:
        st.session_state.box_df = _normalize_df(pd.DataFrame([{
            "選取": True,
            "名稱": "手動箱",
            "長": 35.0,
            "寬": 25.0,
            "高": 20.0,
            "數量": 1,
            "空箱重量": 0.5,
        }]), BOX_COLS)

    if "prod_df" not in st.session_state:
        st.session_state.prod_df = _normalize_df(pd.DataFrame([{
            "選取": True,
            "商品名稱": "禮盒(米餅)",
            "長": 21.0,
            "寬": 14.0,
            "高": 8.5,
            "重量(kg)": 0.5,
            "數量": 5,
        }, {
            "選取": True,
            "商品名稱": "紙袋",
            "長": 28.0,
            "寬": 24.3,
            "高": 0.3,
            "重量(kg)": 0.05,
            "數量": 5,
        }]), PROD_COLS)

    if "current_box_tpl" not in st.session_state:
        st.session_state.current_box_tpl = ""
    if "current_prod_tpl" not in st.session_state:
        st.session_state.current_prod_tpl = ""

    if "last_result" not in st.session_state:
        st.session_state.last_result = None
    if "last_fig" not in st.session_state:
        st.session_state.last_fig = None


def _clear_boxes():
    st.session_state.box_df = _normalize_df(pd.DataFrame(columns=BOX_COLS), BOX_COLS)
    # 預留 8 行可編輯
    st.session_state.box_df = pd.concat([st.session_state.box_df, pd.DataFrame([{
        "選取": False, "名稱": "", "長": 0.0, "寬": 0.0, "高": 0.0, "數量": 0, "空箱重量": 0.0
    } for _ in range(8)])], ignore_index=True)


def _clear_products():
    st.session_state.prod_df = _normalize_df(pd.DataFrame(columns=PROD_COLS), PROD_COLS)
    st.session_state.prod_df = pd.concat([st.session_state.prod_df, pd.DataFrame([{
        "選取": False, "商品名稱": "", "長": 0.0, "寬": 0.0, "高": 0.0, "重量(kg)": 0.0, "數量": 0
    } for _ in range(8)])], ignore_index=True)


def _delete_selected(df: pd.DataFrame) -> pd.DataFrame:
    if "選取" not in df.columns:
        return df
    df2 = df[~df["選取"].astype(bool)].copy()
    if df2.empty:
        # 保留至少 8 行空白
        if set(df.columns) == set(BOX_COLS):
            return _normalize_df(pd.DataFrame([{
                "選取": False, "名稱": "", "長": 0.0, "寬": 0.0, "高": 0.0, "數量": 0, "空箱重量": 0.0
            } for _ in range(8)]), BOX_COLS)
        return _normalize_df(pd.DataFrame([{
            "選取": False, "商品名稱": "", "長": 0.0, "寬": 0.0, "高": 0.0, "重量(kg)": 0.0, "數量": 0
        } for _ in range(8)]), PROD_COLS)
    # 仍補到至少 8 行
    while len(df2) < 8:
        if set(df.columns) == set(BOX_COLS):
            df2 = pd.concat([df2, pd.DataFrame([{
                "選取": False, "名稱": "", "長": 0.0, "寬": 0.0, "高": 0.0, "數量": 0, "空箱重量": 0.0
            }])], ignore_index=True)
        else:
            df2 = pd.concat([df2, pd.DataFrame([{
                "選取": False, "商品名稱": "", "長": 0.0, "寬": 0.0, "高": 0.0, "重量(kg)": 0.0, "數量": 0
            }])], ignore_index=True)
    return df2

# -----------------------------
# 主 UI
# -----------------------------

def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    _ensure_session_defaults()

    # Cloud config
    gas_url = st.secrets.get("GAS_URL", "") if hasattr(st, "secrets") else ""
    gas_token = st.secrets.get("GAS_TOKEN", "") if hasattr(st, "secrets") else ""
    gas_sheet_box = st.secrets.get("GAS_SHEET_BOX", DEFAULT_BOX_SHEET) if hasattr(st, "secrets") else DEFAULT_BOX_SHEET
    gas_sheet_prod = st.secrets.get("GAS_SHEET_PRODUCT", DEFAULT_PROD_SHEET) if hasattr(st, "secrets") else DEFAULT_PROD_SHEET

    store: Optional[CloudStore] = None
    cloud_ready = bool(gas_url and gas_token)
    if cloud_ready:
        store = CloudStore(CloudConfig(url=gas_url, token=gas_token, sheet_box=gas_sheet_box, sheet_product=gas_sheet_prod))

    # Header
    st.title("📦 3D裝箱系統")

    # 版面切換（不要寫 session_state.xxx = widget value 造成 setitem error）
    layout = st.radio(
        "版面配置",
        options=["左右 50% / 50%", "上下（垂直）"],
        horizontal=True,
        index=0 if st.session_state.layout_mode == "左右" else 1,
        key="layout_radio",
    )
    st.session_state.layout_mode = "左右" if layout.startswith("左右") else "上下"

    st.divider()

    if st.session_state.layout_mode == "左右":
        left, right = st.columns([1, 1], gap="large")
        with left:
            render_box_section(store)
        with right:
            render_product_section(store)
    else:
        render_box_section(store)
        st.divider()
        render_product_section(store)

    st.divider()
    render_pack_section()


def render_box_section(store: Optional[CloudStore]):
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("1. 訂單與外箱")

    st.text_input("訂單名稱", key="order_name")

    # 模板區（按你圖示：下拉 + 另存為 + 右側按鈕一起）
    st.markdown("### 箱型模板（載入 / 儲存 / 刪除）")

    names = []
    if store:
        try:
            names = store.list_names(store.cfg.sheet_box)
        except Exception:
            names = []

    colA, colB = st.columns([1.3, 1], gap="medium")

    with colA:
        tpl_sel = st.selectbox("選擇模板", options=["(無)"] + names, index=0, key="box_tpl_select")
        tpl_save_as = st.text_input("另存為模板名稱", placeholder="例如：常用箱型A", key="box_tpl_save_as")
        st.caption(f"目前套用： {st.session_state.current_box_tpl or '未選擇'}")

    with colB:
        b1, b2 = st.columns(2, gap="small")
        with b1:
            st.markdown("<div class='btn-blue'>", unsafe_allow_html=True)
            if st.button("⬇️ 載入模板", use_container_width=True, key="box_btn_load"):
                if store and tpl_sel != "(無)":
                    payload = store.get_payload(store.cfg.sheet_box, tpl_sel)
                    if payload is not None:
                        st.session_state.box_df = _payload_to_df(payload, "box")
                        st.session_state.current_box_tpl = tpl_sel
                        st.success("已載入")
                    else:
                        st.error("載入失敗")
                else:
                    st.warning("請先選擇模板")
            st.markdown("</div>", unsafe_allow_html=True)

        with b2:
            st.markdown("<div class='btn-green'>", unsafe_allow_html=True)
            if st.button("💾 儲存模板", use_container_width=True, key="box_btn_save"):
                if not store:
                    st.error("未設定雲端（GAS_URL/GAS_TOKEN），無法儲存")
                else:
                    name = (tpl_save_as or "").strip()
                    if not name:
                        st.warning("請輸入『另存為模板名稱』")
                    else:
                        ok, msg = store.upsert_payload(store.cfg.sheet_box, name, _df_to_payload(st.session_state.box_df))
                        if ok:
                            st.session_state.current_box_tpl = name
                            st.success("儲存成功")
                        else:
                            st.error(f"儲存失敗：{msg}")
            st.markdown("</div>", unsafe_allow_html=True)

        del_sel = st.selectbox("要刪除的模板", options=["(無)"] + names, index=0, key="box_tpl_del")
        st.markdown("<div class='btn-red'>", unsafe_allow_html=True)
        if st.button("🗑️ 刪除模板", use_container_width=True, key="box_btn_delete"):
            if not store:
                st.error("未設定雲端，無法刪除")
            elif del_sel == "(無)":
                st.warning("請先選擇要刪除的模板")
            else:
                ok, msg = store.delete_name(store.cfg.sheet_box, del_sel)
                if ok:
                    if st.session_state.current_box_tpl == del_sel:
                        st.session_state.current_box_tpl = ""
                    st.success("已刪除")
                else:
                    st.error(f"刪除失敗：{msg}")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    # 表格（form 避免跳回/要按兩次）
    st.markdown("### 箱型表格（勾選=參與計算；勾選後可刪除）")
    st.markdown("<div class='small-hint'>只保留一個『選取』欄：要參與裝箱就勾選；要刪除就勾選後按【刪除勾選】。</div>", unsafe_allow_html=True)

    with st.form("box_table_form", clear_on_submit=False):
        edited = st.data_editor(
            st.session_state.box_df,
            num_rows="dynamic",
            use_container_width=True,
            height=330,
            column_config={
                "選取": checkbox_col("選取"),
                "名稱": st.column_config.TextColumn("名稱"),
                "長": number_col("長", "box_L", step=0.1),
                "寬": number_col("寬", "box_W", step=0.1),
                "高": number_col("高", "box_H", step=0.1),
                "數量": st.column_config.NumberColumn("數量", step=1, format="%d"),
                "空箱重量": number_col("空箱重量", "box_empty", step=0.01),
            },
            key="box_editor",
        )

        c1, c2, c3 = st.columns([1, 1, 1.2])
        with c1:
            st.markdown("<div class='btn-green'>", unsafe_allow_html=True)
            apply = st.form_submit_button("✅ 套用變更（外箱表格）", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown("<div class='btn-red'>", unsafe_allow_html=True)
            del_btn = st.form_submit_button("🗑️ 刪除勾選", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
        with c3:
            st.markdown("<div class='btn-gray'>", unsafe_allow_html=True)
            clear_btn = st.form_submit_button("🧹 清除所有外箱", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

    if apply:
        st.session_state.box_df = _normalize_df(edited, BOX_COLS)
        st.success("已套用")
    if del_btn:
        st.session_state.box_df = _delete_selected(_normalize_df(edited, BOX_COLS))
        st.success("已刪除")
    if clear_btn:
        _clear_boxes()
        st.success("已清除")

    st.markdown("</div>", unsafe_allow_html=True)


def render_product_section(store: Optional[CloudStore]):
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("2. 商品清單")

    st.markdown("### 商品模板（載入 / 儲存 / 刪除）")

    names = []
    if store:
        try:
            names = store.list_names(store.cfg.sheet_product)
        except Exception:
            names = []

    colA, colB = st.columns([1.3, 1], gap="medium")

    with colA:
        tpl_sel = st.selectbox("選擇模板", options=["(無)"] + names, index=0, key="prod_tpl_select")
        tpl_save_as = st.text_input("另存為模板名稱", placeholder="例如：常用商品組合A", key="prod_tpl_save_as")
        st.caption(f"目前套用： {st.session_state.current_prod_tpl or '未選擇'}")

    with colB:
        b1, b2 = st.columns(2, gap="small")
        with b1:
            st.markdown("<div class='btn-blue'>", unsafe_allow_html=True)
            if st.button("⬇️ 載入模板", use_container_width=True, key="prod_btn_load"):
                if store and tpl_sel != "(無)":
                    payload = store.get_payload(store.cfg.sheet_product, tpl_sel)
                    if payload is not None:
                        st.session_state.prod_df = _payload_to_df(payload, "prod")
                        st.session_state.current_prod_tpl = tpl_sel
                        st.success("已載入")
                    else:
                        st.error("載入失敗")
                else:
                    st.warning("請先選擇模板")
            st.markdown("</div>", unsafe_allow_html=True)

        with b2:
            st.markdown("<div class='btn-green'>", unsafe_allow_html=True)
            if st.button("💾 儲存模板", use_container_width=True, key="prod_btn_save"):
                if not store:
                    st.error("未設定雲端（GAS_URL/GAS_TOKEN），無法儲存")
                else:
                    name = (tpl_save_as or "").strip()
                    if not name:
                        st.warning("請輸入『另存為模板名稱』")
                    else:
                        ok, msg = store.upsert_payload(store.cfg.sheet_product, name, _df_to_payload(st.session_state.prod_df))
                        if ok:
                            st.session_state.current_prod_tpl = name
                            st.success("儲存成功")
                        else:
                            st.error(f"儲存失敗：{msg}")
            st.markdown("</div>", unsafe_allow_html=True)

        del_sel = st.selectbox("要刪除的模板", options=["(無)"] + names, index=0, key="prod_tpl_del")
        st.markdown("<div class='btn-red'>", unsafe_allow_html=True)
        if st.button("🗑️ 刪除模板", use_container_width=True, key="prod_btn_delete"):
            if not store:
                st.error("未設定雲端，無法刪除")
            elif del_sel == "(無)":
                st.warning("請先選擇要刪除的模板")
            else:
                ok, msg = store.delete_name(store.cfg.sheet_product, del_sel)
                if ok:
                    if st.session_state.current_prod_tpl == del_sel:
                        st.session_state.current_prod_tpl = ""
                    st.success("已刪除")
                else:
                    st.error(f"刪除失敗：{msg}")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='btn-gray'>", unsafe_allow_html=True)
        if st.button("🧹 清除全部", use_container_width=True, key="prod_btn_clear_all"):
            _clear_products()
            st.success("已清除")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    st.markdown("### 商品表格（勾選=參與計算；勾選後可刪除）")
    st.markdown("<div class='small-hint'>只保留一個『選取』欄：要參與裝箱就勾選；要刪除就勾選後按【刪除勾選】。</div>", unsafe_allow_html=True)

    with st.form("prod_table_form", clear_on_submit=False):
        edited = st.data_editor(
            st.session_state.prod_df,
            num_rows="dynamic",
            use_container_width=True,
            height=330,
            column_config={
                "選取": checkbox_col("選取"),
                "商品名稱": st.column_config.TextColumn("商品名稱"),
                "長": number_col("長", "pL", step=0.1),
                "寬": number_col("寬", "pW", step=0.1),
                "高": number_col("高", "pH", step=0.1),
                "重量(kg)": number_col("重量(kg)", "pWT", step=0.01),
                "數量": st.column_config.NumberColumn("數量", step=1, format="%d"),
            },
            key="prod_editor",
        )

        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown("<div class='btn-green'>", unsafe_allow_html=True)
            apply = st.form_submit_button("✅ 套用變更（商品表格）", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown("<div class='btn-red'>", unsafe_allow_html=True)
            del_btn = st.form_submit_button("🗑️ 刪除勾選", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

    if apply:
        st.session_state.prod_df = _normalize_df(edited, PROD_COLS)
        st.success("已套用")
    if del_btn:
        st.session_state.prod_df = _delete_selected(_normalize_df(edited, PROD_COLS))
        st.success("已刪除")

    st.markdown("</div>", unsafe_allow_html=True)


def render_pack_section():
    st.subheader("3. 裝箱結果與模擬")

    st.markdown("<div class='btn-blue'>", unsafe_allow_html=True)
    if st.button("🚀 開始計算與 3D 模擬", use_container_width=True, key="btn_run_pack"):
        with st.spinner("計算中…"):
            try:
                res = pack_order(st.session_state.box_df, st.session_state.prod_df)
                if not res.get("ok"):
                    st.session_state.last_result = res
                    st.session_state.last_fig = None
                else:
                    fig = build_3d_figure(res.get("packed_bins", []))
                    st.session_state.last_result = res
                    st.session_state.last_fig = fig
            except Exception as e:
                st.session_state.last_result = {"ok": False, "error": str(e)}
                st.session_state.last_fig = None
    st.markdown("</div>", unsafe_allow_html=True)

    res = st.session_state.last_result
    fig = st.session_state.last_fig

    if not res:
        st.info("尚未計算。請先按上方『開始計算與 3D 模擬』")
        return

    if not res.get("ok"):
        st.error(res.get("error") or "發生錯誤")
        return

    packed_bins = res.get("packed_bins", [])
    remaining = res.get("remaining", [])

    # 報告摘要
    b = packed_bins[0]["box"] if packed_bins else None
    total_items = int(res.get("total_items", 0))

    st.markdown("### 訂單裝箱報告")
    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1])
    with c1:
        st.write("**訂單名稱**")
        st.write(st.session_state.order_name)
    with c2:
        st.write("**使用外箱**")
        st.write(f"{b['name']} ({b['L']}×{b['W']}×{b['H']})" if b else "-")
    with c3:
        st.write("**商品總件數**")
        st.write(total_items)
    with c4:
        st.write("**未裝入**")
        st.write(len(remaining))

    if remaining:
        st.warning("注意：有部分商品裝不下！（可能是箱型不足或尺寸不合）")

    # 匯出
    fname, html = make_report_html(st.session_state.order_name, res, fig)
    st.download_button(
        "⬇️ 下載完整裝箱報告（.html）",
        data=html.encode("utf-8"),
        file_name=fname,
        mime="text/html",
        use_container_width=True,
        key="btn_download_html",
    )

    # 3D
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("（沒有可顯示的 3D 圖）")


if __name__ == "__main__":
    main()
