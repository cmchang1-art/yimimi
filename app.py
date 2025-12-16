# -*- coding: utf-8 -*-
#------A001：匯入套件(開始)：------
import os, json, re
import time
import html
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
.fullpage-overlay{
  position:fixed; inset:0;
  background:rgba(255,255,255,0.78);
  display:flex; align-items:center; justify-content:center;
  z-index:99999;
  pointer-events:all;   /* ✅ 直接攔截全頁點擊 */
}
.fullpage-box{
  background:#fff;
  border:1px solid rgba(0,0,0,0.18);
  border-radius:14px;
  padding:12px 16px;
  box-shadow:0 10px 26px rgba(0,0,0,0.10);
  font-weight:900;
}
.fullpage-sub{font-weight:500;color:#555;font-size:13px;margin-top:6px;text-align:center}
</style>''', unsafe_allow_html=True)
#------A002：Streamlit頁面設定與全域CSS(結束)：------



#------A003：Loading Watchdog（避免 loading 卡死）(開始)：------
import time
import streamlit as st

def _loading_watchdog(timeout_sec: int = 60):
    """
    防止 busy/遮罩卡死：
    - 如果 session_state['_busy'] 長時間為 True，代表上一輪可能中斷/例外沒清掉
    - 超過 timeout_sec 就自動解除 busy 並清掉 pending action
    """
    now = time.monotonic()

    # 初始化 timestamp
    if "_busy_since" not in st.session_state:
        st.session_state["_busy_since"] = None

    # 若正在 busy，記錄開始時間
    if st.session_state.get("_busy"):
        if st.session_state["_busy_since"] is None:
            st.session_state["_busy_since"] = now

        # 超時就強制解除（避免全站一直不能操作）
        if (now - st.session_state["_busy_since"]) > timeout_sec:
            st.session_state["_busy"] = False
            st.session_state["_busy_since"] = None
            st.session_state["_pending_action"] = None
            st.session_state["_pending_payload"] = {}
            st.session_state["_pending_message"] = ""
            # 這裡不要 st.rerun()，避免在 main 一開始就無限 rerun
    else:
        # 不 busy 就清掉 timestamp
        st.session_state["_busy_since"] = None
#------A003：Loading Watchdog（避免 loading 卡死）(結束)：------



#------A004：GAS / Secrets / 模板快取工具（補齊 _cache_gas_list 等缺漏）(開始)：------
import time
import json
import requests
import streamlit as st

def _get_secret_any(*keys: str, default=None):
    """
    不改你的 Secrets，只用「多 key 兼容讀取」：
    例如同時支援 GAS_URL / gas_url / GAS_ENDPOINT...
    """
    try:
        sec = st.secrets
    except Exception:
        sec = {}
    for k in keys:
        try:
            if k in sec and sec[k] not in (None, ""):
                return sec[k]
        except Exception:
            pass
    return default

class GASClient:
    def __init__(self, gas_url: str, gas_token: str | None = None, timeout: int = 30):
        self.gas_url = gas_url
        self.gas_token = gas_token
        self.timeout = timeout

    def _post(self, payload: dict):
        if not self.gas_url:
            raise RuntimeError("GAS_URL 未設定（Secrets 讀不到）。")
        headers = {"Content-Type": "application/json"}
        if self.gas_token:
            headers["X-Token"] = self.gas_token
        r = requests.post(self.gas_url, data=json.dumps(payload), headers=headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.text else {}

    def list_templates(self, sheet: str):
        return self._post({"op": "list", "sheet": sheet})

    def read_template(self, sheet: str, name: str):
        return self._post({"op": "read", "sheet": sheet, "name": name})

    def write_template(self, sheet: str, name: str, data: dict):
        return self._post({"op": "write", "sheet": sheet, "name": name, "data": data})

    def delete_template(self, sheet: str, name: str):
        return self._post({"op": "delete", "sheet": sheet, "name": name})

def _get_gas_client() -> GASClient | None:
    """
    用 session_state 快取 client，避免每次 rerun 都重建、也避免「程式載入順序」造成 NameError。
    """
    if "gas_client" in st.session_state and st.session_state["gas_client"] is not None:
        return st.session_state["gas_client"]

    gas_url = _get_secret_any("GAS_URL", "gas_url", "GAS_ENDPOINT", "gas_endpoint", default=None)
    gas_token = _get_secret_any("GAS_TOKEN", "gas_token", "GAS_KEY", "gas_key", default=None)

    if not gas_url:
        st.session_state["gas_client"] = None
        return None

    st.session_state["gas_client"] = GASClient(gas_url, gas_token)
    return st.session_state["gas_client"]

@st.cache_data(ttl=30, show_spinner=False)
def _cache_gas_list(sheet: str) -> list[str]:
    """
    ✅ 你缺的函式：template_block 會用到它
    回傳模板名稱 list[str]
    """
    gas = _get_gas_client()
    if not gas:
        return []
    try:
        res = gas.list_templates(sheet)
        names = res.get("names") or res.get("data") or res.get("items") or []
        # 強制轉字串、去空
        out = []
        for x in names:
            if x is None:
                continue
            s = str(x).strip()
            if s:
                out.append(s)
        return sorted(set(out))
    except Exception:
        return []

@st.cache_data(ttl=10, show_spinner=False)
def _cache_gas_read(sheet: str, name: str) -> dict:
    gas = _get_gas_client()
    if not gas:
        return {}
    try:
        res = gas.read_template(sheet, name)
        data = res.get("data") if isinstance(res, dict) else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _gas_write(sheet: str, name: str, data: dict) -> tuple[bool, str]:
    gas = _get_gas_client()
    if not gas:
        return False, "GAS_URL 未設定，無法儲存模板。"
    try:
        gas.write_template(sheet, name, data)
        # ✅ 讓 list/read 快取失效，避免你說的「畫面恢復了但資料還沒更新」假更新
        _cache_gas_list.clear()
        _cache_gas_read.clear()
        return True, "已儲存模板。"
    except Exception as e:
        return False, f"儲存失敗：{e}"

def _gas_delete(sheet: str, name: str) -> tuple[bool, str]:
    gas = _get_gas_client()
    if not gas:
        return False, "GAS_URL 未設定，無法刪除模板。"
    try:
        gas.delete_template(sheet, name)
        _cache_gas_list.clear()
        _cache_gas_read.clear()
        return True, "已刪除模板。"
    except Exception as e:
        return False, f"刪除失敗：{e}"
#------A004：GAS / Secrets / 模板快取工具（補齊 _cache_gas_list 等缺漏）(結束)：------



#------A005：全頁讀取遮罩防呆（立刻顯示 + 禁止操作）(開始)：------
import time

def _is_loading() -> bool:
    return bool(st.session_state.get('_loading', False))

def _loading_msg() -> str:
    return str(st.session_state.get('_loading_msg', '處理中...'))

def _render_loading_overlay():
    # ✅ 這個 overlay 會「吃掉滑鼠事件」=> 全頁禁止操作
    msg = _loading_msg()
    st.markdown(
        f"""
        <style>
        .yimimi-overlay {{
            position: fixed;
            inset: 0;
            background: rgba(255,255,255,.85);
            z-index: 999999;
            display:flex;
            align-items:center;
            justify-content:center;
            pointer-events: all;   /* ✅ 關鍵：阻擋點擊 */
        }}
        .yimimi-card {{
            background: #fff;
            border: 1px solid #e5e7eb;
            box-shadow: 0 10px 30px rgba(0,0,0,.08);
            border-radius: 14px;
            padding: 18px 20px;
            min-width: 280px;
            max-width: 420px;
            text-align:center;
            font-weight: 800;
        }}
        .yimimi-sub {{
            margin-top:6px;
            font-weight: 600;
            color:#555;
            font-size: 13px;
        }}
        .yimimi-spin {{
            width: 34px; height: 34px;
            border-radius: 999px;
            border: 4px solid #e5e7eb;
            border-top-color: #111827;
            margin: 0 auto 10px auto;
            animation: yimimi-rot 1s linear infinite;
        }}
        @keyframes yimimi-rot {{ to {{ transform: rotate(360deg); }} }}
        </style>
        <div class="yimimi-overlay">
          <div class="yimimi-card">
            <div class="yimimi-spin"></div>
            <div>⏳ {msg}</div>
            <div class="yimimi-sub">請稍候，資料處理完成後即可操作</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

def _begin_loading(msg: str = "處理中..."):
    st.session_state['_loading'] = True
    st.session_state['_loading_msg'] = msg
    st.session_state['_loading_t0'] = time.time()
    # ✅ 立刻把遮罩畫出來（這樣你就不會覺得慢半拍）
    _render_loading_overlay()

def _end_loading():
    st.session_state['_loading'] = False
    st.session_state['_loading_msg'] = ''
    st.session_state.pop('_loading_t0', None)
#------A005：全頁讀取遮罩防呆（立刻顯示 + 禁止操作）(結束)：------



#------A006：Google Apps Script(GAS) API Client(開始)：------
def _get_secret(key: str, default: str = "") -> str:
    """
    ✅注意：不改你的 secrets key 名稱
    只讀取 st.secrets[key]，沒有就回傳 default
    """
    try:
        v = st.secrets.get(key, default)
        return (v or default) if isinstance(v, str) else default
    except Exception:
        return default

# ✅不改 key：就是 GAS_URL / GAS_TOKEN
GAS_URL   = _get_secret("GAS_URL", "").strip()
GAS_TOKEN = _get_secret("GAS_TOKEN", "").strip()

class GASClient:
    """
    ✅這份是「完整可用版」
    會提供 template_block 需要的：
      - list_names(sheet)
      - get_payload(sheet, name)
      - create_only(sheet, name, payload)
      - upsert(sheet, name, payload)
      - delete(sheet, name)
    """
    def __init__(self, url: str, token: str):
        self.url = (url or "").strip()
        self.token = (token or "").strip()

    @property
    def ready(self) -> bool:
        return bool(self.url and self.token)

    def _call(self, action: str, sheet: str, name: str = "", payload=None) -> dict:
        if not self.ready:
            return {"ok": False, "error": "missing_gas_config"}

        params = {"action": action, "sheet": sheet, "token": self.token}
        if name:
            params["name"] = name

        try:
            if action == "upsert":
                r = requests.post(
                    self.url,
                    params=params,
                    json={"payload_json": json.dumps(payload or {}, ensure_ascii=False)},
                    timeout=30,
                )
            else:
                r = requests.get(self.url, params=params, timeout=30)

            return r.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def list_names(self, sheet: str):
        d = self._call("list", sheet)
        return list(d.get("items") or []) if d.get("ok") else []

    def get_payload(self, sheet: str, name: str):
        d = self._call("get", sheet, name=name)
        if not d.get("ok"):
            return None
        raw = d.get("payload_json") or ""
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return None

    def create_only(self, sheet: str, name: str, payload: dict):
        if name in self.list_names(sheet):
            return False, "同名模板已存在，請改名後再儲存。"
        d = self._call("upsert", sheet, name=name, payload=payload)
        return (True, "已儲存") if d.get("ok") else (False, f"儲存失敗：{d.get('error','未知錯誤')}")

    def upsert(self, sheet: str, name: str, payload: dict):
        d = self._call("upsert", sheet, name=name, payload=payload)
        return (True, "已更新") if d.get("ok") else (False, f"更新失敗：{d.get('error','未知錯誤')}")

    def delete(self, sheet: str, name: str):
        d = self._call("delete", sheet, name=name)
        return (True, "已刪除") if d.get("ok") else (False, f"刪除失敗：{d.get('error','未知錯誤')}")

gas = GASClient(GAS_URL, GAS_TOKEN)
#------A006：Google Apps Script(GAS) API Client(結束)：------


#------A006b：GAS 快取輔助（list/get/save/delete + clear cache）(開始)：------
@st.cache_resource(show_spinner=False)
def _get_gas_client(url: str, token: str):
    """建立並快取 GASClient；若未設定 URL/TOKEN，回傳 None。"""
    url = (url or "").strip()
    token = (token or "").strip()
    if not url or not token:
        return None
    return GASClient(url, token)

def _gas_ready() -> bool:
    """目前是否可用 GAS（已設定 URL/TOKEN 且連線正常）。"""
    try:
        c = _get_gas_client(GAS_URL, GAS_TOKEN)
        return bool(c and c.ready())
    except Exception:
        return False

@st.cache_data(show_spinner=False, ttl=60)
def _cache_gas_list(url: str, token: str, sheet: str):
    c = _get_gas_client(url, token)
    if not c:
        return []
    return c.list_templates(sheet)

@st.cache_data(show_spinner=False, ttl=60)
def _cache_gas_get(url: str, token: str, sheet: str, name: str):
    c = _get_gas_client(url, token)
    if not c:
        return None
    return c.get_template(sheet, name)

def _gas_save(url: str, token: str, sheet: str, name: str, payload: dict):
    c = _get_gas_client(url, token)
    if not c:
        raise RuntimeError("GAS_URL / GAS_TOKEN 未設定，無法儲存模板")
    return c.save_template(sheet, name, payload)

def _gas_delete(url: str, token: str, sheet: str, name: str):
    c = _get_gas_client(url, token)
    if not c:
        raise RuntimeError("GAS_URL / GAS_TOKEN 未設定，無法刪除模板")
    return c.delete_template(sheet, name)

def _gas_cache_clear():
    """當你儲存/刪除後，清掉 list/get 的快取，避免畫面顯示舊資料。"""
    try:
        _cache_gas_list.clear()
    except Exception:
        pass
    try:
        _cache_gas_get.clear()
    except Exception:
        pass
#------A006b：GAS 快取輔助（list/get/save/delete + clear cache）(結束)：------


#------A007：Action/真防呆遮罩系統（整段可取代 / 修正 _has_action NameError / 真更新 / 全頁遮罩）(開始)：------
import time
import streamlit as st

# 這個 action 系統的設計：
# 1) 按鈕被按下的當輪：只做 _trigger() -> 立刻 rerun
# 2) 下一輪：先顯示遮罩（整頁不可操作）-> 再執行耗時工作 -> 結束後清 action -> rerun
# => 你要的「真的在運作中才防呆、結束後才解除」就是靠這樣做

_ACTION_KEY = "__action__"
_OVERLAY_KEY = "__overlay__"
_LAST_DONE_KEY = "__action_last_done_ts__"

def _ensure_action_defaults():
    if _ACTION_KEY not in st.session_state:
        st.session_state[_ACTION_KEY] = None
    if _OVERLAY_KEY not in st.session_state:
        st.session_state[_OVERLAY_KEY] = False
    if _LAST_DONE_KEY not in st.session_state:
        st.session_state[_LAST_DONE_KEY] = 0.0

def _has_action() -> bool:
    _ensure_action_defaults()
    return st.session_state.get(_ACTION_KEY) is not None

def _get_action() -> dict | None:
    _ensure_action_defaults()
    a = st.session_state.get(_ACTION_KEY)
    return a if isinstance(a, dict) else None

def _clear_action():
    _ensure_action_defaults()
    st.session_state[_ACTION_KEY] = None
    st.session_state[_OVERLAY_KEY] = False
    st.session_state[_LAST_DONE_KEY] = time.time()

def _trigger(action_name: str, message: str = "處理中，請稍候...", payload: dict | None = None):
    """
    ✅ 按鈕當輪呼叫：只登記 action + 開遮罩 + rerun
    """
    _ensure_action_defaults()
    st.session_state[_ACTION_KEY] = {
        "name": action_name,
        "message": message,
        "payload": payload or {},
        "ts": time.time(),
    }
    st.session_state[_OVERLAY_KEY] = True
    st.rerun()

def _render_fullpage_overlay(message: str = "處理中，請稍候..."):
    """
    ✅ 全頁遮罩：視覺上 + 操作上都不可點（靠 pointer-events）
    """
    st.markdown(
        """
        <style>
        .yimimi-overlay {
            position: fixed;
            inset: 0;
            background: rgba(255,255,255,0.85);
            z-index: 999999;
            display: flex;
            align-items: center;
            justify-content: center;
            pointer-events: all;
        }
        .yimimi-overlay-card{
            background: white;
            border: 1px solid rgba(0,0,0,0.08);
            border-radius: 12px;
            padding: 16px 18px;
            min-width: 280px;
            box-shadow: 0 8px 28px rgba(0,0,0,0.10);
            text-align: center;
        }
        .yimimi-overlay-title{
            font-size: 16px;
            font-weight: 700;
            margin-bottom: 10px;
        }
        .yimimi-overlay-sub{
            font-size: 13px;
            opacity: 0.75;
            margin-top: 8px;
        }
        .yimimi-spinner{
            width: 34px;
            height: 34px;
            border-radius: 999px;
            border: 4px solid rgba(0,0,0,0.10);
            border-top-color: rgba(0,0,0,0.55);
            animation: yimimi-spin 0.9s linear infinite;
            margin: 0 auto;
        }
        @keyframes yimimi-spin { to { transform: rotate(360deg); } }
        </style>
        """,
        unsafe_allow_html=True,
    )

    safe_msg = (message or "處理中，請稍候...").replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(
        f"""
        <div class="yimimi-overlay">
          <div class="yimimi-overlay-card">
            <div class="yimimi-spinner"></div>
            <div class="yimimi-overlay-title">{safe_msg}</div>
            <div class="yimimi-overlay-sub">請勿重新整理或切換模板，系統正在更新資料…</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def _loading_watchdog(timeout_sec: int = 60):
    """
    ✅ 避免遮罩卡死（例如 action 執行中爆錯，下一輪還卡著）
    - 超過 timeout 就自動解除遮罩 + 清 action
    """
    _ensure_action_defaults()
    a = _get_action()
    if not a:
        return
    ts = float(a.get("ts", 0) or 0)
    if ts and (time.time() - ts) > timeout_sec:
        st.warning("⚠ 讀取逾時，已自動解除防呆。請再操作一次。")
        _clear_action()
        st.rerun()

def _handle_action(handlers: dict[str, callable]):
    """
    ✅ 在 main() 一開始呼叫（越早越好）：
    - 這輪如果有 action：先顯示遮罩 -> 執行對應 handler -> 完成後 rerun
    """
    _ensure_action_defaults()

    a = _get_action()
    if not a:
        return

    # 先顯示遮罩（這輪 UI 一開始就看到）
    msg = a.get("message") or "處理中，請稍候..."
    if st.session_state.get(_OVERLAY_KEY, False):
        _render_fullpage_overlay(msg)

    name = a.get("name")
    payload = a.get("payload") or {}

    # 執行 handler
    fn = handlers.get(name)
    try:
        if fn is None:
            raise NameError(f"找不到 action handler：{name}")
        fn(payload)  # 真正耗時工作放這裡
        _clear_action()
        st.rerun()
    except Exception as e:
        # 失敗：解除遮罩/清 action，但不要整頁白掉
        st.session_state[_OVERLAY_KEY] = False
        st.session_state[_ACTION_KEY] = None
        st.error(f"❌ 執行失敗：{e}")
        # 不強制 rerun，讓錯誤留在畫面上

#------A007：Action/真防呆遮罩系統（整段可取代 / 修正 _has_action NameError / 真更新 / 全頁遮罩）(結束)：------



#------A008：初始化 Session State（_ensure_defaults 安全版）(開始)：------
from datetime import datetime

def _ensure_defaults():
    # ---- 時間來源：有 _now_tw 用 _now_tw，沒有就用本機 now ----
    try:
        now = _now_tw()  # type: ignore
    except Exception:
        now = datetime.now()

    # ---- 基本狀態 ----
    if "order_name" not in st.session_state or not st.session_state.get("order_name"):
        st.session_state.order_name = f"訂單_{now.strftime('%Y%m%d')}"

    # 版面配置
    if "layout_mode" not in st.session_state:
        st.session_state.layout_mode = "左右50/50"

    # DataFrame（外箱/商品）確保存在
    if "df_box" not in st.session_state or st.session_state.df_box is None:
        st.session_state.df_box = pd.DataFrame(columns=["選取", "名稱", "長", "寬", "高", "數量", "空箱重量"])

    if "df_prod" not in st.session_state or st.session_state.df_prod is None:
        st.session_state.df_prod = pd.DataFrame(columns=["選取", "商品名稱", "長", "寬", "高", "重量(kg)", "數量"])

    # 模板狀態
    if "active_box_tpl" not in st.session_state:
        st.session_state.active_box_tpl = "未選擇"
    if "active_prod_tpl" not in st.session_state:
        st.session_state.active_prod_tpl = "未選擇"

    # 計算結果暫存
    if "pack_result" not in st.session_state:
        st.session_state.pack_result = None

    # Loading / Action（若你有用防呆遮罩）
    if "_loading" not in st.session_state:
        st.session_state._loading = False
    if "_loading_msg" not in st.session_state:
        st.session_state._loading_msg = ""
    if "_action" not in st.session_state:
        st.session_state._action = None

#------A008：初始化 Session State（_ensure_defaults 安全版）(結束)：------



#------A009：外箱/商品 模板 payload 轉換(開始)：------
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
    if not isinstance(rows,list): 
        raise ValueError('rows is not list')
    out=[]
    for r in rows:
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
    if not isinstance(rows,list): 
        raise ValueError('rows is not list')
    out=[]
    for r in rows:
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
#------A009：外箱/商品 模板 payload 轉換(結束)：------


#------A010：模板區塊 UI（載入 / 儲存 / 刪除）(開始)：------
def template_block(title:str, sheet:str, active_key:str, df_key:str, to_payload, from_payload, key_prefix:str):
    st.markdown(f"### {title}（載入 / 儲存 / 刪除）")
    if not gas.ready:
        st.info('尚未設定 Streamlit Secrets（GAS_URL / GAS_TOKEN）。模板功能暫停。')
        return

    loading = _is_loading()
    names = ['(無)'] + sorted(_cache_gas_list(GAS_URL, GAS_TOKEN, sheet))

    c1, c2 = st.columns([1, 1], gap='medium')
    c3 = st.container()

    with c1:
        sel = st.selectbox('選擇模板', names, key=f'{key_prefix}_sel', disabled=loading)
        load_btn = st.button('⬇️ 載入模板', use_container_width=True, key=f'{key_prefix}_load', disabled=loading)
    with c2:
        del_sel = st.selectbox('要刪除的模板', names, key=f'{key_prefix}_del_sel', disabled=loading)
        del_btn = st.button('🗑️ 刪除模板', use_container_width=True, key=f'{key_prefix}_del', disabled=loading)
    with c3:
        new_name = st.text_input('另存為模板名稱', placeholder='例如：常用A', key=f'{key_prefix}_new', disabled=loading)
        save_btn = st.button('💾 儲存模板', use_container_width=True, key=f'{key_prefix}_save', disabled=loading)

    # ===== 動作：載入 =====
    if load_btn:
        if sel == '(無)':
            st.warning('請先選擇要載入的模板')
        else:
            def _do_load():
                payload = _cache_gas_get(GAS_URL, GAS_TOKEN, sheet, sel)
                if payload is None:
                    st.error('載入失敗：請確認雲端連線 / 權限')
                    return
                df_loaded = from_payload(payload)
                st.session_state[df_key] = df_loaded
                st.session_state[active_key] = sel

                # 同步 live df：確保 3D 計算一定讀到最新資料
                if df_key == 'df_box':
                    st.session_state['_box_live_df'] = df_loaded.copy()
                    st.session_state.pop('box_editor', None)
                if df_key == 'df_prod':
                    st.session_state['_prod_live_df'] = df_loaded.copy()
                    st.session_state.pop('prod_editor', None)

                _gas_cache_clear()
                st.success(f'已載入：{sel}')

            _with_fullpage_lock('讀取模板中...', _do_load)
            _force_rerun()

    # ===== 動作：儲存 =====
    if save_btn:
        nm = (new_name or '').strip()
        if not nm:
            st.warning('請先輸入「另存為模板名稱」')
        else:
            def _do_save():
                ok, msg = gas.create_only(sheet, nm, to_payload(st.session_state[df_key]))
                if ok:
                    st.session_state[active_key] = nm
                    _gas_cache_clear()
                    st.success(msg)
                else:
                    st.error(msg)

            _with_fullpage_lock('儲存模板中...', _do_save)
            _force_rerun()

    # ===== 動作：刪除 =====
    if del_btn:
        if del_sel == '(無)':
            st.warning('請先選擇要刪除的模板')
        else:
            def _do_delete():
                ok, msg = gas.delete(sheet, del_sel)
                if ok:
                    if st.session_state.get(active_key) == del_sel:
                        st.session_state[active_key] = ''
                    _gas_cache_clear()
                    st.success(msg)
                else:
                    st.error(msg)

            _with_fullpage_lock('刪除模板中...', _do_delete)
            _force_rerun()

    st.caption(f"目前套用：{st.session_state.get(active_key) or '未選擇'}")
#------A010：模板區塊 UI（載入 / 儲存 / 刪除）(結束)：------



#------A011：外箱表格 UI（Data Editor + 操作按鈕）(開始)：------
def box_table_block():
    st.markdown('### 箱型表格（勾選=參與計算；勾選後可刪除）')
    st.markdown('<div class="muted">只保留一個「選取」欄：要參與裝箱就勾選；要刪除就勾選後按「刪除勾選」。</div>', unsafe_allow_html=True)

    loading = _is_loading()
    df = _sanitize_box(st.session_state.df_box)

    st.markdown('<div class="loading-wrap">', unsafe_allow_html=True)
    if loading:
        # ✅ 讀取中：禁止操作（不顯示可編輯 editor）
        st.info('資料讀取中…外箱表格暫時不可操作')
        st.markdown(_loading_overlay_html(), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        return

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

    # ✅ 每次畫面更新都保存「當下表格」給 3D 計算使用
    st.session_state['_box_live_df'] = edited.copy()

    b1, b2, b3 = st.columns([1, 1, 1], gap='medium')
    with b1:
        apply_btn = st.button('✅ 套用變更（外箱表格）', use_container_width=True, key='box_apply', disabled=loading)
    with b2:
        del_btn = st.button('🗑️ 刪除勾選', use_container_width=True, key='box_del', disabled=loading)
    with b3:
        clear_btn = st.button('🧹 清除全部外箱', use_container_width=True, key='box_clear', disabled=loading)

    if apply_btn:
        _begin_loading('套用外箱變更中...')
        try:
            clean = _sanitize_box(edited)
            st.session_state.df_box = clean
            st.session_state['_box_live_df'] = clean.copy()

            if gas.ready and (st.session_state.get('active_box_tpl') or '').strip():
                tpl = st.session_state['active_box_tpl']
                ok, msg = gas.upsert(SHEET_BOX, tpl, _box_payload(clean))
                if ok:
                    st.success(f'已套用並同步更新模板：{tpl}')
                else:
                    st.error(msg)
            else:
                st.success('已套用外箱表格變更')

            _gas_cache_clear()
            _force_rerun()
        finally:
            _end_loading()

    if del_btn:
        _begin_loading('刪除外箱中...')
        try:
            d = _sanitize_box(edited)
            d = d[~d['選取']].reset_index(drop=True)
            d = _sanitize_box(d)
            st.session_state.df_box = d
            st.session_state['_box_live_df'] = d.copy()
            st.success('已刪除勾選外箱')
            _force_rerun()
        finally:
            _end_loading()

    if clear_btn:
        _begin_loading('清除外箱中...')
        try:
            empty = pd.DataFrame(columns=['選取','名稱','長','寬','高','數量','空箱重量'])
            st.session_state.df_box = empty
            st.session_state.active_box_tpl = ''
            st.session_state['_box_live_df'] = empty.copy()
            st.success('已清空全部外箱，並清除「目前套用」狀態')
            _force_rerun()
        finally:
            _end_loading()

    st.markdown('</div>', unsafe_allow_html=True)
#------A011：外箱表格 UI（Data Editor + 操作按鈕）(結束)：------



#------A012：商品表格 UI（Data Editor + 操作按鈕）(開始)：------
def prod_table_block():
    st.markdown('### 商品表格（勾選=參與計算；勾選後可刪除）')
    st.markdown('<div class="muted">只保留一個「選取」欄：要參與裝箱就勾選；要刪除就勾選後按「刪除勾選」。</div>', unsafe_allow_html=True)

    loading = _is_loading()
    df = _sanitize_prod(st.session_state.df_prod)

    st.markdown('<div class="loading-wrap">', unsafe_allow_html=True)
    if loading:
        st.info('資料讀取中…商品表格暫時不可操作')
        st.markdown(_loading_overlay_html(), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        return

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

    # ✅ 每次畫面更新都保存「當下表格」給 3D 計算使用
    st.session_state['_prod_live_df'] = edited.copy()

    b1, b2, b3 = st.columns([1, 1, 1], gap='medium')
    with b1:
        apply_btn = st.button('✅ 套用變更（商品表格）', use_container_width=True, key='prod_apply', disabled=loading)
    with b2:
        del_btn = st.button('🗑️ 刪除勾選', use_container_width=True, key='prod_del', disabled=loading)
    with b3:
        clear_btn = st.button('🧹 清除全部商品', use_container_width=True, key='prod_clear', disabled=loading)

    if apply_btn:
        _begin_loading('套用商品變更中...')
        try:
            clean = _sanitize_prod(edited)
            st.session_state.df_prod = clean
            st.session_state['_prod_live_df'] = clean.copy()

            if gas.ready and (st.session_state.get('active_prod_tpl') or '').strip():
                tpl = st.session_state['active_prod_tpl']
                ok, msg = gas.upsert(SHEET_PROD, tpl, _prod_payload(clean))
                if ok:
                    st.success(f'已套用並同步更新模板：{tpl}')
                else:
                    st.error(msg)
            else:
                st.success('已套用商品表格變更')

            _gas_cache_clear()
            _force_rerun()
        finally:
            _end_loading()

    if del_btn:
        _begin_loading('刪除商品中...')
        try:
            d = _sanitize_prod(edited)
            d = d[~d['選取']].reset_index(drop=True)
            d = _sanitize_prod(d)
            st.session_state.df_prod = d
            st.session_state['_prod_live_df'] = d.copy()
            st.success('已刪除勾選商品')
            _force_rerun()
        finally:
            _end_loading()

    if clear_btn:
        _begin_loading('清除商品中...')
        try:
            empty = pd.DataFrame(columns=['選取','商品名稱','長','寬','高','重量(kg)','數量'])
            st.session_state.df_prod = empty
            st.session_state.active_prod_tpl = ''
            st.session_state['_prod_live_df'] = empty.copy()
            st.success('已清空全部商品，並清除「目前套用」狀態')
            _force_rerun()
        finally:
            _end_loading()

    st.markdown('</div>', unsafe_allow_html=True)
#------A012：商品表格 UI（Data Editor + 操作按鈕）(結束)：------




#------A013：模板區塊 template_block（修正 NameError/恢復模板讀取/真更新）(開始)：------
import streamlit as st

def template_block(title: str, sheet: str, active_key: str, df_key: str,
                   build_payload_fn, apply_payload_fn, tpl_key_prefix: str):
    """
    你原本 main() 裡呼叫的 template_block(...) 用這版取代。
    - build_payload_fn(): 由目前資料組成要存的 payload(dict)
    - apply_payload_fn(payload): 把讀到的 payload 套用回 session_state / df
    """

    st.markdown(f"### {title}")

    gas = _get_gas_client()
    if not gas:
        st.warning("⚠ 模板功能未啟用：讀不到 GAS_URL（Secrets 仍維持你原本的 key，不會被我改）。")
        return

    colL, colR = st.columns(2)

    # 左：選擇模板 + 載入
    with colL:
        names = ["(無)"] + _cache_gas_list(sheet)
        cur = st.session_state.get(active_key, "(無)")
        if cur not in names:
            cur = "(無)"

        sel = st.selectbox(
            "選擇模板",
            options=names,
            index=names.index(cur) if cur in names else 0,
            key=f"{tpl_key_prefix}_sel",
        )

        if st.button("⬇️ 載入模板", use_container_width=True, key=f"{tpl_key_prefix}_btn_load"):
            if sel == "(無)":
                st.info("請先選擇要載入的模板。")
            else:
                payload = _cache_gas_read(sheet, sel)
                if not payload:
                    st.error("讀取失敗或模板內容為空。")
                else:
                    try:
                        apply_payload_fn(payload)
                        st.session_state[active_key] = sel
                        st.success(f"已載入：{sel}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"套用模板失敗：{e}")

    # 右：刪除模板
    with colR:
        del_names = ["(無)"] + _cache_gas_list(sheet)
        del_sel = st.selectbox(
            "要刪除的模板",
            options=del_names,
            key=f"{tpl_key_prefix}_del_sel",
        )
        if st.button("🗑️ 刪除模板", use_container_width=True, key=f"{tpl_key_prefix}_btn_del"):
            if del_sel == "(無)":
                st.info("請先選擇要刪除的模板。")
            else:
                ok, msg = _gas_delete(sheet, del_sel)
                if ok:
                    if st.session_state.get(active_key) == del_sel:
                        st.session_state[active_key] = "(無)"
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    # 另存新模板名稱 + 儲存
    save_name = st.text_input("另存為模板名稱", key=f"{tpl_key_prefix}_save_name", placeholder="例如：常用A")
    if st.button("💾 儲存模板", use_container_width=True, key=f"{tpl_key_prefix}_btn_save"):
        name = (save_name or "").strip()
        if not name:
            st.info("請輸入要儲存的模板名稱。")
        else:
            try:
                payload = build_payload_fn()
                ok, msg = _gas_write(sheet, name, payload)
                if ok:
                    st.session_state[active_key] = name
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            except Exception as e:
                st.error(f"組合資料失敗：{e}")
#------A013：模板區塊 template_block（修正 NameError/恢復模板讀取/真更新）(結束)：------



#------A014：3D 圖表建立（Plotly）(開始)：------
def build_3d_fig(box:Dict[str,Any], fitted:List[Item], color_map:Dict[str,str]=None)->go.Figure:
    fig=go.Figure()

    # 統一座標：x=長(L), y=寬(W), z=高(H)
    L=float(box['l']); W=float(box['w']); H=float(box['h'])

    # 外箱框線
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
        # ✅ py3dbp 旋轉後尺寸（避免你看到融合/穿透/大小不對）
        if hasattr(it,'get_dimension'):
            d=it.get_dimension()  # (w,h,d)
            return float(d[0]),float(d[1]),float(d[2])
        return float(it.width),float(it.height),float(it.depth)

    # 若未提供 color_map，就用 fitted 自己建立（但你現在會由 A016 提供，才能跨箱一致）
    if color_map is None:
        palette=['#2F3A4A','#4C6A92','#6C757D','#8E9AAF','#A3B18A','#B08968','#C9ADA7','#6D6875']
        color_map={}
        ci=0
        for it in fitted:
            base=_base_name(getattr(it,'name',''))
            if base not in color_map:
                color_map[base]=palette[ci%len(palette)]
                ci += 1

    # 畫商品：實心、不透明、加邊框
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

        item_edges=[(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
        for a,b in item_edges:
            fig.add_trace(go.Scatter3d(
                x=[vx[a],vx[b]],y=[vy[a],vy[b]],z=[vz[a],vz[b]],
                mode='lines', line=dict(width=3,color='#000'),
                hoverinfo='skip', showlegend=False
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
#------A014：3D 圖表建立（Plotly）(結束)：------



#------A015：HTML 報告輸出（含 Plotly 內嵌）(開始)：------
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

    # 未裝入警示
    warn=''
    if unfitted:
        counts={}
        for it in unfitted:
            base=str(it.name).split('_')[0]
            counts[base]=counts.get(base,0)+1
        warn="<div class='warn'><b>注意：</b>有部分商品裝不下！（可能是箱型庫存不足或尺寸不夠）</div>"+''.join(
            [f"<div class='warn2'>⚠ {k}：超過 {v} 個</div>" for k,v in counts.items()]
        )

    # Legend（同 Streamlit）
    legend_items=''.join([
        f"<div class='legrow'><span class='sw' style='background:{c}'></span>{k}</div>"
        for k,c in color_map.items()
    ])

    # 每箱圖
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
      <div>📦 <b>使用箱數</b>　<b>{len(packed_bins)}</b> 箱（可混用不同箱型）</div>
      <div>⚖️ <b>內容淨重</b>　{content_wt:.2f} kg</div>
      <div>🔴 <b>本次總重</b>　{total_wt:.2f} kg</div>
      <div>📊 <b>整體空間利用率</b>　{util:.2f}%</div>
    </div>
    {warn}
  </div>
  {body}
</div>
</body></html>"""
#------A015：HTML 報告輸出（含 Plotly 內嵌）(結束)：------



#------A016：裝箱計算核心（py3dbp）+ 統計(開始)：------
def pack_and_render(order_name:str, df_box:pd.DataFrame, df_prod:pd.DataFrame)->Dict[str,Any]:
    bins=_build_bins(df_box)
    if not bins:
        return {'ok':False,'error':'請至少勾選 1 個外箱（且數量>0、尺寸>0）'}

    items=_build_items(df_prod)
    if not items:
        return {'ok':False,'error':'請至少勾選 1 個商品（且數量>0、尺寸>0）'}

    # 固定配色：依商品表格順序（跨箱一致）
    palette=['#2F3A4A','#4C6A92','#6C757D','#8E9AAF','#A3B18A','#B08968','#C9ADA7','#6D6875']
    def _base_name(n:str)->str:
        n=str(n or '')
        return n.rsplit('_',1)[0] if '_' in n else n

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

    def _rot_dim(it:Item):
        if hasattr(it,'get_dimension'):
            d=it.get_dimension()
            return float(d[0]),float(d[1]),float(d[2])
        return float(it.width),float(it.height),float(it.depth)

    remaining=list(items)
    packed=[]  # [{'box':..., 'name':..., 'items':[Item...]}]

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

    used_item_vol=sum((_rot_dim(it)[0]*_rot_dim(it)[1]*_rot_dim(it)[2]) for it in all_fitted)
    used_box_vol=sum(float(p['box']['l']*p['box']['w']*p['box']['h']) for p in packed)
    util=(used_item_vol/used_box_vol*100.0) if used_box_vol>0 else 0.0
    util=max(0.0, min(100.0, util))

    # 預設 3D：第一箱（但 UI 會顯示多箱）
    if packed:
        fig=build_3d_fig(packed[0]['box'], packed[0]['items'], color_map=color_map)
    else:
        fig=go.Figure()

    # 給 UI 用（下拉/多圖）
    class _MiniBin:
        def __init__(self, name, items):
            self.name=name
            self.items=items

    packer_bins=[_MiniBin(p['name'], p['items']) for p in packed]
    bins_input=[p['box'] for p in packed]

    # 先回傳，HTML 由 A018 呼叫 A015 生成（確保與畫面一致）
    return {
        'ok':True,
        'bins_input': bins_input,
        'packer_bins': packer_bins,
        'packed_bins': packed,       # ✅ 每箱使用/件數/內容
        'used_bin_count': len(packed),
        'unfitted': unfitted,
        'content_wt': content_wt,
        'total_wt': total_wt,
        'util': util,
        'fig': fig,
        'color_map': color_map,
        'report_html': ''            # ✅ 由 A018 生成（避免與畫面不一致）
    }
#------A016：裝箱計算核心（py3dbp）+ 統計(結束)：------




#------A017：商品總件數統計(用於檔名)(開始)：------
def _total_items(df_prod:pd.DataFrame)->int:
    if df_prod is None or df_prod.empty: 
        return 0
    sel=df_prod['選取'].astype(bool)
    return int(df_prod.loc[sel,'數量'].apply(lambda x:int(_to_float(x,0))).sum())
#------A017：商品總件數統計(用於檔名)(結束)：------


#------A018：結果區塊 UI（開始計算 + 顯示結果 + 下載HTML）(開始)：------
def result_block():
    # 先顯示標題
    st.markdown("## 3. 裝箱結果與模擬")

    # ✅ 第二段：如果上一輪按了按鈕，這輪就在這裡真的執行（遮罩已經在上一輪立刻出現）
    def _do_run_3d(_payload: dict):
        # 這裡用你檔案內「已存在」的 pack_and_render
        # 重要：請不要在 st.button 當輪直接跑，避免遮罩慢半拍
        try:
            df_box = st.session_state.get("df_box")
            df_prod = st.session_state.get("df_prod")
            # 如果你有前面 sanitize，這裡也可以再保護一次
            if df_box is None or df_prod is None:
                raise RuntimeError("找不到 df_box / df_prod，請先確認外箱與商品表格已有資料。")

            # ✅ 真正耗時計算
            pack_and_render()

        finally:
            # pack_and_render() 裡若會寫入 st.session_state.pack_result / report_html 等，就讓它自然更新
            pass

    _handle_action({
        "RUN_3D": _do_run_3d,
    })

    # ✅ 第一段：按下按鈕立刻出現遮罩，下一輪才做耗時工作
    if st.button(
        "🚀 開始計算與 3D 模擬",
        use_container_width=True,
        key=f"btn_run3d_{_get_render_nonce()}",
        disabled=bool(st.session_state.get("_loading")),
    ):
        _trigger("RUN_3D", "正在計算與產生 3D 模擬，請稍候...")

    # ====== 以下渲染結果 ======
    res = st.session_state.get("pack_result")
    if not res:
        st.info("尚未計算 3D。請按上方「開始計算與 3D 模擬」。")
        return

    figs = res.get("figs") or []
    boxes = res.get("boxes") or []
    color_map = res.get("color_map") or {}  # 你的顏色對照表（若有）

    # ✅ legend（分類顏色說明）如果你本來有一段 legend_html，就沿用
    # 這裡用最保險方式：有 legend_html 就顯示，沒有就顯示 color_map
    legend_html = res.get("legend_html")

    run_id = _get_render_nonce()  # 每次 action 結束會 bump，避免 key 撞

    # ✅ 頁籤標題：顯示每箱件數
    tab_titles = []
    for i, b in enumerate(boxes):
        title = b.get("title") or b.get("name") or f"外箱{i+1}"
        cnt = b.get("count")
        tab_titles.append(f"{title}（{cnt}件）" if cnt is not None else title)

    tabs = st.tabs(tab_titles if tab_titles else ["外箱1"])

    for i, t in enumerate(tabs):
        with t:
            c1, c2 = st.columns([0.25, 0.75], gap="large")

            with c1:
                st.markdown("### 分類顏色說明")
                if legend_html:
                    st.markdown(legend_html, unsafe_allow_html=True)
                else:
                    if not color_map:
                        st.caption("（尚無分類顏色資料）")
                    else:
                        for k, v in color_map.items():
                            st.markdown(f"- **{k}**：`{v}`")

                # ✅ 每箱資訊
                if i < len(boxes):
                    bi = boxes[i]
                    st.markdown("### 本箱資訊")
                    st.write(f"裝入件數：**{bi.get('count', 0)}** 件")
                    if bi.get("name") or bi.get("title"):
                        st.write(f"箱型：**{bi.get('name') or bi.get('title')}**")

            with c2:
                if i < len(figs) and figs[i] is not None:
                    # ✅ 這裡「一定要 key」，避免箱子多/商品多就爆 DuplicateElementId
                    st.plotly_chart(
                        figs[i],
                        use_container_width=True,
                        key=f"plotly_box_{run_id}_{i}",
                    )
                else:
                    st.info("此箱沒有 3D 圖可顯示。")
#------A018：結果區塊 UI（開始計算 + 顯示結果 + 下載HTML）(結束)：------



#------A019：主程式 UI（版面配置：左右 / 上下）(開始)：------
def main():
    _loading_watchdog(timeout_sec=60)  # ✅ 避免 loading 卡死造成一直遮罩

    _ensure_defaults()

    # ✅ 先處理 pending action（會顯示全頁遮罩並執行 IO）
    if _has_action():
        _handle_pending_action()
        return

    # ✅ 若正在 loading（保險）
    if _is_loading():
        _render_fullpage_overlay()
        return

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

    # ✅ 這裡就是你原本的訂單名稱輸入（不再呼叫 order_block）
    st.text_input('訂單名稱', key='order_name')

    if st.session_state.layout_mode == '左右 50% / 50%':
        left, right = st.columns([1,1], gap='large')
        with left:
            st.markdown('## 1. 訂單與外箱')
            template_block('箱型模板（載入 / 儲存 / 刪除）', SHEET_BOX, 'active_box_tpl', 'df_box',
                           _box_payload, _box_from, 'box_tpl_v')
            box_table_block()

        with right:
            st.markdown('## 2. 商品清單')
            template_block('商品模板（載入 / 儲存 / 刪除）', SHEET_PROD, 'active_prod_tpl', 'df_prod',
                           _prod_payload, _prod_from, 'prod_tpl_v')
            prod_table_block()

        st.divider()
        result_block()

    else:
        st.markdown('## 1. 訂單與外箱')
        template_block('箱型模板（載入 / 儲存 / 刪除）', SHEET_BOX, 'active_box_tpl', 'df_box',
                       _box_payload, _box_from, 'box_tpl_v')
        box_table_block()

        st.divider()

        st.markdown('## 2. 商品清單')
        template_block('商品模板（載入 / 儲存 / 刪除）', SHEET_PROD, 'active_prod_tpl', 'df_prod',
                       _prod_payload, _prod_from, 'prod_tpl_v')
        prod_table_block()

        st.divider()
        result_block()
#------A019：主程式 UI（版面配置：左右 / 上下）(結束)：------


#------A020：程式入口（避免覆蓋 main / 防止白屏）(開始)：------
# ⚠️ 不要再定義第二個 main()，會覆蓋 A019 的主程式 main()
# Streamlit 需要在檔案最後呼叫一次 main() 才會渲染 UI

main()
#------A020：程式入口（避免覆蓋 main / 防止白屏）(結束)：------
