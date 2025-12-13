# -*- coding: utf-8 -*-
"""
3D 裝箱系統（穩定版 / Streamlit Community Cloud 友善）

重點修正：
- 版面切換：左右 50/50 或 上下（垂直），呈現方式與你原先一致
- 表格：用「選取」欄位勾選後一鍵刪除（移除原本最後一欄「刪除」）
- 避免「動作要按兩次 / 會跳回原狀」：所有表格修改都在 form 內，按【套用變更】一次生效
- 3D：py3dbp 自動旋轉，並用相容寫法呼叫 pack()，避免 fix_point 參數報錯
- Google Sheet / Apps Script：有設定 Secrets 就走雲端，沒設定就退回本機 data/ JSON
"""

import json
import math
import os
import time
import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# -----------------------------
# 基本設定
# -----------------------------
APP_TITLE = "3D裝箱系統"
DATA_DIR = "data"
LOCAL_BOX_FILE = os.path.join(DATA_DIR, "box_presets.json")
LOCAL_TPL_FILE = os.path.join(DATA_DIR, "product_templates.json")

DEFAULT_BOX_COLS = ["選取", "使用", "名稱", "長", "寬", "高", "數量", "空箱重量"]
DEFAULT_PROD_COLS = ["選取", "啟用", "商品名稱", "長", "寬", "高", "重量(kg)", "數量"]

# -----------------------------
# 外觀（按鈕配色 + 表格 + 版面）
# -----------------------------
CSS = """
<style>
/* 讓整體更像你原本的乾淨白底 */
main .block-container { padding-top: 1.5rem; padding-bottom: 2.5rem; }
h1 { margin-bottom: .25rem; }
hr { margin: 1rem 0 1.25rem 0; }

/* 表格高度與字體 */
div[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }

/* 按鈕群組：用外層 div class 來精準上色 */
.btn-soft-green div[data-testid="stButton"] button,
.btn-soft-green div[data-testid="stFormSubmitButton"] button{
  background: #E8F5E9 !important; color: #1B5E20 !important;
  border: 1px solid #C8E6C9 !important;
}
.btn-soft-blue div[data-testid="stButton"] button,
.btn-soft-blue div[data-testid="stFormSubmitButton"] button{
  background: #E3F2FD !important; color: #0D47A1 !important;
  border: 1px solid #BBDEFB !important;
}
.btn-soft-red div[data-testid="stButton"] button,
.btn-soft-red div[data-testid="stFormSubmitButton"] button{
  background: #FFEBEE !important; color: #B71C1C !important;
  border: 1px solid #FFCDD2 !important;
}
.btn-soft-gray div[data-testid="stButton"] button,
.btn-soft-gray div[data-testid="stFormSubmitButton"] button{
  background: #F5F5F5 !important; color: #263238 !important;
  border: 1px solid #E0E0E0 !important;
}

/* 讓按鈕文字更清楚 */
div[data-testid="stButton"] button, div[data-testid="stFormSubmitButton"] button{
  border-radius: 10px !important;
  font-weight: 700 !important;
}

/* 小提示文字 */
.small-hint { color: #6b7280; font-size: .9rem; }
.badge { display:inline-block; padding:.15rem .5rem; border-radius: 999px; border:1px solid #e5e7eb; background:#fafafa; font-size:.85rem; }
</style>
"""

# -----------------------------
# 儲存層（Apps Script / Local JSON）
# -----------------------------
@dataclass
class StorageConfig:
    apps_script_url: Optional[str] = None
    apps_script_token: Optional[str] = None

class Storage:
    """
    雲端（Apps Script Web App）優先；若未設定 secrets 則使用本地 JSON（Streamlit Cloud 也可用，但不跨使用者）
    Apps Script 介面（建議）：
      GET  {url}?token=...&action=ping
      GET  {url}?token=...&action=list_box_templates
      GET  {url}?token=...&action=list_product_templates
      GET  {url}?token=...&action=load_box_template&name=xxx
      GET  {url}?token=...&action=load_product_template&name=xxx
      POST {url} JSON {token, action, name, data}
      action = save_box_template / save_product_template / delete_box_template / delete_product_template
    """
    def __init__(self, cfg: StorageConfig):
        self.cfg = cfg
        self._ensure_local_dir()

    def _ensure_local_dir(self):
        os.makedirs(DATA_DIR, exist_ok=True)

    def _has_cloud(self) -> bool:
        return bool(self.cfg.apps_script_url and self.cfg.apps_script_token)

    def _cloud_get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        import requests
        params = dict(params)
        params["token"] = self.cfg.apps_script_token
        url = self.cfg.apps_script_url
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def _cloud_post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        import requests
        payload = dict(payload)
        payload["token"] = self.cfg.apps_script_token
        url = self.cfg.apps_script_url
        r = requests.post(url, json=payload, timeout=20)
        r.raise_for_status()
        return r.json()

    # -------- Local JSON helpers --------
    def _read_local_json(self, path: str, default: Any) -> Any:
        try:
            if not os.path.exists(path):
                return default
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _write_local_json(self, path: str, data: Any) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # -------- Public: Boxes --------
    def load_boxes(self) -> List[Dict[str, Any]]:
        if self._has_cloud():
            # 讓雲端也能存「目前外箱清單」：用固定名稱 __CURRENT__
            try:
                res = self._cloud_get({"action": "load_box_template", "name": "__CURRENT__"})
                if res.get("ok") and isinstance(res.get("data"), list):
                    return res["data"]
            except Exception:
                pass

        data = self._read_local_json(LOCAL_BOX_FILE, [])
        return data if isinstance(data, list) else []

    def save_boxes(self, boxes: List[Dict[str, Any]]) -> None:
        if self._has_cloud():
            try:
                self._cloud_post({"action": "save_box_template", "name": "__CURRENT__", "data": boxes})
                return
            except Exception:
                pass
        self._write_local_json(LOCAL_BOX_FILE, boxes)

    def list_box_templates(self) -> List[str]:
        if self._has_cloud():
            try:
                res = self._cloud_get({"action": "list_box_templates"})
                if res.get("ok") and isinstance(res.get("names"), list):
                    return [n for n in res["names"] if n != "__CURRENT__"]
            except Exception:
                pass
        # local：盒模板和目前盒清單同檔，這裡簡化：只回空（你主要用雲端）
        return []

    def load_box_template(self, name: str) -> Optional[List[Dict[str, Any]]]:
        if not name:
            return None
        if self._has_cloud():
            res = self._cloud_get({"action": "load_box_template", "name": name})
            if res.get("ok") and isinstance(res.get("data"), list):
                return res["data"]
        return None

    def save_box_template(self, name: str, data: List[Dict[str, Any]]) -> bool:
        if not name:
            return False
        if self._has_cloud():
            res = self._cloud_post({"action": "save_box_template", "name": name, "data": data})
            return bool(res.get("ok"))
        return False

    def delete_box_template(self, name: str) -> bool:
        if not name:
            return False
        if self._has_cloud():
            res = self._cloud_post({"action": "delete_box_template", "name": name})
            return bool(res.get("ok"))
        return False

    # -------- Public: Products --------
    def load_products(self) -> List[Dict[str, Any]]:
        if self._has_cloud():
            try:
                res = self._cloud_get({"action": "load_product_template", "name": "__CURRENT__"})
                if res.get("ok") and isinstance(res.get("data"), list):
                    return res["data"]
            except Exception:
                pass

        data = self._read_local_json(LOCAL_TPL_FILE, [])
        return data if isinstance(data, list) else []

    def save_products(self, prods: List[Dict[str, Any]]) -> None:
        if self._has_cloud():
            try:
                self._cloud_post({"action": "save_product_template", "name": "__CURRENT__", "data": prods})
                return
            except Exception:
                pass
        self._write_local_json(LOCAL_TPL_FILE, prods)

    def list_product_templates(self) -> List[str]:
        if self._has_cloud():
            try:
                res = self._cloud_get({"action": "list_product_templates"})
                if res.get("ok") and isinstance(res.get("names"), list):
                    return [n for n in res["names"] if n != "__CURRENT__"]
            except Exception:
                pass
        return []

    def load_product_template(self, name: str) -> Optional[List[Dict[str, Any]]]:
        if not name:
            return None
        if self._has_cloud():
            res = self._cloud_get({"action": "load_product_template", "name": name})
            if res.get("ok") and isinstance(res.get("data"), list):
                return res["data"]
        return None

    def save_product_template(self, name: str, data: List[Dict[str, Any]]) -> bool:
        if not name:
            return False
        if self._has_cloud():
            res = self._cloud_post({"action": "save_product_template", "name": name, "data": data})
            return bool(res.get("ok"))
        return False

    def delete_product_template(self, name: str) -> bool:
        if not name:
            return False
        if self._has_cloud():
            res = self._cloud_post({"action": "delete_product_template", "name": name})
            return bool(res.get("ok"))
        return False

# -----------------------------
# Utils
# -----------------------------
def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or (isinstance(x, str) and x.strip() == ""):
            return default
        return float(x)
    except Exception:
        return default

def _to_int(x: Any, default: int = 0) -> int:
    try:
        if x is None or (isinstance(x, str) and x.strip() == ""):
            return default
        return int(float(x))
    except Exception:
        return default

def _normalize_boxes(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        out.append({
            "選取": bool(r.get("選取", False)),
            "使用": bool(r.get("使用", True)),
            "名稱": str(r.get("名稱", "")).strip() or "未命名箱型",
            "長": _to_float(r.get("長", 0)),
            "寬": _to_float(r.get("寬", 0)),
            "高": _to_float(r.get("高", 0)),
            "數量": max(0, _to_int(r.get("數量", 1), 1)),
            "空箱重量": max(0.0, _to_float(r.get("空箱重量", 0.0), 0.0)),
        })
    return out

def _normalize_products(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        out.append({
            "選取": bool(r.get("選取", False)),
            "啟用": bool(r.get("啟用", True)),
            "商品名稱": str(r.get("商品名稱", "")).strip() or "未命名商品",
            "長": _to_float(r.get("長", 0)),
            "寬": _to_float(r.get("寬", 0)),
            "高": _to_float(r.get("高", 0)),
            "重量(kg)": max(0.0, _to_float(r.get("重量(kg)", 0.0), 0.0)),
            "數量": max(0, _to_int(r.get("數量", 1), 1)),
        })
    return out

def _df_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    return df.fillna("").to_dict("records")

def _records_to_df(records: List[Dict[str, Any]], cols: List[str]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame([{c: "" for c in cols}]).iloc[0:0]
    df = pd.DataFrame(records)
    for c in cols:
        if c not in df.columns:
            df[c] = "" if c not in ("使用","啟用","選取") else False
    return df[cols]

# -----------------------------
# 3D Packing (py3dbp)
# -----------------------------
def _try_import_py3dbp():
    try:
        from py3dbp import Packer, Bin, Item  # type: ignore
        return Packer, Bin, Item
    except Exception:
        return None, None, None

def pack_3d(box: Dict[str, Any], products: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    回傳：
      result: {ok, fitted, unfitted, stats...}
      placed_items: list of placed items with position/dim
    """
    Packer, Bin, Item = _try_import_py3dbp()
    if Packer is None:
        return {"ok": False, "error": "缺少 py3dbp 套件。請在 requirements.txt 加入 py3dbp"}, []

    L = _to_float(box.get("長", 0))
    W = _to_float(box.get("寬", 0))
    H = _to_float(box.get("高", 0))
    if min(L, W, H) <= 0:
        return {"ok": False, "error": "外箱尺寸不正確（長/寬/高 必須 > 0）"}, []

    packer = Packer()
    max_weight = 9999999
    b = Bin(str(box.get("名稱", "Box")), L, W, H, max_weight)
    packer.add_bin(b)

    # 加入商品（展開 quantity）
    total_weight = 0.0
    total_volume = 0.0
    items_count = 0
    for p in products:
        if not bool(p.get("啟用", True)):
            continue
        qty = _to_int(p.get("數量", 0), 0)
        if qty <= 0:
            continue
        l = _to_float(p.get("長", 0))
        w = _to_float(p.get("寬", 0))
        h = _to_float(p.get("高", 0))
        if min(l, w, h) <= 0:
            continue
        weight = _to_float(p.get("重量(kg)", 0.0), 0.0)
        name = str(p.get("商品名稱", "Item"))

        for i in range(qty):
            it = Item(f"{name}_{i+1}", l, w, h, weight)
            # 允許旋轉：盡量用不同版本相容的屬性
            try:
                it.rotation_type = 6  # all rotations
            except Exception:
                pass
            packer.add_item(it)

        total_weight += weight * qty
        total_volume += (l * w * h) * qty
        items_count += qty

    # pack() 不同版本參數不同，做相容呼叫（避免 fix_point 報錯）
    try:
        packer.pack(bigger_first=True, distribute_items=False, number_of_decimals=1)
    except TypeError:
        try:
            packer.pack(bigger_first=True, distribute_items=False)
        except TypeError:
            packer.pack()

    fitted = []
    unfitted = []
    placed_items: List[Dict[str, Any]] = []

    for bi in packer.bins:
        # 已放入
        for it in getattr(bi, "items", []):
            pos = getattr(it, "position", [0, 0, 0])
            dim = getattr(it, "get_dimension", lambda: (it.width, it.height, it.depth))()
            # py3dbp 維度順序有版本差異，保守處理：
            try:
                dx, dy, dz = dim
            except Exception:
                dx, dy, dz = it.width, it.height, it.depth

            placed_items.append({
                "name": getattr(it, "name", ""),
                "x": float(pos[0]), "y": float(pos[1]), "z": float(pos[2]),
                "dx": float(dx), "dy": float(dy), "dz": float(dz),
                "weight": float(getattr(it, "weight", 0.0)),
            })
            fitted.append(getattr(it, "name", ""))

        for it in getattr(bi, "unfitted_items", []):
            unfitted.append(getattr(it, "name", ""))

    box_volume = L * W * H
    used_volume = sum(i["dx"] * i["dy"] * i["dz"] for i in placed_items)
    utilization = (used_volume / box_volume * 100.0) if box_volume > 0 else 0.0

    result = {
        "ok": True,
        "fitted_count": len(fitted),
        "unfitted_count": len(unfitted),
        "unfitted_items": unfitted,
        "items_count": items_count,
        "content_weight": round(total_weight, 3),
        "box_empty_weight": round(_to_float(box.get("空箱重量", 0.0), 0.0), 3),
        "total_weight": round(total_weight + _to_float(box.get("空箱重量", 0.0), 0.0), 3),
        "utilization": round(utilization, 2),
    }
    return result, placed_items

def plot_3d(box: Dict[str, Any], placed_items: List[Dict[str, Any]]) -> go.Figure:
    L = _to_float(box.get("長", 0))
    W = _to_float(box.get("寬", 0))
    H = _to_float(box.get("高", 0))

    fig = go.Figure()

    # 外箱框線（wireframe）
    corners = [
        (0, 0, 0), (L, 0, 0), (L, W, 0), (0, W, 0),
        (0, 0, H), (L, 0, H), (L, W, H), (0, W, H),
    ]
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7)
    ]
    ex, ey, ez = [], [], []
    for a, b in edges:
        (x1, y1, z1) = corners[a]
        (x2, y2, z2) = corners[b]
        ex += [x1, x2, None]
        ey += [y1, y2, None]
        ez += [z1, z2, None]
    fig.add_trace(go.Scatter3d(x=ex, y=ey, z=ez, mode="lines", name="外箱", showlegend=False))

    # 物件方塊
    for i, it in enumerate(placed_items):
        x, y, z = it["x"], it["y"], it["z"]
        dx, dy, dz = it["dx"], it["dy"], it["dz"]
        # cuboid vertices
        vx = [x, x+dx, x+dx, x, x, x+dx, x+dx, x]
        vy = [y, y, y+dy, y+dy, y, y, y+dy, y+dy]
        vz = [z, z, z, z, z+dz, z+dz, z+dz, z+dz]
        faces = [
            (0, 1, 2, 3),
            (4, 5, 6, 7),
            (0, 1, 5, 4),
            (2, 3, 7, 6),
            (1, 2, 6, 5),
            (0, 3, 7, 4),
        ]
        for (a, b, c, d) in faces:
            fig.add_trace(go.Mesh3d(
                x=[vx[a], vx[b], vx[c], vx[d]],
                y=[vy[a], vy[b], vy[c], vy[d]],
                z=[vz[a], vz[b], vz[c], vz[d]],
                opacity=0.55,
                name=it["name"],
                showlegend=False,
                i=[0, 0], j=[1, 2], k=[2, 3]
            ))

    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        scene=dict(
            xaxis_title="x",
            yaxis_title="y",
            zaxis_title="z",
            aspectmode="data",
        ),
        height=480,
    )
    return fig

# -----------------------------
# UI Helpers
# -----------------------------
def init_state(storage: Storage):
    if "layout_mode" not in st.session_state:
        st.session_state.layout_mode = "左右 50% / 50%"
    if "order_name" not in st.session_state:
        st.session_state.order_name = f"訂單_{dt.datetime.now().strftime('%Y%m%d')}"
    if "boxes" not in st.session_state:
        st.session_state.boxes = _normalize_boxes(storage.load_boxes())
        if not st.session_state.boxes:
            st.session_state.boxes = _normalize_boxes([{
                "選取": False, "使用": True, "名稱": "手動箱", "長": 35.0, "寬": 25.0, "高": 20.0, "數量": 1, "空箱重量": 0.5
            }])
    if "products" not in st.session_state:
        st.session_state.products = _normalize_products(storage.load_products())
        if not st.session_state.products:
            st.session_state.products = _normalize_products([
                {"選取": False, "啟用": True, "商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5},
                {"選取": False, "啟用": True, "商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5},
            ])

    # 模板選擇狀態（顯示目前套用）
    st.session_state.setdefault("active_box_template", "")
    st.session_state.setdefault("active_prod_template", "")

def render_header():
    st.title(APP_TITLE)
    st.markdown("<hr/>", unsafe_allow_html=True)

def render_layout_toggle():
    st.markdown("**版面配置**")
    # 重要：不要在 radio 後再手動 st.session_state.layout_mode = ...
    st.radio(
        label="",
        options=["左右 50% / 50%", "上下（垂直）"],
        key="layout_mode",
        horizontal=True
    )

def section_title(n: int, text: str):
    st.markdown(f"### {n}. {text}")

def soft_button_wrap(cls: str, fn):
    st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
    out = fn()
    st.markdown('</div>', unsafe_allow_html=True)
    return out

# -----------------------------
# Box / Product Tables
# -----------------------------
def box_table_form(storage: Storage):
    section_title(1, "訂單與外箱設定")

    left, right = st.columns([1.2, 1.0])
    with left:
        st.text_input("訂單名稱", key="order_name")

    # 盒模板操作：放在一起（不拆散）
    box_tpl_names = ["(無)"] + storage.list_box_templates()
    with right:
        st.markdown("**箱型模板（載入 / 另存 / 刪除）**")
        c1, c2 = st.columns([1.1, 1.0])
        with c1:
            selected = st.selectbox("選擇模板", box_tpl_names, key="box_tpl_select")
        with c2:
            tpl_name = st.text_input("另存為模板名稱", key="box_tpl_saveas", placeholder="例如：常用箱型A")

        c3, c4, c5 = st.columns([1, 1, 1])
        with c3:
            clicked_load = soft_button_wrap("btn-soft-gray", lambda: st.button("載入", use_container_width=True, key="box_tpl_load"))
        with c4:
            clicked_save = soft_button_wrap("btn-soft-blue", lambda: st.button("儲存", use_container_width=True, key="box_tpl_save"))
        with c5:
            clicked_del = soft_button_wrap("btn-soft-red", lambda: st.button("刪除模板", use_container_width=True, key="box_tpl_delete"))

        if st.session_state.active_box_template:
            st.markdown(f'<span class="badge">目前套用：{st.session_state.active_box_template}</span>', unsafe_allow_html=True)

        if clicked_load:
            if selected != "(無)":
                data = storage.load_box_template(selected)
                if data is not None:
                    st.session_state.boxes = _normalize_boxes(data)
                    st.session_state.active_box_template = selected
                    st.success("已載入箱型模板")
                else:
                    st.error("載入失敗：找不到模板或雲端未連線")
            else:
                st.info("請先選擇要載入的模板")

        if clicked_save:
            if tpl_name.strip():
                ok = storage.save_box_template(tpl_name.strip(), st.session_state.boxes)
                if ok:
                    st.session_state.active_box_template = tpl_name.strip()
                    st.success("已儲存箱型模板")
                else:
                    st.error("儲存失敗：請確認雲端連線 / 權限")
            else:
                st.warning("請輸入『另存為模板名稱』")

        if clicked_del:
            if selected != "(無)":
                ok = storage.delete_box_template(selected)
                if ok:
                    if st.session_state.active_box_template == selected:
                        st.session_state.active_box_template = ""
                    st.success("已刪除模板")
                else:
                    st.error("刪除失敗：請確認雲端連線 / 權限")
            else:
                st.info("請先選擇要刪除的模板")

    st.markdown('<div class="small-hint">✅ 表格修改在下方按【套用變更】一次生效（避免跳回 / 要按兩次）。</div>', unsafe_allow_html=True)

    # 表格（Form 避免雙點）
    df = _records_to_df(st.session_state.boxes, DEFAULT_BOX_COLS)

    with st.form("box_editor_form", clear_on_submit=False):
        edited = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            height=360,  # 約 8 行以上
            column_config={
                "選取": st.column_config.CheckboxColumn("選取", help="勾選後可用下方按鈕刪除"),
                "使用": st.column_config.CheckboxColumn("使用", help="未勾選：不參與裝箱"),
                "名稱": st.column_config.TextColumn("名稱"),
                "長": st.column_config.NumberColumn("長", step=0.1, format="%.2f"),
                "寬": st.column_config.NumberColumn("寬", step=0.1, format="%.2f"),
                "高": st.column_config.NumberColumn("高", step=0.1, format="%.2f"),
                "數量": st.column_config.NumberColumn("數量", step=1),
                "空箱重量": st.column_config.NumberColumn("空箱重量", step=0.01, format="%.2f"),
            },
            key="box_editor",
        )

        b1, b2, b3 = st.columns([1, 1, 1])
        with b1:
            apply_btn = soft_button_wrap("btn-soft-green", lambda: st.form_submit_button("套用變更", use_container_width=True))
        with b2:
            add_btn = soft_button_wrap("btn-soft-green", lambda: st.form_submit_button("新增一列箱型", use_container_width=True))
        with b3:
            del_btn = soft_button_wrap("btn-soft-red", lambda: st.form_submit_button("刪除勾選箱型", use_container_width=True))

        clear_btn = soft_button_wrap("btn-soft-gray", lambda: st.form_submit_button("清除套用（重設為預設箱型）", use_container_width=True))

    if apply_btn or add_btn or del_btn or clear_btn:
        # 以 form 的 edited 為準，避免第一次被回復
        rows = _df_to_records(edited)

        if clear_btn:
            st.session_state.boxes = _normalize_boxes([{
                "選取": False, "使用": True, "名稱": "手動箱", "長": 35.0, "寬": 25.0, "高": 20.0, "數量": 1, "空箱重量": 0.5
            }])
            st.session_state.active_box_template = ""
            storage.save_boxes(st.session_state.boxes)
            st.success("已清除套用並重設")
            st.rerun()

        if add_btn:
            rows.append({
                "選取": False, "使用": True, "名稱": "新箱型",
                "長": 45.0, "寬": 30.0, "高": 30.0,
                "數量": 1, "空箱重量": 0.5
            })

        if del_btn:
            rows = [r for r in rows if not bool(r.get("選取", False))]

        st.session_state.boxes = _normalize_boxes(rows)
        storage.save_boxes(st.session_state.boxes)

        if st.session_state.active_box_template:
            st.info("你目前有套用箱型模板；若要更新模板內容，請點右上『儲存』覆寫/另存。")

        st.success("已套用變更")
        st.rerun()

def product_table_form(storage: Storage):
    section_title(2, "商品清單（直接編輯表格）")

    # 商品模板操作：放在一起（不拆散）
    tpl_names = ["(無)"] + storage.list_product_templates()
    st.markdown("**商品模板（載入 / 另存 / 刪除）**")

    c1, c2, c3 = st.columns([1.2, 1.2, 1.0])
    with c1:
        selected = st.selectbox("選擇模板", tpl_names, key="prod_tpl_select")
    with c2:
        tpl_name = st.text_input("另存為模板名稱", key="prod_tpl_saveas", placeholder="例如：常用商品組合A")
    with c3:
        # 目前套用
        if st.session_state.active_prod_template:
            st.markdown(f'<span class="badge">目前套用：{st.session_state.active_prod_template}</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="badge">目前套用：未選擇</span>', unsafe_allow_html=True)

    b1, b2, b3 = st.columns([1, 1, 1])
    with b1:
        clicked_load = soft_button_wrap("btn-soft-gray", lambda: st.button("載入", use_container_width=True, key="prod_tpl_load"))
    with b2:
        clicked_save = soft_button_wrap("btn-soft-blue", lambda: st.button("儲存", use_container_width=True, key="prod_tpl_save"))
    with b3:
        clicked_del = soft_button_wrap("btn-soft-red", lambda: st.button("刪除模板", use_container_width=True, key="prod_tpl_delete"))

    if clicked_load:
        if selected != "(無)":
            data = storage.load_product_template(selected)
            if data is not None:
                st.session_state.products = _normalize_products(data)
                st.session_state.active_prod_template = selected
                st.success("已載入商品模板")
                storage.save_products(st.session_state.products)  # 同步 __CURRENT__
                st.rerun()
            else:
                st.error("載入失敗：找不到模板或雲端未連線")
        else:
            st.info("請先選擇要載入的模板")

    if clicked_save:
        if tpl_name.strip():
            ok = storage.save_product_template(tpl_name.strip(), st.session_state.products)
            if ok:
                st.session_state.active_prod_template = tpl_name.strip()
                st.success("已儲存商品模板")
                st.rerun()
            else:
                st.error("儲存失敗：請確認雲端連線 / 權限")
        else:
            st.warning("請輸入『另存為模板名稱』")

    if clicked_del:
        if selected != "(無)":
            ok = storage.delete_product_template(selected)
            if ok:
                if st.session_state.active_prod_template == selected:
                    st.session_state.active_prod_template = ""
                st.success("已刪除模板")
                st.rerun()
            else:
                st.error("刪除失敗：請確認雲端連線 / 權限")
        else:
            st.info("請先選擇要刪除的模板")

    st.markdown('<div class="small-hint">✅ 勾選「啟用」且數量 > 0 才會進入裝箱；勾選「選取」可刪除。</div>', unsafe_allow_html=True)

    df = _records_to_df(st.session_state.products, DEFAULT_PROD_COLS)

    with st.form("prod_editor_form", clear_on_submit=False):
        edited = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            height=360,  # 至少 8 行
            column_config={
                "選取": st.column_config.CheckboxColumn("選取", help="勾選後可刪除"),
                "啟用": st.column_config.CheckboxColumn("啟用"),
                "商品名稱": st.column_config.TextColumn("商品名稱"),
                "長": st.column_config.NumberColumn("長", step=0.1, format="%.2f"),
                "寬": st.column_config.NumberColumn("寬", step=0.1, format="%.2f"),
                "高": st.column_config.NumberColumn("高", step=0.1, format="%.2f"),
                "重量(kg)": st.column_config.NumberColumn("重量(kg)", step=0.01, format="%.2f"),
                "數量": st.column_config.NumberColumn("數量", step=1),
            },
            key="prod_editor",
        )

        b1, b2, b3 = st.columns([1, 1, 1])
        with b1:
            apply_btn = soft_button_wrap("btn-soft-green", lambda: st.form_submit_button("套用變更", use_container_width=True))
        with b2:
            add_btn = soft_button_wrap("btn-soft-green", lambda: st.form_submit_button("新增一列商品", use_container_width=True))
        with b3:
            del_btn = soft_button_wrap("btn-soft-red", lambda: st.form_submit_button("刪除勾選商品", use_container_width=True))

        clear_btn = soft_button_wrap("btn-soft-gray", lambda: st.form_submit_button("清除套用（清空商品列）", use_container_width=True))

    if apply_btn or add_btn or del_btn or clear_btn:
        rows = _df_to_records(edited)

        if clear_btn:
            st.session_state.products = _normalize_products([])
            st.session_state.active_prod_template = ""
            storage.save_products(st.session_state.products)
            st.success("已清空商品列表")
            st.rerun()

        if add_btn:
            rows.append({
                "選取": False, "啟用": True, "商品名稱": "新商品",
                "長": 10.0, "寬": 10.0, "高": 10.0, "重量(kg)": 0.1, "數量": 1
            })

        if del_btn:
            rows = [r for r in rows if not bool(r.get("選取", False))]

        st.session_state.products = _normalize_products(rows)
        storage.save_products(st.session_state.products)
        st.success("已套用變更")
        st.rerun()

# -----------------------------
# Compute & Report
# -----------------------------
def pick_box_for_packing(boxes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    # 先用「使用」且數量>0 的第一個箱型作為演示（你後續若要多箱，可再擴充）
    for b in boxes:
        if bool(b.get("使用", True)) and _to_int(b.get("數量", 0), 0) > 0:
            return b
    return None

def render_result_section(storage: Storage):
    section_title(3, "裝箱結果與模擬")
    st.markdown('<div class="small-hint">點【開始計算與 3D 模擬】後，會以目前勾選的外箱與商品計算。</div>', unsafe_allow_html=True)

    run_btn = soft_button_wrap("btn-soft-green", lambda: st.button("🚀 開始計算與 3D 模擬", use_container_width=True, key="run_pack"))

    if not run_btn:
        return

    with st.spinner("計算中..."):
        box = pick_box_for_packing(st.session_state.boxes)
        if not box:
            st.error("找不到可用的外箱：請在箱型表格勾選『使用』且數量 > 0")
            return

        result, placed = pack_3d(box, st.session_state.products)

    if not result.get("ok"):
        st.error(str(result.get("error", "計算失敗")))
        return

    # 報告區
    report = {
        "訂單名稱": st.session_state.order_name,
        "計算時間": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S（台灣時間）"),
        "使用外箱": f'{box.get("名稱")} ({box.get("長")}×{box.get("寬")}×{box.get("高")}) × 1 箱',
        "內容淨重": f'{result["content_weight"]} kg',
        "本次總重": f'{result["total_weight"]} kg',
        "空間利用率": f'{result["utilization"]}%',
    }

    st.markdown("#### 📦 訂單裝箱報告")
    df_rep = pd.DataFrame(list(report.items()), columns=["項目", "內容"])
    st.dataframe(df_rep, use_container_width=True, hide_index=True)

    if result["unfitted_count"] > 0:
        st.warning("注意：有部分商品裝不下！（可能是箱型庫存不足或尺寸不足）")
        st.error("；".join(result["unfitted_items"][:30]) + ("…" if len(result["unfitted_items"]) > 30 else ""))

    # 3D
    fig = plot_3d(box, placed)
    st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# Main
# -----------------------------
def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")

    st.markdown(CSS, unsafe_allow_html=True)

    # Secrets（Streamlit Community Cloud）
    apps_url = None
    apps_token = None
    try:
        apps_url = st.secrets.get("APPS_SCRIPT_URL") or st.secrets.get("apps_script_url")
        apps_token = st.secrets.get("APPS_SCRIPT_TOKEN") or st.secrets.get("apps_script_token") or st.secrets.get("TOKEN")
    except Exception:
        pass

    storage = Storage(StorageConfig(apps_script_url=apps_url, apps_script_token=apps_token))
    init_state(storage)

    render_header()
    render_layout_toggle()

    # 版面切換（要像你原本：左右 50/50 或 上下垂直）
    if st.session_state.layout_mode == "左右 50% / 50%":
        col_left, col_right = st.columns([1, 1])
        with col_left:
            box_table_form(storage)
        with col_right:
            product_table_form(storage)
        render_result_section(storage)
    else:
        box_table_form(storage)
        product_table_form(storage)
        render_result_section(storage)

if __name__ == "__main__":
    main()
