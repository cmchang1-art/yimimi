# -*- coding: utf-8 -*-
# =========================
# 3D 裝箱系統（真防呆穩定版）
# - 單一 Action/Overlay 機制（按下即遮罩，完成才解鎖）
# - 修正 NameError / 全白畫面
# - plotly 唯一 key 避免 DuplicateElementId
# =========================

#------A001：匯入套件(開始)：------
import os, json, re, html, time, uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional, Tuple

import requests
import pandas as pd
import streamlit as st
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
from plotly.offline import plot as plotly_offline_plot
#------A001：匯入套件(結束)：------


#------A002：Streamlit頁面設定與全域CSS(開始)：------
st.set_page_config(page_title='3D裝箱系統', layout='wide')
st.markdown('''<style>
.block-container{padding-top:1.25rem;padding-bottom:2rem}
.muted{color:#666;font-size:13px}
.soft-card{border:1px solid #e6e6e6;border-radius:14px;padding:16px;background:#fff}
.soft-title{font-weight:800;font-size:20px;margin-bottom:10px}

/* ===== Full-page loading overlay (真防呆/鎖全頁) ===== */
._oai_overlay{
  position:fixed; inset:0;
  background:rgba(255,255,255,0.78);
  display:flex; align-items:center; justify-content:center;
  z-index:999999;
  pointer-events:all;
}
._oai_box{
  background:#fff;
  border:1px solid rgba(0,0,0,0.18);
  border-radius:14px;
  padding:14px 18px;
  box-shadow:0 10px 26px rgba(0,0,0,0.10);
  font-weight:900;
}
._oai_sub{font-weight:600;color:#555;font-size:13px;margin-top:6px;text-align:center}
._oai_spin{
  width:34px;height:34px;border-radius:999px;
  border:4px solid #e5e7eb;border-top-color:#111827;
  margin:0 auto 10px auto;
  animation:_oai_rot 1s linear infinite;
}
@keyframes _oai_rot { to { transform: rotate(360deg); } }
</style>''', unsafe_allow_html=True)
#------A002：Streamlit頁面設定與全域CSS(結束)：------


#------A003：共用工具/Action/Overlay（真防呆核心）(開始)：------
def _now_tw() -> datetime:
    return datetime.now(ZoneInfo("Asia/Taipei"))

def _safe_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", "_", s)
    return s or "report"

def _get_render_nonce() -> str:
    # 每次 rerun 變更，避免任何 element id / key 撞到
    if "_render_nonce" not in st.session_state:
        st.session_state["_render_nonce"] = uuid.uuid4().hex[:10]
    return st.session_state["_render_nonce"]

def _bump_render_nonce():
    st.session_state["_render_nonce"] = uuid.uuid4().hex[:10]

def _render_fullpage_overlay(msg: str):
    st.markdown(
        f"""
        <div class="_oai_overlay">
          <div class="_oai_box">
            <div class="_oai_spin"></div>
            <div>⏳ {html.escape(msg)}</div>
            <div class="_oai_sub">請稍候，完成後會自動更新畫面</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

def _trigger(action: str, payload: Optional[dict] = None, message: str = "處理中，請稍候..."):
    st.session_state["_pending_action"] = action
    st.session_state["_pending_payload"] = payload or {}
    st.session_state["_pending_message"] = message
    st.session_state["_busy"] = True
    st.session_state["_busy_since"] = time.monotonic()
    _bump_render_nonce()
    st.rerun()

def _has_action() -> bool:
    return bool(st.session_state.get("_pending_action"))

def _consume_action():
    act = st.session_state.get("_pending_action")
    payload = st.session_state.get("_pending_payload") or {}
    msg = st.session_state.get("_pending_message") or "處理中，請稍候..."
    st.session_state["_pending_action"] = None
    st.session_state["_pending_payload"] = {}
    st.session_state["_pending_message"] = ""
    return act, payload, msg

def _loading_watchdog(timeout_sec: int = 60):
    # 避免遮罩卡死：busy 超過 timeout 就自動解除（並清 pending）
    if not st.session_state.get("_busy"):
        st.session_state["_busy_since"] = None
        return
    t0 = st.session_state.get("_busy_since")
    if t0 is None:
        st.session_state["_busy_since"] = time.monotonic()
        return
    if (time.monotonic() - float(t0)) > timeout_sec:
        st.session_state["_busy"] = False
        st.session_state["_busy_since"] = None
        st.session_state["_pending_action"] = None
        st.session_state["_pending_payload"] = {}
        st.session_state["_pending_message"] = ""

def _handle_action(handler_map: dict):
    # 必須在 UI 前面呼叫：先顯示遮罩，再執行耗時，完成後再 rerun
    if not _has_action():
        return
    act, payload, msg = _consume_action()
    _render_fullpage_overlay(msg)

    try:
        fn = handler_map.get(act)
        if fn:
            fn(payload)
    except Exception as e:
        st.session_state["_last_error"] = f"{type(e).__name__}: {e}"
    finally:
        st.session_state["_busy"] = False
        st.session_state["_busy_since"] = None
        _bump_render_nonce()
        st.rerun()
#------A003：共用工具/Action/Overlay（真防呆核心）(結束)：------


#------A004：GASClient（自動相容版：POST/GET、多種欄位名）(開始)：------
import traceback

def _get_secret(name: str, default: str = "") -> str:
    try:
        v = st.secrets.get(name, None)
        if v is not None:
            return str(v)
    except Exception:
        pass
    return str(os.environ.get(name, default) or default)

class GASClient:
    """
    盡量相容常見 GAS Web App 寫法：
    - POST JSON: {"op":"list","sheet":"..."} 或 {"action":"list",...} 或 {"mode":"list",...}
    - GET query: ?op=list&sheet=...
    - token 可能在 Header / payload / query
    - 回傳可能是：{"ok":true,"names":[...]} 或 {"status":"ok","data":[...]} 等
    """
    def __init__(self, url: str, token: str = "", timeout: int = 30):
        self.url = (url or "").strip()
        self.token = (token or "").strip()
        self.timeout = int(timeout)

    @property
    def ready(self) -> bool:
        return bool(self.url)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            # 有些 GAS 會讀 Authorization
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _normalize_list(self, res: dict) -> list:
        if not isinstance(res, dict):
            return []
        # 常見 keys
        for k in ("names", "list", "items", "data"):
            v = res.get(k)
            if isinstance(v, list):
                # data 可能是 [{"name":"A"},...]
                if v and isinstance(v[0], dict):
                    for nk in ("name", "title", "key"):
                        if nk in v[0]:
                            return [str(x.get(nk, "")).strip() for x in v if str(x.get(nk, "")).strip()]
                return [str(x).strip() for x in v if str(x).strip()]
        return []

    def _normalize_payload(self, res: dict):
        if not isinstance(res, dict):
            return None
        for k in ("payload", "row", "item", "data", "value"):
            if k in res:
                return res.get(k)
        # 有些直接回傳 payload 本體
        if "rows" in res:
            return res
        return None

    def _ok(self, res: dict) -> bool:
        if not isinstance(res, dict):
            return False
        if res.get("ok") is True:
            return True
        if str(res.get("status", "")).lower() in ("ok", "success", "true"):
            return True
        if res.get("success") is True:
            return True
        return False

    def _request(self, payload: dict) -> dict:
        if not self.url:
            return {"ok": False, "error": "GAS_URL 未設定"}

        # 1) 先試 POST JSON（多數都可）
        try:
            p = dict(payload or {})
            if self.token:
                # 有些 GAS 只看 payload token
                p.setdefault("token", self.token)
            r = requests.post(self.url, json=p, headers=self._headers(), timeout=self.timeout)
            r.raise_for_status()
            try:
                return r.json()
            except Exception:
                return {"ok": False, "raw": r.text}
        except Exception:
            # 2) 再試 GET query（不少人用 doGet）
            try:
                q = dict(payload or {})
                if self.token:
                    q.setdefault("token", self.token)
                r = requests.get(self.url, params=q, timeout=self.timeout)
                r.raise_for_status()
                try:
                    return r.json()
                except Exception:
                    return {"ok": False, "raw": r.text}
            except Exception as e2:
                return {"ok": False, "error": f"{type(e2).__name__}: {e2}"}

    def _call_multi(self, variants: list) -> dict:
        last = {}
        for p in variants:
            res = self._request(p)
            last = res
            if self._ok(res):
                return res
        return last

    def list_names(self, sheet: str) -> list:
        variants = [
            {"op": "list", "sheet": sheet},
            {"action": "list", "sheet": sheet},
            {"mode": "list", "sheet": sheet},
            {"op": "names", "sheet": sheet},
            {"action": "names", "sheet": sheet},
        ]
        res = self._call_multi(variants)
        return self._normalize_list(res)

    def get_payload(self, sheet: str, name: str):
        variants = [
            {"op": "get", "sheet": sheet, "name": name},
            {"action": "get", "sheet": sheet, "name": name},
            {"mode": "get", "sheet": sheet, "name": name},
            {"op": "read", "sheet": sheet, "name": name},
            {"action": "read", "sheet": sheet, "name": name},
        ]
        res = self._call_multi(variants)
        if not self._ok(res):
            return None
        return self._normalize_payload(res)

    def create_only(self, sheet: str, name: str, payload: dict):
        variants = [
            {"op": "create_only", "sheet": sheet, "name": name, "payload": payload},
            {"op": "create", "sheet": sheet, "name": name, "payload": payload},
            {"action": "create", "sheet": sheet, "name": name, "payload": payload},
            {"mode": "create", "sheet": sheet, "name": name, "payload": payload},
        ]
        res = self._call_multi(variants)
        ok = self._ok(res)
        msg = str(res.get("msg") or res.get("message") or ("OK" if ok else res.get("error") or "create failed"))
        return ok, msg

    def delete(self, sheet: str, name: str):
        variants = [
            {"op": "delete", "sheet": sheet, "name": name},
            {"action": "delete", "sheet": sheet, "name": name},
            {"mode": "delete", "sheet": sheet, "name": name},
            {"op": "remove", "sheet": sheet, "name": name},
            {"action": "remove", "sheet": sheet, "name": name},
        ]
        res = self._call_multi(variants)
        ok = self._ok(res)
        msg = str(res.get("msg") or res.get("message") or ("OK" if ok else res.get("error") or "delete failed"))
        return ok, msg

GAS_URL = _get_secret("GAS_URL", "")
GAS_TOKEN = _get_secret("GAS_TOKEN", "")
gas = GASClient(GAS_URL, GAS_TOKEN) if GAS_URL else GASClient("")
#------A004：GASClient（自動相容版：POST/GET、多種欄位名）(結束)：------


#------A005：GAS cache（避免切換一直打 API）(開始)：------
def _gas_cache_key(prefix: str, sheet: str, name: str = "") -> str:
    return f"_gas_cache::{prefix}::{sheet}::{name}"

def _cache_gas_list(sheet: str) -> list:
    k = _gas_cache_key("list", sheet)
    if k in st.session_state:
        return st.session_state[k]
    names = gas.list_names(sheet) if gas.ready else []
    st.session_state[k] = names
    return names

def _cache_gas_get(sheet: str, name: str):
    k = _gas_cache_key("get", sheet, name)
    if k in st.session_state:
        return st.session_state[k]
    payload = gas.get_payload(sheet, name) if gas.ready else None
    st.session_state[k] = payload
    return payload

def _gas_cache_clear():
    keys = [k for k in st.session_state.keys() if str(k).startswith("_gas_cache::")]
    for k in keys:
        st.session_state.pop(k, None)
#------A005：GAS cache（避免切換一直打 API）(結束)：------


#------A006：外箱資料清理/防呆(開始)：------
def _to_float(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return float(default)
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        if s == "":
            return float(default)
        s = s.replace(",", "")
        return float(s)
    except Exception:
        return float(default)

def _sanitize_box(df: pd.DataFrame) -> pd.DataFrame:
    """
    外箱表格清理：
    - 補齊欄位
    - 轉型
    - 移除空白列
    - 清完是空就回空（不硬塞預設）
    """
    cols = ["選取", "名稱", "長", "寬", "高", "數量", "空箱重量"]

    if df is None:
        df = pd.DataFrame(columns=cols)

    df = df.copy()

    for c in cols:
        if c not in df.columns:
            df[c] = "" if c == "名稱" else 0

    df = df[cols].fillna("")

    if df.empty:
        return pd.DataFrame(columns=cols)

    def _to_bool(x):
        if isinstance(x, bool):
            return x
        s = str(x).strip().lower()
        return s in ("1", "true", "t", "yes", "y", "✅")

    df["選取"] = df["選取"].apply(_to_bool)
    df["名稱"] = df["名稱"].apply(lambda x: str(x).strip() if x is not None else "")

    for c in ["長", "寬", "高", "空箱重量"]:
        df[c] = df[c].apply(lambda x: _to_float(x, 0.0))

    df["數量"] = df["數量"].apply(lambda x: int(_to_float(x, 0.0)))

    def _is_empty_row(r):
        return (r["名稱"] == "") and (r["長"] == 0) and (r["寬"] == 0) and (r["高"] == 0) and (r["數量"] == 0)

    df = df[~df.apply(_is_empty_row, axis=1)].reset_index(drop=True)

    if df.empty:
        return pd.DataFrame(columns=cols)

    return df
#------A006：外箱資料清理/防呆(結束)：------


#------A007：商品資料清理/防呆(開始)：------
def _sanitize_prod(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["選取", "商品名稱", "長", "寬", "高", "重量(kg)", "數量"]

    if df is None:
        df = pd.DataFrame(columns=cols)

    df = df.copy()
    for c in cols:
        if c not in df.columns:
            df[c] = "" if c == "商品名稱" else 0

    df = df[cols].fillna("")

    if df.empty:
        return pd.DataFrame(columns=cols)

    def _to_bool(x):
        if isinstance(x, bool):
            return x
        s = str(x).strip().lower()
        return s in ("1", "true", "t", "yes", "y", "✅")

    df["選取"] = df["選取"].apply(_to_bool)
    df["商品名稱"] = df["商品名稱"].apply(lambda x: str(x).strip() if x is not None else "")

    for c in ["長", "寬", "高", "重量(kg)"]:
        df[c] = df[c].apply(lambda x: _to_float(x, 0.0))
    df["數量"] = df["數量"].apply(lambda x: int(_to_float(x, 0.0)))

    def _is_empty_row(r):
        return (r["商品名稱"] == "") and (r["長"] == 0) and (r["寬"] == 0) and (r["高"] == 0) and (r["數量"] == 0)

    df = df[~df.apply(_is_empty_row, axis=1)].reset_index(drop=True)

    if df.empty:
        return pd.DataFrame(columns=cols)

    return df
#------A007：商品資料清理/防呆(結束)：------


#------A008：初始化 Session State（安全版）(開始)：------
SHEET_BOX = "box_templates"
SHEET_PROD = "prod_templates"

def _ensure_defaults():
    now = _now_tw()

    if "order_name" not in st.session_state or not st.session_state.get("order_name"):
        st.session_state.order_name = f"訂單_{now.strftime('%Y%m%d')}"

    if "layout_mode" not in st.session_state:
        st.session_state.layout_mode = "左右 50% / 50%"

    if "df_box" not in st.session_state or st.session_state.df_box is None:
        st.session_state.df_box = pd.DataFrame(columns=["選取","名稱","長","寬","高","數量","空箱重量"])
    if "df_prod" not in st.session_state or st.session_state.df_prod is None:
        st.session_state.df_prod = pd.DataFrame(columns=["選取","商品名稱","長","寬","高","重量(kg)","數量"])

    if "active_box_tpl" not in st.session_state:
        st.session_state.active_box_tpl = ""
    if "active_prod_tpl" not in st.session_state:
        st.session_state.active_prod_tpl = ""

    if "last_result" not in st.session_state:
        st.session_state.last_result = None

    if "_busy" not in st.session_state:
        st.session_state["_busy"] = False
    if "_busy_since" not in st.session_state:
        st.session_state["_busy_since"] = None
    if "_pending_action" not in st.session_state:
        st.session_state["_pending_action"] = None
    if "_pending_payload" not in st.session_state:
        st.session_state["_pending_payload"] = {}
    if "_pending_message" not in st.session_state:
        st.session_state["_pending_message"] = ""
#------A008：初始化 Session State（安全版）(結束)：------


#------A009：模板 payload 轉換(開始)：------
def _box_payload(df):
    rows=[]
    for _,r in df.fillna('').iterrows():
        rows.append({
            'selected':bool(r['選取']),
            'name':str(r['名稱']).strip(),
            'l':_to_float(r['長']),
            'w':_to_float(r['寬']),
            'h':_to_float(r['高']),
            'qty':int(_to_float(r['數量'],0)),
            'tare':_to_float(r['空箱重量'])
        })
    return {'rows':rows}

def _box_from(payload):
    if not isinstance(payload,dict):
        raise ValueError('payload is not dict')
    rows=payload.get('rows',[])
    out=[]
    for r in rows if isinstance(rows,list) else []:
        if not isinstance(r,dict): 
            continue
        out.append({
            '選取':bool(r.get('selected',False)),
            '名稱':str(r.get('name','')),
            '長':_to_float(r.get('l',0)),
            '寬':_to_float(r.get('w',0)),
            '高':_to_float(r.get('h',0)),
            '數量':int(_to_float(r.get('qty',0),0)),
            '空箱重量':_to_float(r.get('tare',0))
        })
    return _sanitize_box(pd.DataFrame(out))

def _prod_payload(df):
    rows=[]
    for _,r in df.fillna('').iterrows():
        rows.append({
            'selected':bool(r['選取']),
            'name':str(r['商品名稱']).strip(),
            'l':_to_float(r['長']),
            'w':_to_float(r['寬']),
            'h':_to_float(r['高']),
            'wt':_to_float(r['重量(kg)']),
            'qty':int(_to_float(r['數量'],0))
        })
    return {'rows':rows}

def _prod_from(payload):
    if not isinstance(payload,dict):
        raise ValueError('payload is not dict')
    rows=payload.get('rows',[])
    out=[]
    for r in rows if isinstance(rows,list) else []:
        if not isinstance(r,dict):
            continue
        out.append({
            '選取':bool(r.get('selected',False)),
            '商品名稱':str(r.get('name','')),
            '長':_to_float(r.get('l',0)),
            '寬':_to_float(r.get('w',0)),
            '高':_to_float(r.get('h',0)),
            '重量(kg)':_to_float(r.get('wt',0)),
            '數量':int(_to_float(r.get('qty',0),0))
        })
    return _sanitize_prod(pd.DataFrame(out))
#------A009：模板 payload 轉換(結束)：------


#------A010：模板區塊 UI（全走真防呆 Action）(開始)：------
def template_block(title:str, sheet:str, active_key:str, df_key:str, to_payload, from_payload, key_prefix:str):
    # 先處理該區塊的 pending action（確保點按後下一輪真的做）
    def _do_load(_p):
        nm = str(_p.get("name","")).strip()
        payload = _cache_gas_get(sheet, nm)
        if payload is None:
            st.session_state["_tpl_msg"] = f"載入失敗：{nm}"
            return
        df_loaded = from_payload(payload)
        st.session_state[df_key] = df_loaded
        st.session_state[active_key] = nm
        # 同步 live df（避免 3D 用到舊資料）
        if df_key == "df_box":
            st.session_state["_box_live_df"] = df_loaded.copy()
            st.session_state.pop("box_editor", None)
        if df_key == "df_prod":
            st.session_state["_prod_live_df"] = df_loaded.copy()
            st.session_state.pop("prod_editor", None)
        _gas_cache_clear()
        st.session_state["_tpl_msg"] = f"已載入：{nm}"

    def _do_save(_p):
        nm = str(_p.get("name","")).strip()
        payload = to_payload(st.session_state[df_key])
        ok, msg = gas.create_only(sheet, nm, payload) if gas.ready else (False, "未設定 GAS_URL")
        if ok:
            st.session_state[active_key] = nm
            _gas_cache_clear()
        st.session_state["_tpl_msg"] = msg

    def _do_delete(_p):
        nm = str(_p.get("name","")).strip()
        ok, msg = gas.delete(sheet, nm) if gas.ready else (False, "未設定 GAS_URL")
        if ok and st.session_state.get(active_key) == nm:
            st.session_state[active_key] = ""
        _gas_cache_clear()
        st.session_state["_tpl_msg"] = msg

    _handle_action({
        f"{key_prefix}__LOAD": _do_load,
        f"{key_prefix}__SAVE": _do_save,
        f"{key_prefix}__DEL":  _do_delete,
    })

    st.markdown(f"### {title}（載入 / 儲存 / 刪除）")

    if not gas.ready:
        st.info("尚未設定 Streamlit Secrets（GAS_URL / GAS_TOKEN）。模板功能暫停（不影響裝箱計算）。")
        return

    names = ['(無)'] + sorted(_cache_gas_list(sheet))

    c1, c2 = st.columns([1, 1], gap='medium')
    c3 = st.container()

    with c1:
        sel = st.selectbox('選擇模板', names, key=f'{key_prefix}_sel')
        if st.button('⬇️ 載入模板', use_container_width=True, key=f'{key_prefix}_load'):
            if sel == "(無)":
                st.warning("請先選擇要載入的模板")
            else:
                _trigger(f"{key_prefix}__LOAD", {"name": sel}, "讀取模板中...")

    with c2:
        del_sel = st.selectbox('要刪除的模板', names, key=f'{key_prefix}_del_sel')
        if st.button('🗑️ 刪除模板', use_container_width=True, key=f'{key_prefix}_del'):
            if del_sel == "(無)":
                st.warning("請先選擇要刪除的模板")
            else:
                _trigger(f"{key_prefix}__DEL", {"name": del_sel}, "刪除模板中...")

    with c3:
        new_name = st.text_input('另存為模板名稱', placeholder='例如：常用A', key=f'{key_prefix}_new')
        if st.button('💾 儲存模板', use_container_width=True, key=f'{key_prefix}_save'):
            nm = (new_name or "").strip()
            if not nm:
                st.warning("請先輸入「另存為模板名稱」")
            else:
                _trigger(f"{key_prefix}__SAVE", {"name": nm}, "儲存模板中...")

    if st.session_state.get("_tpl_msg"):
        st.caption(st.session_state["_tpl_msg"])
        st.session_state["_tpl_msg"] = ""
    st.caption(f"目前套用：{st.session_state.get(active_key) or '未選擇'}")
#------A010：模板區塊 UI（全走真防呆 Action）(結束)：------


#------A011：外箱表格 UI（全走真防呆 Action）(開始)：------
def box_table_block():
    def _apply(_p):
        edited = st.session_state.get("_box_live_df", st.session_state.df_box)
        clean = _sanitize_box(edited)
        st.session_state.df_box = clean
        st.session_state["_box_live_df"] = clean.copy()
        st.session_state["_box_msg"] = "已套用外箱表格變更"
        _gas_cache_clear()

    def _del(_p):
        edited = st.session_state.get("_box_live_df", st.session_state.df_box)
        d = _sanitize_box(edited)
        d = d[~d['選取']].reset_index(drop=True)
        d = _sanitize_box(d)
        st.session_state.df_box = d
        st.session_state["_box_live_df"] = d.copy()
        st.session_state["_box_msg"] = "已刪除勾選外箱"

    def _clear(_p):
        empty = pd.DataFrame(columns=["選取","名稱","長","寬","高","數量","空箱重量"])
        st.session_state.df_box = empty
        st.session_state["_box_live_df"] = empty.copy()
        st.session_state.active_box_tpl = ""
        st.session_state["_box_msg"] = "已清空全部外箱"

    _handle_action({
        "BOX__APPLY": _apply,
        "BOX__DEL": _del,
        "BOX__CLEAR": _clear,
    })

    st.markdown('### 箱型表格（勾選=參與計算；勾選後可刪除）')
    st.markdown('<div class="muted">只保留一個「選取」欄：要參與裝箱就勾選；要刪除就勾選後按「刪除勾選」。</div>', unsafe_allow_html=True)

    df = _sanitize_box(st.session_state.df_box)

    edited = st.data_editor(
        df,
        key='box_editor',
        hide_index=True,
        num_rows='dynamic',
        use_container_width=True,
        height=320,
        column_config={
            '選取': st.column_config.CheckboxColumn('選取'),
            '名稱': st.column_config.TextColumn('名稱'),
            '長': st.column_config.NumberColumn('長', step=0.1, format='%.2f'),
            '寬': st.column_config.NumberColumn('寬', step=0.1, format='%.2f'),
            '高': st.column_config.NumberColumn('高', step=0.1, format='%.2f'),
            '數量': st.column_config.NumberColumn('數量', step=1),
            '空箱重量': st.column_config.NumberColumn('空箱重量', step=0.01, format='%.2f')
        }
    )
    st.session_state["_box_live_df"] = edited.copy()

    b1, b2, b3 = st.columns([1, 1, 1], gap='medium')
    with b1:
        if st.button('✅ 套用變更（外箱表格）', use_container_width=True, key='box_apply'):
            _trigger("BOX__APPLY", {}, "套用外箱變更中...")
    with b2:
        if st.button('🗑️ 刪除勾選', use_container_width=True, key='box_del'):
            _trigger("BOX__DEL", {}, "刪除外箱中...")
    with b3:
        if st.button('🧹 清除全部外箱', use_container_width=True, key='box_clear'):
            _trigger("BOX__CLEAR", {}, "清除外箱中...")

    if st.session_state.get("_box_msg"):
        st.success(st.session_state["_box_msg"])
        st.session_state["_box_msg"] = ""
#------A011：外箱表格 UI（全走真防呆 Action）(結束)：------


#------A012：商品表格 UI（全走真防呆 Action）(開始)：------
def prod_table_block():
    def _apply(_p):
        edited = st.session_state.get("_prod_live_df", st.session_state.df_prod)
        clean = _sanitize_prod(edited)
        st.session_state.df_prod = clean
        st.session_state["_prod_live_df"] = clean.copy()
        st.session_state["_prod_msg"] = "已套用商品表格變更"
        _gas_cache_clear()

    def _del(_p):
        edited = st.session_state.get("_prod_live_df", st.session_state.df_prod)
        d = _sanitize_prod(edited)
        d = d[~d['選取']].reset_index(drop=True)
        d = _sanitize_prod(d)
        st.session_state.df_prod = d
        st.session_state["_prod_live_df"] = d.copy()
        st.session_state["_prod_msg"] = "已刪除勾選商品"

    def _clear(_p):
        empty = pd.DataFrame(columns=["選取","商品名稱","長","寬","高","重量(kg)","數量"])
        st.session_state.df_prod = empty
        st.session_state["_prod_live_df"] = empty.copy()
        st.session_state.active_prod_tpl = ""
        st.session_state["_prod_msg"] = "已清空全部商品"

    _handle_action({
        "PROD__APPLY": _apply,
        "PROD__DEL": _del,
        "PROD__CLEAR": _clear,
    })

    st.markdown('### 商品表格（勾選=參與計算；勾選後可刪除）')
    st.markdown('<div class="muted">只保留一個「選取」欄：要參與裝箱就勾選；要刪除就勾選後按「刪除勾選」。</div>', unsafe_allow_html=True)

    df = _sanitize_prod(st.session_state.df_prod)

    edited = st.data_editor(
        df,
        key='prod_editor',
        hide_index=True,
        num_rows='dynamic',
        use_container_width=True,
        height=320,
        column_config={
            '選取': st.column_config.CheckboxColumn('選取'),
            '商品名稱': st.column_config.TextColumn('商品名稱'),
            '長': st.column_config.NumberColumn('長', step=0.1, format='%.2f'),
            '寬': st.column_config.NumberColumn('寬', step=0.1, format='%.2f'),
            '高': st.column_config.NumberColumn('高', step=0.1, format='%.2f'),
            '重量(kg)': st.column_config.NumberColumn('重量(kg)', step=0.01, format='%.2f'),
            '數量': st.column_config.NumberColumn('數量', step=1)
        }
    )
    st.session_state["_prod_live_df"] = edited.copy()

    b1, b2, b3 = st.columns([1, 1, 1], gap='medium')
    with b1:
        if st.button('✅ 套用變更（商品表格）', use_container_width=True, key='prod_apply'):
            _trigger("PROD__APPLY", {}, "套用商品變更中...")
    with b2:
        if st.button('🗑️ 刪除勾選', use_container_width=True, key='prod_del'):
            _trigger("PROD__DEL", {}, "刪除商品中...")
    with b3:
        if st.button('🧹 清除全部商品', use_container_width=True, key='prod_clear'):
            _trigger("PROD__CLEAR", {}, "清除商品中...")

    if st.session_state.get("_prod_msg"):
        st.success(st.session_state["_prod_msg"])
        st.session_state["_prod_msg"] = ""
#------A012：商品表格 UI（全走真防呆 Action）(結束)：------


#------A013：外箱/商品展開(開始)：------
def _build_bins(df_box:pd.DataFrame)->List[Dict[str,Any]]:
    bins=[]
    for _,r in df_box.iterrows():
        if not bool(r.get('選取', False)):
            continue
        qty=int(r.get('數量',0) or 0)
        if qty<=0:
            continue
        L=float(r.get('長',0) or 0)
        W=float(r.get('寬',0) or 0)
        H=float(r.get('高',0) or 0)
        if L<=0 or W<=0 or H<=0:
            continue
        name=(str(r.get('名稱','') or '').strip() or '外箱')
        tare=float(r.get('空箱重量',0) or 0)
        for _i in range(qty):
            bins.append({'name':name,'l':L,'w':W,'h':H,'tare':tare})
    return bins

def _build_items(df_prod:pd.DataFrame)->List[Item]:
    items=[]
    for _,r in df_prod.iterrows():
        if not bool(r.get('選取', False)):
            continue
        qty=int(r.get('數量',0) or 0)
        if qty<=0:
            continue
        L=float(r.get('長',0) or 0)
        W=float(r.get('寬',0) or 0)
        H=float(r.get('高',0) or 0)
        if L<=0 or W<=0 or H<=0:
            continue
        nm=(str(r.get('商品名稱','') or '').strip() or '商品')
        wt=float(r.get('重量(kg)',0) or 0)
        for i in range(qty):
            items.append(Item(f"{nm}_{i+1}", L, W, H, wt))
    return items
#------A013：外箱/商品展開(結束)：------


#------A014：3D 圖(開始)：------
def build_3d_fig(box:Dict[str,Any], fitted:List[Item], color_map:Dict[str,str]=None)->go.Figure:
    fig=go.Figure()
    L=float(box['l']); W=float(box['w']); H=float(box['h'])

    edges=[((0,0,0),(L,0,0)),((L,0,0),(L,W,0)),((L,W,0),(0,W,0)),((0,W,0),(0,0,0)),
           ((0,0,H),(L,0,H)),((L,0,H),(L,W,H)),((L,W,H),(0,W,H)),((0,W,H),(0,0,H)),
           ((0,0,0),(0,0,H)),((L,0,0),(L,0,H)),((L,W,0),(L,W,H)),((0,W,0),(0,W,H))]
    for a,b in edges:
        fig.add_trace(go.Scatter3d(
            x=[a[0],b[0]],y=[a[1],b[1]],z=[a[2],b[2]],
            mode='lines', line=dict(width=5,color='#111'),
            hoverinfo='skip', showlegend=False
        ))

    def _base_name(n:str)->str:
        n=str(n or '')
        return n.rsplit('_',1)[0] if '_' in n else n

    def _rot_dim(it:Item):
        if hasattr(it,'get_dimension'):
            d=it.get_dimension()
            return float(d[0]),float(d[1]),float(d[2])
        return float(it.width),float(it.height),float(it.depth)

    if color_map is None:
        palette=['#2F3A4A','#4C6A92','#6C757D','#8E9AAF','#A3B18A','#B08968','#C9ADA7','#6D6875']
        color_map={}
        ci=0
        for it in fitted:
            base=_base_name(getattr(it,'name',''))
            if base not in color_map:
                color_map[base]=palette[ci%len(palette)]
                ci += 1

    for it in fitted:
        name=str(getattr(it,'name',''))
        base=_base_name(name)
        c=color_map.get(base, '#4C6A92')
        px,py,pz=[float(v) for v in (getattr(it,'position',[0,0,0]) or [0,0,0])]
        dx,dy,dz=_rot_dim(it)

        vx=[px,px+dx,px+dx,px,px,px+dx,px+dx,px]
        vy=[py,py,py+dy,py+dy,py,py,py+dy,py+dy]
        vz=[pz,pz,pz,pz,pz+dz,pz+dz,pz+dz,pz+dz]

        faces=[(0,1,2),(0,2,3),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
               (1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
        I,J,K=zip(*faces)

        fig.add_trace(go.Mesh3d(
            x=vx,y=vy,z=vz, i=I,j=J,k=K,
            color=c, opacity=1.0, flatshading=True,
            hovertemplate=f"{base}<br>尺寸:{dx:.1f}×{dy:.1f}×{dz:.1f}<extra></extra>",
            showlegend=False
        ))

    fig.update_layout(
        scene=dict(
            xaxis=dict(range=[0,L], title='長 (L)'),
            yaxis=dict(range=[0,W], title='寬 (W)'),
            zaxis=dict(range=[0,H], title='高 (H)'),
            aspectmode='data'
        ),
        margin=dict(l=0,r=0,t=0,b=0),
        height=520
    )
    return fig
#------A014：3D 圖(結束)：------


#------A015：HTML 報告(開始)：------
def build_report_html(
    order_name:str,
    packed_bins:List[Dict[str,Any]],
    unfitted:List[Item],
    content_wt:float,
    total_wt:float,
    util:float,
    color_map:Dict[str,str]
)->str:
    ts=_now_tw().strftime('%Y-%m-%d %H:%M:%S (台灣時間)')

    warn=''
    if unfitted:
        counts={}
        for it in unfitted:
            base=str(it.name).split('_')[0]
            counts[base]=counts.get(base,0)+1
        warn="<div class='warn'><b>注意：</b>有部分商品裝不下！</div>"+''.join(
            [f"<div class='warn2'>⚠ {k}：超過 {v} 個</div>" for k,v in counts.items()]
        )

    legend_items=''.join([
        f"<div class='legrow'><span class='sw' style='background:{c}'></span>{k}</div>"
        for k,c in (color_map or {}).items()
    ])

    sections=[]
    for idx,p in enumerate(packed_bins, start=1):
        box=p['box']; items=p['items']
        fig=build_3d_fig(box, items, color_map=color_map)
        fig_div=plotly_offline_plot(fig, output_type='div', include_plotlyjs=('cdn' if idx==1 else False))
        sections.append(f"""
          <div class='boxcard'>
            <div class='boxtitle'>📦 {p['name']}（裝入 {len(items)} 件）</div>
            <div class='boxmeta'>箱子尺寸：{box['l']} × {box['w']} × {box['h']}</div>
            <div class='boxgrid'>
              <div class='legend'>
                <div class='legtitle'>分類說明</div>
                {legend_items}
              </div>
              <div class='plot'>{fig_div}</div>
            </div>
          </div>
        """)

    body=''.join(sections) if sections else "<div class='warn'>本次沒有任何箱子成功裝入商品。</div>"

    return f"""<!doctype html><html lang='zh-Hant'><head>
<meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/>
<title>訂單裝箱報告 - {_safe_name(order_name)}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang TC','Microsoft JhengHei',Arial,sans-serif;margin:0;background:#fff}}
.container{{max-width:1200px;margin:24px auto;padding:0 16px}}
.card{{border:1px solid #e6e6e6;border-radius:14px;padding:16px 18px;margin:12px 0}}
h2{{margin:0 0 10px 0}}
.meta{{display:flex;flex-direction:column;gap:6px;color:#222}}
.warn{{border:1px solid #f2b8b5;background:#fdecea;padding:10px 12px;border-radius:12px;margin:12px 0}}
.warn2{{border:1px solid #f2b8b5;background:#fdecea;padding:8px 12px;border-radius:12px;margin:8px 0}}
.boxcard{{border:1px solid #e6e6e6;border-radius:14px;padding:14px 14px;margin:14px 0}}
.boxtitle{{font-weight:900;margin-bottom:6px}}
.boxmeta{{color:#444;margin-bottom:10px}}
.boxgrid{{display:grid;grid-template-columns:260px 1fr;gap:12px;align-items:start}}
.legend{{border:1px solid #eee;border-radius:12px;padding:10px 10px}}
.legtitle{{font-weight:800;margin-bottom:8px}}
.legrow{{display:flex;align-items:center;gap:8px;margin:6px 0}}
.sw{{width:14px;height:14px;border:2px solid #111;border-radius:3px;display:inline-block}}
.plot{{border-radius:12px;overflow:hidden}}
@media (max-width:900px){{ .boxgrid{{grid-template-columns:1fr}} }}
</style>
</head><body>
<div class='container'>
  <div class='card'>
    <h2>🧾 訂單裝箱報告</h2>
    <div class='meta'>
      <div>🧾 <b>訂單名稱</b>　{order_name}</div>
      <div>🕒 <b>計算時間</b>　{ts}</div>
      <div>📦 <b>使用箱數</b>　<b>{len(packed_bins)}</b> 箱</div>
      <div>⚖️ <b>內容淨重</b>　{content_wt:.2f} kg</div>
      <div>🔴 <b>本次總重</b>　{total_wt:.2f} kg</div>
      <div>📊 <b>整體空間利用率</b>　{util:.2f}%</div>
    </div>
    {warn}
  </div>
  {body}
</div>
</body></html>"""
#------A015：HTML 報告(結束)：------


#------A016：裝箱計算核心(開始)：------
def pack_and_render(order_name:str, df_box:pd.DataFrame, df_prod:pd.DataFrame)->Dict[str,Any]:
    bins=_build_bins(df_box)
    if not bins:
        return {'ok':False,'error':'請至少勾選 1 個外箱（且數量>0、尺寸>0）'}

    items=_build_items(df_prod)
    if not items:
        return {'ok':False,'error':'請至少勾選 1 個商品（且數量>0、尺寸>0）'}

    palette=['#2F3A4A','#4C6A92','#6C757D','#8E9AAF','#A3B18A','#B08968','#C9ADA7','#6D6875']
    base_order=[]
    for _,r in df_prod.iterrows():
        if not bool(r.get('選取', False)):
            continue
        qty=int(r.get('數量',0) or 0)
        L=float(r.get('長',0) or 0); W=float(r.get('寬',0) or 0); H=float(r.get('高',0) or 0)
        if qty<=0 or L<=0 or W<=0 or H<=0:
            continue
        base_order.append(str(r.get('商品名稱','') or '商品').strip() or '商品')

    color_map={}
    ci=0
    for bname in base_order:
        if bname not in color_map:
            color_map[bname]=palette[ci%len(palette)]
            ci += 1

    def _vol(b): return float(b['l']*b['w']*b['h'])
    bins_sorted=sorted(bins, key=_vol, reverse=True)

    remaining=list(items)
    packed=[]

    for i,b in enumerate(bins_sorted, start=1):
        if not remaining:
            break

        packer=Packer()
        packer.add_bin(Bin(f"{b['name']}#{i}", float(b['l']), float(b['w']), float(b['h']), 999999))
        for it in remaining:
            packer.add_item(it)

        try:
            packer.pack(bigger_first=True, distribute_items=False)
        except TypeError:
            packer.pack()

        bb=packer.bins[0]
        fitted=list(getattr(bb,'items',[]) or [])
        unfitted=list(getattr(bb,'unfitted_items',[]) or [])

        if fitted:
            packed.append({'box':b, 'name':bb.name, 'items':fitted})

        remaining=unfitted

    unfitted=remaining
    all_fitted=[it for p in packed for it in p['items']]
    content_wt=sum(float(getattr(it,'weight',0) or 0) for it in all_fitted)
    tare_total=sum(float(p['box'].get('tare',0) or 0) for p in packed)
    total_wt=content_wt+tare_total

    used_bin_vol=sum(float(p['box']['l']*p['box']['w']*p['box']['h']) for p in packed)
    used_item_vol=0.0
    for it in all_fitted:
        if hasattr(it,'get_dimension'):
            d=it.get_dimension()
            used_item_vol += float(d[0]*d[1]*d[2])
        else:
            used_item_vol += float(it.width*it.height*it.depth)
    util=(used_item_vol/used_bin_vol*100.0) if used_bin_vol>0 else 0.0
    util=max(0.0, min(100.0, util))

    return {
        'ok':True,
        'packed_bins': packed,
        'used_bin_count': len(packed),
        'unfitted': unfitted,
        'content_wt': content_wt,
        'total_wt': total_wt,
        'util': util,
        'color_map': color_map,
    }
#------A016：裝箱計算核心(結束)：------


#------A017：商品總件數統計(開始)：------
def _total_items(df_prod:pd.DataFrame)->int:
    if df_prod is None or df_prod.empty:
        return 0
    sel=df_prod['選取'].astype(bool)
    return int(df_prod.loc[sel,'數量'].apply(lambda x:int(_to_float(x,0))).sum())
#------A017：商品總件數統計(結束)：------


#------A018：結果區塊（3D 計算也走真防呆）(開始)：------
def result_block():
    def _do_run(_p):
        df_box_src  = st.session_state.get('_box_live_df',  st.session_state.df_box)
        df_prod_src = st.session_state.get('_prod_live_df', st.session_state.df_prod)

        st.session_state.df_box  = _sanitize_box(df_box_src)
        st.session_state.df_prod = _sanitize_prod(df_prod_src)

        res = pack_and_render(
            st.session_state.order_name,
            st.session_state.df_box,
            st.session_state.df_prod
        )
        res['run_id'] = str(int(time.time() * 1000))
        st.session_state.last_result = res

    _handle_action({"RUN__PACK": _do_run})

    st.markdown('## 3. 裝箱結果與模擬')

    if st.button('🚀 開始計算與 3D 模擬', use_container_width=True, key=f'run_pack_{_get_render_nonce()}'):
        _trigger("RUN__PACK", {}, "計算與 3D 模擬中...")

    res = st.session_state.get('last_result')
    if not res:
        return
    if not res.get('ok'):
        st.error(res.get('error', '計算失敗'))
        return

    packed_bins = res.get('packed_bins') or []
    unfitted = res.get('unfitted') or []
    color_map = res.get('color_map') or {}
    run_id = str(res.get('run_id', '0'))

    report_html = build_report_html(
        st.session_state.order_name,
        packed_bins=packed_bins,
        unfitted=unfitted,
        content_wt=float(res.get('content_wt', 0.0) or 0.0),
        total_wt=float(res.get('total_wt', 0.0) or 0.0),
        util=float(res.get('util', 0.0) or 0.0),
        color_map=color_map
    )

    st.markdown("### 🧾 訂單裝箱報告")
    st.markdown('<div class="soft-card">', unsafe_allow_html=True)

    used_bin_count = int(res.get('used_bin_count', 0))
    st.markdown(
        f"""
        <div style="display:flex;flex-direction:column;gap:8px">
          <div>🧾 <b>訂單名稱</b>　<span style="color:#1f6feb;font-weight:900">{st.session_state.order_name}</span></div>
          <div>🕒 <b>計算時間</b>　{_now_tw().strftime('%Y-%m-%d %H:%M:%S (台灣時間)')}</div>
          <div>📦 <b>使用箱數</b>　<b>{used_bin_count}</b> 箱</div>
          <div>⚖️ <b>內容淨重</b>　{float(res.get('content_wt',0.0) or 0.0):.2f} kg</div>
          <div>🔴 <b>本次總重</b>　<span style="color:#c62828;font-weight:900">{float(res.get('total_wt',0.0) or 0.0):.2f} kg</span></div>
          <div>📊 <b>整體空間利用率</b>　{float(res.get('util',0.0) or 0.0):.2f}%</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if unfitted:
        counts = {}
        for it in unfitted:
            base = str(it.name).split('_')[0]
            counts[base] = counts.get(base, 0) + 1
        st.warning('注意：有部分商品裝不下！（可能箱型尺寸不足或箱數不足）')
        for k, v in counts.items():
            st.error(f"{k}：超過 {v} 個")

    st.markdown('</div>', unsafe_allow_html=True)

    ts = _now_tw().strftime('%Y%m%d_%H%M')
    fname = f"{_safe_name(st.session_state.order_name)}_{ts}_總數{_total_items(st.session_state.df_prod)}件.html"
    st.download_button(
        '⬇️ 下載完整裝箱報告（.html）',
        data=report_html.encode('utf-8'),
        file_name=fname,
        mime='text/html',
        use_container_width=True,
        key=f'dl_report_{run_id}'
    )

    if not packed_bins:
        st.info("本次沒有任何箱子成功裝入商品。")
        return

    legend_html = "<div style='display:flex;flex-direction:column;gap:6px'>"
    legend_html += "<div style='font-weight:900;margin-bottom:4px'>分類說明</div>"
    for k, c in (color_map or {}).items():
        legend_html += (
            "<div style='display:flex;align-items:center;gap:8px'>"
            f"<span style='width:14px;height:14px;border:2px solid #111;border-radius:3px;background:{c};display:inline-block'></span>"
            f"<span>{html.escape(str(k))}</span></div>"
        )
    legend_html += "</div>"

    tab_titles = [f"{p['name']}（裝入 {len(p.get('items') or [])} 件）" for p in packed_bins]
    tabs = st.tabs(tab_titles)

    for i, (t, p) in enumerate(zip(tabs, packed_bins)):
        with t:
            box_meta = p['box']
            fitted = list(p.get('items') or [])

            c1, c2 = st.columns([1, 3], gap='large')
            with c1:
                st.markdown(legend_html, unsafe_allow_html=True)
                st.markdown(
                    f"<div style='margin-top:10px;color:#444'>箱子尺寸：{box_meta['l']} × {box_meta['w']} × {box_meta['h']}</div>",
                    unsafe_allow_html=True
                )
            with c2:
                fig = build_3d_fig(box_meta, fitted, color_map=color_map)
                st.plotly_chart(fig, use_container_width=True, key=f'plot_{run_id}_{i}')
#------A018：結果區塊（3D 計算也走真防呆）(結束)：------


#------A019：主程式(開始)：------
def main():
    _loading_watchdog(timeout_sec=60)
    _ensure_defaults()

    # 如果上一輪炸掉，顯示錯誤，但不要讓整頁白掉
    if st.session_state.get("_last_error"):
        st.error(st.session_state["_last_error"])
        st.session_state["_last_error"] = ""

    st.title('📦 3D裝箱系統')

    st.markdown('#### 版面配置')
    mode = st.radio(
        '',
        ['左右 50% / 50%','上下（垂直）'],
        horizontal=True,
        key='layout_radio',
        index=0 if st.session_state.layout_mode=='左右 50% / 50%' else 1
    )
    st.session_state.layout_mode = mode

    st.text_input('訂單名稱', key='order_name')

    if st.session_state.layout_mode == '左右 50% / 50%':
        left, right = st.columns([1,1], gap='large')
        with left:
            st.markdown('## 1. 訂單與外箱')
            template_block('箱型模板', SHEET_BOX, 'active_box_tpl', 'df_box',
                           _box_payload, _box_from, 'box_tpl')
            box_table_block()

        with right:
            st.markdown('## 2. 商品清單')
            template_block('商品模板', SHEET_PROD, 'active_prod_tpl', 'df_prod',
                           _prod_payload, _prod_from, 'prod_tpl')
            prod_table_block()

        st.divider()
        result_block()

    else:
        st.markdown('## 1. 訂單與外箱')
        template_block('箱型模板', SHEET_BOX, 'active_box_tpl', 'df_box',
                       _box_payload, _box_from, 'box_tpl')
        box_table_block()

        st.divider()

        st.markdown('## 2. 商品清單')
        template_block('商品模板', SHEET_PROD, 'active_prod_tpl', 'df_prod',
                       _prod_payload, _prod_from, 'prod_tpl')
        prod_table_block()

        st.divider()
        result_block()
#------A019：主程式(結束)：------


#------A020：入口(開始)：------
main()
#------A020：入口(結束)：------
