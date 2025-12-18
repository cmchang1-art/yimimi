# -*- coding: utf-8 -*-
#------A001：匯入套件(開始)：------
import os, json, re
from datetime import datetime, timedelta
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

/* ===== Loading overlay (鎖操作) ===== */
.loading-wrap{position:relative}
.loading-overlay{
  position:absolute; inset:0;
  background:rgba(255,255,255,0.78);
  border:1px dashed rgba(0,0,0,0.18);
  border-radius:14px;
  display:flex; align-items:center; justify-content:center;
  z-index:50;
  pointer-events:all;
}
.loading-box{
  background:#fff;
  border:1px solid rgba(0,0,0,0.15);
  border-radius:12px;
  padding:10px 14px;
  box-shadow:0 6px 20px rgba(0,0,0,0.08);
  font-weight:800;
}
.loading-sub{font-weight:500;color:#555;font-size:13px;margin-top:4px}

/* ===== Download button 外觀（全域套用）===== */
div[data-testid="stDownloadButton"] > button{
  font-size: 16px;          /* 字體大小 */
  /*padding: 10px 14px;        內距：讓按鈕更大顆好按 */
  border-radius: 12px;      /* 圓角 */
  font-weight: 800;
  margin: 2rem 0px 0rem;    /*外圍間距*/
  background: #bdd4f9;      /*按鈕底色*/
}

/* ===== 只針對「🚀 開始計算與 3D 模擬」按鈕 ===== */
.run-pack-btn div[data-testid="stButton"] button{
  font-size: 18px;          /* 字體大小 */
  font-weight: 800;
  padding: 14px 16px;       /* 讓按鈕更大顆 */
  border-radius: 12px;      /* 圓角 */
  background: #eaebf9;      /*按鈕底色*/
}

/* hover 效果 */
.run-pack-btn div[data-testid="stButton"] button:hover{
  transform: translateY(-1px);
  filter: brightness(1.05);
}

/* disabled 狀態（計算中） */
.run-pack-btn div[data-testid="stButton"] button:disabled{
  opacity: 0.55;
  cursor: not-allowed;
}

</style>''', unsafe_allow_html=True)
#------A002：Streamlit頁面設定與全域CSS(結束)：------



#------A003：Secrets/環境變數讀取工具(開始)：------
def _secret(k:str, d:str='')->str:
    try:
        return str(st.secrets.get(k, d))
    except Exception:
        return os.getenv(k, d) or d

GAS_URL=_secret('GAS_URL','').strip()
GAS_TOKEN=_secret('GAS_TOKEN','').strip()
SHEET_BOX=_secret('SHEET_BOX','box_templates').strip()
SHEET_PROD=_secret('SHEET_PROD','product_templates').strip()
#------A003：Secrets/環境變數讀取工具(結束)：------


#------A004：通用工具函式(型別/時間/檔名安全)(開始)：------
def _to_float(x, default=0.0)->float:
    try:
        return float(x)
    except Exception:
        try:
            return float(str(x).strip())
        except Exception:
            return float(default)

def _now_tw()->datetime:
    return datetime.utcnow()+timedelta(hours=8)

def _safe_name(s:str)->str:
    s=(s or '').strip() or '訂單'
    s=re.sub(r'[\\/:*?"<>| ]+','_',s)
    return s[:60]

def _force_rerun():
    try:
        st.rerun()
    except Exception:
        try:
            st.experimental_rerun()
        except Exception:
            pass

def _apply_editor_state(df: pd.DataFrame, state: Any) -> pd.DataFrame:
    """
    將 st.data_editor 的 widget state（dict: edited_rows/added_rows/deleted_rows）
    套用回 DataFrame。這樣「不按套用變更」也能用畫面上最新勾選/修改來計算。
    """
    if df is None:
        df = pd.DataFrame()
    out = df.copy()

    if not isinstance(state, dict):
        return out

    edited_rows = state.get("edited_rows") or {}
    deleted_rows = state.get("deleted_rows") or []
    added_rows = state.get("added_rows") or []

    if isinstance(edited_rows, dict) and not out.empty:
        for ridx, changes in edited_rows.items():
            try:
                i = int(ridx)
            except Exception:
                continue
            if i < 0 or i >= len(out):
                continue
            if isinstance(changes, dict):
                for col, val in changes.items():
                    if col in out.columns:
                        out.at[out.index[i], col] = val

    if isinstance(deleted_rows, list) and not out.empty:
        for ridx in sorted(deleted_rows, reverse=True):
            try:
                i = int(ridx)
            except Exception:
                continue
            if 0 <= i < len(out):
                out = out.drop(out.index[i])
        out = out.reset_index(drop=True)

    if isinstance(added_rows, list):
        for row in added_rows:
            if isinstance(row, dict):
                if out.empty and len(out.columns) == 0:
                    out = pd.DataFrame(columns=list(row.keys()))
                safe_row = {c: row.get(c, "") for c in out.columns}
                out = pd.concat([out, pd.DataFrame([safe_row])], ignore_index=True)

    return out

# ===== Loading 控制（全區塊鎖定）=====
def _is_loading()->bool:
    return bool(st.session_state.get('_loading', False))

def _set_loading(flag: bool, msg: str = '資料讀取中...'):
    st.session_state['_loading'] = bool(flag)
    st.session_state['_loading_msg'] = msg or '資料讀取中...'

def _loading_msg()->str:
    return str(st.session_state.get('_loading_msg', '資料讀取中...') or '資料讀取中...')

def _loading_overlay_html(msg: str = None) -> str:
    m = msg or _loading_msg()
    return f"""
    <div class="loading-overlay">
      <div class="loading-box">
        ⏳ {m}
        <div class="loading-sub">請稍候，資料處理完成後即可操作</div>
      </div>
    </div>
    """

def _begin_loading(msg: str = '資料讀取中...'):
    _set_loading(True, msg)

def _end_loading():
    _set_loading(False, '')

# ===== GAS cache（減少 list/get 的延遲）=====
@st.cache_data(ttl=20, show_spinner=False)
def _cache_gas_list(url: str, token: str, sheet: str) -> List[str]:
    c = GASClient(url, token)
    return c.list_names(sheet) if c.ready else []

@st.cache_data(ttl=20, show_spinner=False)
def _cache_gas_get(url: str, token: str, sheet: str, name: str) -> Optional[Dict[str, Any]]:
    c = GASClient(url, token)
    return c.get_payload(sheet, name) if c.ready else None

def _gas_cache_clear():
    try:
        st.cache_data.clear()
    except Exception:
        pass
#------A004：通用工具函式(型別/時間/檔名安全)(結束)：------



#------A005：Google Apps Script(GAS) API Client(開始)：------
class GASClient:
    def __init__(self,url:str,token:str):
        self.url=url.strip(); self.token=token.strip()

    @property
    def ready(self)->bool: 
        return bool(self.url and self.token)

    def _call(self, action:str, sheet:str, name:str='', payload:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
        if not self.ready: 
            return {'ok':False,'error':'missing_gas_config'}
        params={'action':action,'sheet':sheet,'token':self.token}
        if name: 
            params['name']=name
        try:
            if action=='upsert':
                r=requests.post(
                    self.url, 
                    params=params, 
                    json={'payload_json': json.dumps(payload or {}, ensure_ascii=False)}
                )
            else:
                r=requests.get(self.url, params=params)
            return r.json()
        except Exception as e:
            return {'ok':False,'error':str(e)}

    def list_names(self,sheet:str)->List[str]:
        d=self._call('list',sheet)
        return list(d.get('items') or []) if d.get('ok') else []

    def get_payload(self,sheet:str,name:str)->Optional[Dict[str,Any]]:
        d=self._call('get',sheet,name=name)
        if not d.get('ok'): 
            return None
        raw=d.get('payload_json') or ''
        try: 
            return json.loads(raw) if raw else {}
        except Exception: 
            return None

    def create_only(self,sheet:str,name:str,payload:Dict[str,Any])->Tuple[bool,str]:
        if name in self.list_names(sheet):
            return False,'同名模板已存在，請改名後再儲存。'
        d=self._call('upsert',sheet,name=name,payload=payload)
        return (True,'已儲存') if d.get('ok') else (False, f"儲存失敗：{d.get('error','未知錯誤')}")

    def upsert(self,sheet:str,name:str,payload:Dict[str,Any])->Tuple[bool,str]:
        # 覆寫儲存（用於：套用變更後同步回寫雲端模板）
        d=self._call('upsert',sheet,name=name,payload=payload)
        return (True,'已更新') if d.get('ok') else (False, f"更新失敗：{d.get('error','未知錯誤')}")

    def delete(self,sheet:str,name:str)->Tuple[bool,str]:
        d=self._call('delete',sheet,name=name)
        return (True,'已刪除') if d.get('ok') else (False, f"刪除失敗：{d.get('error','未知錯誤')}")

gas=GASClient(GAS_URL,GAS_TOKEN)
#------A005：Google Apps Script(GAS) API Client(結束)：------



#------A006：Session State 預設值初始化(開始)：------
def _ensure_defaults():
    if 'layout_mode' not in st.session_state: 
        st.session_state.layout_mode='左右 50% / 50%'
    if 'order_name' not in st.session_state: 
        st.session_state.order_name=f"訂單_{_now_tw().strftime('%Y%m%d')}"
    if 'df_box' not in st.session_state:
        st.session_state.df_box=pd.DataFrame([
            {'選取':True,'名稱':'手動箱','長':35.0,'寬':25.0,'高':20.0,'數量':1,'空箱重量':0.50}
        ])
    if 'df_prod' not in st.session_state:
        st.session_state.df_prod=pd.DataFrame([
            {'選取':True,'商品名稱':'禮盒(米餅)','長':21.0,'寬':14.0,'高':8.5,'重量(kg)':0.50,'數量':5}
        ])
    if 'active_box_tpl' not in st.session_state: 
        st.session_state.active_box_tpl=''
    if 'active_prod_tpl' not in st.session_state: 
        st.session_state.active_prod_tpl=''
    if 'last_result' not in st.session_state: 
        st.session_state.last_result=None
#------A006：Session State 預設值初始化(結束)：------


#------A007：外箱資料清理/防呆(開始)：------
def _sanitize_box(df:pd.DataFrame)->pd.DataFrame:
    cols=['選取','名稱','長','寬','高','數量','空箱重量']
    if df is None:
        df=pd.DataFrame(columns=cols)
    df=df.copy()
    for c in cols:
        if c not in df.columns:
            df[c]='' if c=='名稱' else 0
    df=df[cols].fillna('')

    # 空表就直接回傳空表（不要強塞預設值）
    if df.empty:
        return pd.DataFrame(columns=cols)

    df['選取']=df['選取'].astype(bool)
    df['名稱']=df['名稱'].astype(str).str.strip()
    for c in ['長','寬','高','空箱重量']:
        df[c]=df[c].apply(_to_float)
    df['數量']=df['數量'].apply(lambda x:int(_to_float(x,0)))

    def empty_row(r):
        return (not r['名稱']) and r['長']==0 and r['寬']==0 and r['高']==0 and r['數量']==0

    df=df[~df.apply(empty_row,axis=1)].reset_index(drop=True)

    # 清理完如果變空，也保持空（不回填預設）
    if df.empty:
        return pd.DataFrame(columns=cols)

    return df
#------A007：外箱資料清理/防呆(結束)：------



#------A008：商品資料清理/防呆(開始)：------
def _sanitize_prod(df:pd.DataFrame)->pd.DataFrame:
    cols=['選取','商品名稱','長','寬','高','重量(kg)','數量']
    if df is None:
        df=pd.DataFrame(columns=cols)
    df=df.copy()
    for c in cols:
        if c not in df.columns:
            df[c]='' if c=='商品名稱' else 0
    df=df[cols].fillna('')

    if df.empty:
        return pd.DataFrame(columns=cols)

    df['選取']=df['選取'].astype(bool)
    df['商品名稱']=df['商品名稱'].astype(str).str.strip()
    for c in ['長','寬','高','重量(kg)']:
        df[c]=df[c].apply(_to_float)
    df['數量']=df['數量'].apply(lambda x:int(_to_float(x,0)))

    def empty_row(r):
        return (not r['商品名稱']) and r['長']==0 and r['寬']==0 and r['高']==0 and r['數量']==0

    df=df[~df.apply(empty_row,axis=1)].reset_index(drop=True)

    if df.empty:
        return pd.DataFrame(columns=cols)

    return df
#------A008：商品資料清理/防呆(結束)：------



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

    # ✅ 用 cache 減少清單讀取延遲
    names = ['(無)'] + sorted(_cache_gas_list(GAS_URL, GAS_TOKEN, sheet))

    # ✅ 整段包在 loading-wrap 內，overlay 才能「覆蓋」控制項
    st.markdown('<div class="loading-wrap">', unsafe_allow_html=True)

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

    # ✅ 若目前正處於 loading 狀態（上一輪 rerun 後），顯示 overlay
    if loading:
        st.markdown(_loading_overlay_html(), unsafe_allow_html=True)

    # ===== 動作：載入 =====
    if load_btn:
        if sel == '(無)':
            st.warning('請先選擇要載入的模板')
        else:
            _begin_loading('讀取模板中...')
            # ✅ 關鍵：同一次 run 立即渲染 overlay（使用者才看得到）
            st.markdown(_loading_overlay_html('讀取模板中...'), unsafe_allow_html=True)
            try:
                payload = _cache_gas_get(GAS_URL, GAS_TOKEN, sheet, sel)
                if payload is None:
                    st.error('載入失敗：請確認雲端連線 / 權限')
                else:
                    df_loaded = from_payload(payload)
                    st.session_state[df_key] = df_loaded
                    st.session_state[active_key] = sel

                    # ✅ 載入後同步更新「live df」
                    if df_key == 'df_box':
                        st.session_state['_box_live_df'] = df_loaded.copy()
                        st.session_state.pop('box_editor', None)
                    if df_key == 'df_prod':
                        st.session_state['_prod_live_df'] = df_loaded.copy()
                        st.session_state.pop('prod_editor', None)

                    st.success(f'已載入：{sel}')

                    _gas_cache_clear()
                    _force_rerun()
            except Exception as e:
                st.error(f'載入解析失敗：{e}')
            finally:
                _end_loading()

    # ===== 動作：儲存 =====
    if save_btn:
        nm = (new_name or '').strip()
        if not nm:
            st.warning('請先輸入「另存為模板名稱」')
        else:
            _begin_loading('儲存模板中...')
            # ✅ 關鍵：同一次 run 立即渲染 overlay（使用者才看得到）
            st.markdown(_loading_overlay_html('儲存模板中...'), unsafe_allow_html=True)
            try:
                ok, msg = gas.create_only(sheet, nm, to_payload(st.session_state[df_key]))
                if ok:
                    st.session_state[active_key] = nm
                    st.success(msg)
                    _gas_cache_clear()
                    _force_rerun()
                else:
                    st.error(msg)
            finally:
                _end_loading()

    # ===== 動作：刪除 =====
    if del_btn:
        if del_sel == '(無)':
            st.warning('請先選擇要刪除的模板')
        else:
            _begin_loading('刪除模板中...')
            # ✅ 關鍵：同一次 run 立即渲染 overlay（使用者才看得到）
            st.markdown(_loading_overlay_html('刪除模板中...'), unsafe_allow_html=True)
            try:
                ok, msg = gas.delete(sheet, del_sel)
                if ok:
                    if st.session_state.get(active_key) == del_sel:
                        st.session_state[active_key] = ''
                    st.success(msg)
                    _gas_cache_clear()
                    _force_rerun()
                else:
                    st.error(msg)
            finally:
                _end_loading()

    st.caption(f"目前套用：{st.session_state.get(active_key) or '未選擇'}")
    st.markdown('</div>', unsafe_allow_html=True)
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
            aspectmode='data',
          
            # ✅ (1) 讓初始 3D 物件看起來小約 20%：相機拉遠（eye 變大）
            # 你之後想更小/更大，就調整下面三個數字
            camera=dict(eye=dict(x=1.56, y=1.56, z=1.5))
        ),
        margin=dict(l=0,r=0,t=0,b=0),
        height=650
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
  
# 只包住「🚀 開始計算與 3D 模擬」按鈕：方便 CSS 精準套用
st.markdown('<div class="run-pack-btn">', unsafe_allow_html=True)

clicked = st.button(
    '🚀 開始計算與 3D 模擬',
    use_container_width=True,
    key='run_pack',
    disabled=loading
)

st.markdown('</div>', unsafe_allow_html=True)

if clicked:
    _begin_loading('計算與 3D 模擬中...')
    try:
        df_box_src  = st.session_state.get('_box_live_df',  st.session_state.df_box)
        df_prod_src = st.session_state.get('_prod_live_df', st.session_state.df_prod)

        st.session_state.df_box  = _sanitize_box(df_box_src)
        st.session_state.df_prod = _sanitize_prod(df_prod_src)

        with st.spinner('計算中...'):
            st.session_state.last_result = pack_and_render(
                st.session_state.order_name,
                st.session_state.df_box,
                st.session_state.df_prod
            )
        _force_rerun()
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



    # ===== 下載完整報告 =====
    ts = _now_tw().strftime('%Y%m%d_%H%M')
    fname = f"{_safe_name(st.session_state.order_name)}_{ts}_總數{_total_items(st.session_state.df_prod)}件.html"
    st.download_button(
        '⬇️ 下載完整裝箱報告（.html）',
        data=res['report_html'].encode('utf-8'),
        file_name=fname,
        mime='text/html',
        use_container_width=True,
        key='dl_report'
    )

    # ===== 3D：改回 Tabs（每箱一頁）+ 旁邊顯示 legend =====
    if not packed_bins:
        st.info("本次沒有任何箱子成功裝入商品（可能全部商品尺寸不合）。")
        return

    # legend HTML（同色塊+品項名）
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

    for idx, (t, p) in enumerate(zip(tabs, packed_bins), start=1):
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
                # ✅ 關鍵修正：多箱(tab)時，每個 plotly_chart 必須有唯一 key，避免 DuplicateElementId
                st.plotly_chart(fig, use_container_width=True, key=f"box3d_{idx}")
#------A018：結果區塊 UI（開始計算 + 顯示結果 + 下載HTML）(結束)：------




#------A019：主程式 UI（版面配置：左右 / 上下）(開始)：------
def main():
    _ensure_defaults()
    st.title('📦 3D裝箱系統')

    st.markdown('#### 版面配置')
    mode=st.radio(
        '', 
        ['左右 50% / 50%','上下（垂直）'], 
        horizontal=True, 
        key='layout_radio', 
        index=0 if st.session_state.layout_mode=='左右 50% / 50%' else 1
    )
    st.session_state.layout_mode=mode

    st.text_input('訂單名稱', key='order_name')

    if mode=='左右 50% / 50%':
        left,right=st.columns(2,gap='large')
        with left:
            st.markdown('## 1. 訂單與外箱')
            template_block('箱型模板', SHEET_BOX, 'active_box_tpl', 'df_box', _box_payload, _box_from, 'box_tpl')
            box_table_block()
        with right:
            st.markdown('## 2. 商品清單')
            template_block('商品模板', SHEET_PROD, 'active_prod_tpl', 'df_prod', _prod_payload, _prod_from, 'prod_tpl')
            prod_table_block()

        st.divider()
        result_block()

    else:
        st.markdown('## 1. 訂單與外箱')
        template_block('箱型模板', SHEET_BOX, 'active_box_tpl', 'df_box', _box_payload, _box_from, 'box_tpl_v')
        box_table_block()

        st.divider()

        st.markdown('## 2. 商品清單')
        template_block('商品模板', SHEET_PROD, 'active_prod_tpl', 'df_prod', _prod_payload, _prod_from, 'prod_tpl_v')
        prod_table_block()

        st.divider()
        result_block()
#------A019：主程式 UI（版面配置：左右 / 上下）(結束)：------


#------A020：程式進入點(開始)：------
if __name__=='__main__':
    main()
#------A020：程式進入點(結束)：------
