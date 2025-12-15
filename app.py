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



#------A003：通用工具（時間/轉型/安全字串）(開始)：------
def _now_tw() -> datetime:
    """台灣時間 now()（避免 NameError）"""
    return datetime.now(ZoneInfo("Asia/Taipei"))

def _to_float(x, default: float = 0.0) -> float:
    """把各種輸入安全轉 float（支援 '', None, '1,234', ' 12 '）"""
    try:
        if x is None:
            return default
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "":
            return default
        s = s.replace(",", "")
        return float(s)
    except Exception:
        return default

def _safe_name(s: str, fallback: str = "report") -> str:
    """給檔名/模板名用：移除不合法字元"""
    s = (s or "").strip()
    if not s:
        return fallback
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or fallback
#------A003：通用工具（時間/轉型/安全字串）(結束)：------



#------A004：全頁防呆遮罩（loading overlay + watchdog 防白屏）(開始)：------
import time

def _is_loading() -> bool:
    # ✅ 嚴格只接受 True，避免 "True"/1/None 亂入造成誤判
    return st.session_state.get("_loading", False) is True

def _set_loading(flag: bool, msg: str = "資料處理中..."):
    st.session_state["_loading"] = (flag is True)
    st.session_state["_loading_msg"] = msg or "資料處理中..."
    if flag is True:
        st.session_state["_loading_since"] = time.time()
    else:
        st.session_state.pop("_loading_since", None)

def _loading_msg() -> str:
    return str(st.session_state.get("_loading_msg") or "資料處理中...")

def _loading_watchdog(timeout_sec: int = 60):
    """
    ✅ 防止卡死白屏：如果 loading 超過 timeout_sec，強制解除
    """
    if not _is_loading():
        return
    since = st.session_state.get("_loading_since", None)
    if since is None:
        # 沒有時間戳也別卡住
        _set_loading(False, "")
        return
    if time.time() - float(since) > float(timeout_sec):
        st.session_state["_last_3d_error"] = "系統偵測到操作逾時，已自動解除讀取鎖定（請再試一次）。"
        _set_loading(False, "")

def _overlay_html(msg: str) -> str:
    m = msg or "資料處理中..."
    # ✅ 遮罩一定看得到，不會「白白一片」
    return f"""
    <style>
      .fullpage-overlay {{
        position: fixed; inset: 0;
        background: rgba(255,255,255,.72);
        z-index: 999999;
        display: flex; align-items: center; justify-content: center;
        pointer-events: all;
      }}
      .fullpage-box {{
        min-width: 260px;
        padding: 16px 20px;
        border-radius: 14px;
        border: 1px solid rgba(0,0,0,.10);
        background: rgba(255,255,255,.95);
        box-shadow: 0 8px 28px rgba(0,0,0,.12);
        color: rgba(0,0,0,.85);
        font-size: 16px;
        line-height: 1.4;
        text-align: center;
      }}
      .fullpage-sub {{
        margin-top: 8px;
        font-size: 12px;
        color: rgba(0,0,0,.55);
      }}
      .fullpage-spin {{
        display:inline-block;
        width:18px;height:18px;
        border:2px solid rgba(0,0,0,.18);
        border-top-color: rgba(0,0,0,.55);
        border-radius: 50%;
        animation: spin 0.9s linear infinite;
        vertical-align: -3px;
        margin-right: 8px;
      }}
      @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    </style>
    <div class="fullpage-overlay">
      <div class="fullpage-box">
        <span class="fullpage-spin"></span>{html.escape(m)}
        <div class="fullpage-sub">請稍候，完成後才能繼續操作</div>
      </div>
    </div>
    """

def _render_fullpage_overlay():
    # ✅ 每次 render 前先跑 watchdog，避免卡住白屏
    _loading_watchdog(timeout_sec=60)
    if _is_loading():
        st.markdown(_overlay_html(_loading_msg()), unsafe_allow_html=True)
#------A004：全頁防呆遮罩（loading overlay + watchdog 防白屏）(結束)：------


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



#------A006：GASClient（Google Apps Script API 客戶端/避免 NameError）(開始)：------
import os
import requests

def _get_secret(name: str, default: str = "") -> str:
    """
    ✅ 先讀 st.secrets，再讀環境變數，避免本機/雲端不同環境造成爆炸
    """
    try:
        v = st.secrets.get(name, None)
        if v is not None:
            return str(v)
    except Exception:
        pass
    return str(os.environ.get(name, default) or default)

class GASClient:
    """
    Google Apps Script Web App（或你自己的 GAS API）呼叫器
    你原本程式只要需要 gas.post({...}) / gas.get(...) 就能用
    """
    def __init__(self, url: str, token: str = "", timeout: int = 30):
        self.url = (url or "").strip()
        self.token = (token or "").strip()
        self.timeout = int(timeout)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            # 你原本用什麼 header 驗證就放這裡（常見：Authorization: Bearer）
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def post(self, payload: dict) -> dict:
        """
        ✅ 依你原本的 GAS 方式：傳 JSON payload 給 GAS_URL
        """
        if not self.url:
            raise RuntimeError("GAS_URL 未設定，無法呼叫 GAS。")
        r = requests.post(self.url, json=payload, headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"ok": False, "raw": r.text}

    def get(self, params: dict) -> dict:
        if not self.url:
            raise RuntimeError("GAS_URL 未設定，無法呼叫 GAS。")
        r = requests.get(self.url, params=params, headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"ok": False, "raw": r.text}


# ✅ 安全初始化：沒設定就不要讓程式直接死掉
GAS_URL = _get_secret("GAS_URL", "")
GAS_TOKEN = _get_secret("GAS_TOKEN", "")

gas = None
if GAS_URL:
    try:
        gas = GASClient(GAS_URL, GAS_TOKEN)
    except Exception as e:
        # 不要讓整頁爆掉，改成後續 UI 顯示錯誤
        st.session_state["_gas_init_error"] = str(e)
        gas = None
#------A006：GASClient（Google Apps Script API 客戶端/避免 NameError）(結束)：------


#------A007：外箱資料清理/防呆(開始)：------
def _to_float(x, default: float = 0.0) -> float:
    """把各種輸入安全轉成 float；失敗回傳 default。"""
    try:
        if x is None:
            return float(default)
        # bool 要先處理，不然 True/False 會變 1/0 但常常不是你要的
        if isinstance(x, bool):
            return 1.0 if x else 0.0
        if isinstance(x, (int, float)):
            return float(x)

        s = str(x).strip()
        if s == "" or s.lower() in ("nan", "none"):
            return float(default)

        # 常見：1,234.5
        s = s.replace(",", "")
        return float(s)
    except Exception:
        return float(default)


def _sanitize_box(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["選取", "名稱", "長", "寬", "高", "數量", "空箱重量"]

    if df is None:
        df = pd.DataFrame(columns=cols)

    df = df.copy()

    # 補齊欄位
    for c in cols:
        if c not in df.columns:
            df[c] = "" if c == "名稱" else 0

    # 只保留需要欄位，空值處理
    df = df[cols].fillna("")

    # 空表就直接回傳空表（不要強塞預設值）
    if df.empty:
        return pd.DataFrame(columns=cols)

    # 型別整理
    df["選取"] = df["選取"].astype(bool)
    df["名稱"] = df["名稱"].astype(str).fillna("").map(lambda s: s.strip())

    for c in ["長", "寬", "高", "空箱重量"]:
        df[c] = df[c].apply(lambda v: _to_float(v, 0.0))

    df["數量"] = df["數量"].apply(lambda v: int(_to_float(v, 0.0)))
    df.loc[df["數量"] < 0, "數量"] = 0

    # 過濾完全空白列
    def _is_empty_row(r) -> bool:
        return (
            (not r["名稱"])
            and float(r["長"]) == 0.0
            and float(r["寬"]) == 0.0
            and float(r["高"]) == 0.0
            and int(r["數量"]) == 0
            and float(r["空箱重量"]) == 0.0
        )

    df = df[~df.apply(_is_empty_row, axis=1)].reset_index(drop=True)

    # 清理完如果變空，也保持空（不回填預設）
    if df.empty:
        return pd.DataFrame(columns=cols)

    return df
#------A007：外箱資料清理/防呆(結束)：------



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




#------A013：外箱選擇/商品展開為 Item(開始)：------
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
        for i in range(qty):
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
#------A013：外箱選擇/商品展開為 Item(結束)：------



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
    st.markdown('## 3. 裝箱結果與模擬')

    loading = _is_loading()

    if st.button('🚀 開始計算與 3D 模擬', use_container_width=True, key='run_pack', disabled=loading):
        _begin_loading('計算與 3D 模擬中...')
        try:
            df_box_src  = st.session_state.get('_box_live_df',  st.session_state.df_box)
            df_prod_src = st.session_state.get('_prod_live_df', st.session_state.df_prod)

            st.session_state.df_box  = _sanitize_box(df_box_src)
            st.session_state.df_prod = _sanitize_prod(df_prod_src)

            # ✅ 不用 _force_rerun()，避免「遮罩先結束→畫面又跑一下」的假防呆
            with st.spinner('計算中...'):
                res = pack_and_render(
                    st.session_state.order_name,
                    st.session_state.df_box,
                    st.session_state.df_prod
                )
                # ✅ 每次計算給一個 run_id，後面 plotly key 會用到，避免 DuplicateElementId
                res['run_id'] = str(int(time.time() * 1000))
                st.session_state.last_result = res
        finally:
            _end_loading()

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

    # ✅ 每次顯示時都用「目前結果」重建 report_html，確保下載內容與畫面一致
    res['report_html'] = build_report_html(
        st.session_state.order_name,
        packed_bins=packed_bins,
        unfitted=unfitted,
        content_wt=float(res.get('content_wt', 0.0) or 0.0),
        total_wt=float(res.get('total_wt', 0.0) or 0.0),
        util=float(res.get('util', 0.0) or 0.0),
        color_map=color_map
    )
    st.session_state.last_result = res

    # ===== 報告摘要 =====
    st.markdown("### 🧾 訂單裝箱報告")
    st.markdown('<div class="soft-card">', unsafe_allow_html=True)

    used_bin_count = int(res.get('used_bin_count', 0))
    st.markdown(
        f"""
        <div style="display:flex;flex-direction:column;gap:8px">
          <div>🧾 <b>訂單名稱</b>　<span style="color:#1f6feb;font-weight:900">{st.session_state.order_name}</span></div>
          <div>🕒 <b>計算時間</b>　{_now_tw().strftime('%Y-%m-%d %H:%M:%S (台灣時間)')}</div>
          <div>📦 <b>使用箱數</b>　<b>{used_bin_count}</b> 箱（可混用不同箱型）</div>
          <div>⚖️ <b>內容淨重</b>　{float(res.get('content_wt',0.0) or 0.0):.2f} kg</div>
          <div>🔴 <b>本次總重</b>　<span style="color:#c62828;font-weight:900">{float(res.get('total_wt',0.0) or 0.0):.2f} kg</span></div>
          <div>📊 <b>整體空間利用率</b>　{float(res.get('util',0.0) or 0.0):.2f}%（以實際用到的箱子總體積計算）</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 未裝入警示
    if unfitted:
        counts = {}
        for it in unfitted:
            base = str(it.name).split('_')[0]
            counts[base] = counts.get(base, 0) + 1
        st.warning('注意：有部分商品裝不下！（可能是箱型庫存不足或尺寸不夠）')
        for k, v in counts.items():
            st.error(f"{k}：超過 {v} 個")

    st.markdown('</div>', unsafe_allow_html=True)

    # ===== 下載完整報告 =====
    ts = _now_tw().strftime('%Y%m%d_%H%M')
    fname = f"{_safe_name(st.session_state.order_name)}_{ts}_總數{_total_items(st.session_state.df_prod)}件.html"
    st.download_button(
        '⬇️ 下載完整裝箱報告（.html）',
        data=res['report_html'].encode('utf-8'),
        file_name=fname,
        mime='text/html',
        use_container_width=True,
        key=f'dl_report_{run_id}'
    )

    # ===== 3D：Tabs（每箱一頁）+ 旁邊 legend =====
    if not packed_bins:
        st.info("本次沒有任何箱子成功裝入商品（可能全部商品尺寸不合）。")
        return

    legend_html = "<div style='display:flex;flex-direction:column;gap:6px'>"
    legend_html += "<div style='font-weight:900;margin-bottom:4px'>分類說明</div>"
    for k, c in (color_map or {}).items():
        legend_html += (
            "<div style='display:flex;align-items:center;gap:8px'>"
            f"<span style='width:14px;height:14px;border:2px solid #111;border-radius:3px;background:{c};display:inline-block'></span>"
            f"<span>{k}</span></div>"
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
                # ✅ 關鍵：給 plotly_chart 唯一 key，避免 DuplicateElementId
                st.plotly_chart(fig, use_container_width=True, key=f'plot_{run_id}_{i}')
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
