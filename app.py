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

    # 1) edited_rows: {row_index: {col: value}}
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

    # 2) deleted_rows: [row_index...]
    if isinstance(deleted_rows, list) and not out.empty:
        for ridx in sorted(deleted_rows, reverse=True):
            try:
                i = int(ridx)
            except Exception:
                continue
            if 0 <= i < len(out):
                out = out.drop(out.index[i])
        out = out.reset_index(drop=True)

    # 3) added_rows: [{col: val}...]
    if isinstance(added_rows, list):
        for row in added_rows:
            if isinstance(row, dict):
                if out.empty and len(out.columns) == 0:
                    out = pd.DataFrame(columns=list(row.keys()))
                safe_row = {c: row.get(c, "") for c in out.columns}
                out = pd.concat([out, pd.DataFrame([safe_row])], ignore_index=True)

    return out
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

    names = ['(無)'] + sorted(gas.list_names(sheet))

    c1, c2 = st.columns([1, 1], gap='medium')
    c3 = st.container()

    with c1:
        sel = st.selectbox('選擇模板', names, key=f'{key_prefix}_sel')
        load_btn = st.button('⬇️ 載入模板', use_container_width=True, key=f'{key_prefix}_load')
    with c2:
        del_sel = st.selectbox('要刪除的模板', names, key=f'{key_prefix}_del_sel')
        del_btn = st.button('🗑️ 刪除模板', use_container_width=True, key=f'{key_prefix}_del')
    with c3:
        new_name = st.text_input('另存為模板名稱', placeholder='例如：常用A', key=f'{key_prefix}_new')
        save_btn = st.button('💾 儲存模板', use_container_width=True, key=f'{key_prefix}_save')

    # 先處理動作，再顯示目前套用（才會即時更新）
    if load_btn:
        if sel == '(無)':
            st.warning('請先選擇要載入的模板')
        else:
            payload = gas.get_payload(sheet, sel)
            if payload is None:
                st.error('載入失敗：請確認雲端連線 / 權限')
            else:
                try:
                    df_loaded = from_payload(payload)
                    st.session_state[df_key] = df_loaded
                    st.session_state[active_key] = sel

                    # ✅ 載入後同步更新「live df」，確保 3D 計算讀到的是最新畫面資料
                    if df_key == 'df_box':
                        st.session_state['_box_live_df'] = df_loaded.copy()
                        st.session_state.pop('box_editor', None)
                    if df_key == 'df_prod':
                        st.session_state['_prod_live_df'] = df_loaded.copy()
                        st.session_state.pop('prod_editor', None)

                    st.success(f'已載入：{sel}')
                    _force_rerun()
                except Exception as e:
                    st.error(f'載入解析失敗：{e}')

    if save_btn:
        nm = (new_name or '').strip()
        if not nm:
            st.warning('請先輸入「另存為模板名稱」')
        else:
            ok, msg = gas.create_only(sheet, nm, to_payload(st.session_state[df_key]))
            if ok:
                st.session_state[active_key] = nm
                st.success(msg)
                _force_rerun()
            else:
                st.error(msg)

    if del_btn:
        if del_sel == '(無)':
            st.warning('請先選擇要刪除的模板')
        else:
            ok, msg = gas.delete(sheet, del_sel)
            if ok:
                if st.session_state.get(active_key) == del_sel:
                    st.session_state[active_key] = ''
                st.success(msg)
                _force_rerun()
            else:
                st.error(msg)

    st.caption(f"目前套用：{st.session_state.get(active_key) or '未選擇'}")
#------A010：模板區塊 UI（載入 / 儲存 / 刪除）(結束)：------




#------A011：外箱表格 UI（Data Editor + 操作按鈕）(開始)：------
def box_table_block():
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

    # ✅ 每次畫面更新都保存「當下表格」給 3D 計算使用
    st.session_state['_box_live_df'] = edited.copy()

    b1, b2, b3 = st.columns([1, 1, 1], gap='medium')
    with b1:
        apply_btn = st.button('✅ 套用變更（外箱表格）', use_container_width=True, key='box_apply')
    with b2:
        del_btn = st.button('🗑️ 刪除勾選', use_container_width=True, key='box_del')
    with b3:
        clear_btn = st.button('🧹 清除全部外箱', use_container_width=True, key='box_clear')

    if apply_btn:
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

        _force_rerun()

    if del_btn:
        d = _sanitize_box(edited)
        d = d[~d['選取']].reset_index(drop=True)
        d = _sanitize_box(d)
        st.session_state.df_box = d
        st.session_state['_box_live_df'] = d.copy()
        st.success('已刪除勾選外箱')
        _force_rerun()

    if clear_btn:
        empty = pd.DataFrame(columns=['選取','名稱','長','寬','高','數量','空箱重量'])
        st.session_state.df_box = empty
        st.session_state.active_box_tpl = ''
        st.session_state['_box_live_df'] = empty.copy()
        st.success('已清空全部外箱，並清除「目前套用」狀態')
        _force_rerun()
#------A011：外箱表格 UI（Data Editor + 操作按鈕）(結束)：------



#------A012：商品表格 UI（Data Editor + 操作按鈕）(開始)：------
def prod_table_block():
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

    # ✅ 每次畫面更新都保存「當下表格」給 3D 計算使用
    st.session_state['_prod_live_df'] = edited.copy()

    b1, b2, b3 = st.columns([1, 1, 1], gap='medium')
    with b1:
        apply_btn = st.button('✅ 套用變更（商品表格）', use_container_width=True, key='prod_apply')
    with b2:
        del_btn = st.button('🗑️ 刪除勾選', use_container_width=True, key='prod_del')
    with b3:
        clear_btn = st.button('🧹 清除全部商品', use_container_width=True, key='prod_clear')

    if apply_btn:
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

        _force_rerun()

    if del_btn:
        d = _sanitize_prod(edited)
        d = d[~d['選取']].reset_index(drop=True)
        d = _sanitize_prod(d)
        st.session_state.df_prod = d
        st.session_state['_prod_live_df'] = d.copy()
        st.success('已刪除勾選商品')
        _force_rerun()

    if clear_btn:
        empty = pd.DataFrame(columns=['選取','商品名稱','長','寬','高','重量(kg)','數量'])
        st.session_state.df_prod = empty
        st.session_state.active_prod_tpl = ''
        st.session_state['_prod_live_df'] = empty.copy()
        st.success('已清空全部商品，並清除「目前套用」狀態')
        _force_rerun()
#------A012：商品表格 UI（Data Editor + 操作按鈕）(結束)：------




#------A013：外箱選擇/商品展開為 Item(開始)：------
def _build_bins(df_box: pd.DataFrame) -> List[Dict[str,Any]]:
    """
    回傳所有勾選且數量>0的箱子，並展開數量（qty=3 就會產生 3 個 bin 設定）。
    """
    bins=[]
    for _,r in df_box.iterrows():
        if not bool(r.get('選取', False)):
            continue
        qty=int(r.get('數量', 0) or 0)
        if qty<=0:
            continue
        L=float(r.get('長',0) or 0)
        W=float(r.get('寬',0) or 0)
        H=float(r.get('高',0) or 0)
        if L<=0 or W<=0 or H<=0:
            continue

        name=str(r.get('名稱','') or '外箱').strip() or '外箱'
        tare=float(r.get('空箱重量',0) or 0)

        for i in range(qty):
            bins.append({'name':name, 'l':L, 'w':W, 'h':H, 'tare':tare})
    return bins

def _build_items(df_prod:pd.DataFrame)->List[Item]:
    items=[]
    for _,r in df_prod.iterrows():
        if not bool(r.get('選取', False)):
            continue
        qty=int(r.get('數量', 0) or 0)
        if qty<=0:
            continue
        L=float(r.get('長',0) or 0)
        W=float(r.get('寬',0) or 0)
        H=float(r.get('高',0) or 0)
        if L<=0 or W<=0 or H<=0:
            continue

        nm=str(r.get('商品名稱','') or '商品').strip() or '商品'
        wt=float(r.get('重量(kg)',0) or 0)

        for i in range(qty):
            items.append(Item(f"{nm}_{i+1}", L, W, H, wt))
    return items
#------A013：外箱選擇/商品展開為 Item(結束)：------


#------A014：3D 圖表建立（Plotly）(開始)：------
def build_3d_fig(box:Dict[str,Any], fitted:List[Item])->go.Figure:
    palette=['#2F3A4A','#4C6A92','#6C757D','#8E9AAF','#A3B18A','#B08968','#C9ADA7','#6D6875']
    fig=go.Figure()
    L,W,H=box['l'],box['w'],box['h']
    edges=[((0,0,0),(L,0,0)),((L,0,0),(L,W,0)),((L,W,0),(0,W,0)),((0,W,0),(0,0,0)),
           ((0,0,H),(L,0,H)),((L,0,H),(L,W,H)),((L,W,H),(0,W,H)),((0,W,H),(0,0,H)),
           ((0,0,0),(0,0,H)),((L,0,0),(L,0,H)),((L,W,0),(L,W,H)),((0,W,0),(0,W,H))]
    for a,b in edges:
        fig.add_trace(go.Scatter3d(
            x=[a[0],b[0]],y=[a[1],b[1]],z=[a[2],b[2]],
            mode='lines',
            line=dict(width=4,color='#333'),
            hoverinfo='skip',
            showlegend=False
        ))
    for i,it in enumerate(fitted):
        c=palette[i%len(palette)]
        px,py,pz=[_to_float(v) for v in getattr(it,'position',[0,0,0])]
        dx,dy,dz=float(it.depth),float(it.width),float(it.height)
        vx=[px,px+dx,px+dx,px,px,px+dx,px+dx,px]
        vy=[py,py,py+dy,py+dy,py,py,py+dy,py+dy]
        vz=[pz,pz,pz,pz,pz+dz,pz+dz,pz+dz,pz+dz]
        faces=[(0,1,2),(0,2,3),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
               (1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
        I,J,K=zip(*faces)
        fig.add_trace(go.Mesh3d(
            x=vx,y=vy,z=vz,
            i=I,j=J,k=K,
            opacity=0.65,
            color=c,
            hovertemplate=f"{it.name}<br>尺寸:{dx:.1f}×{dy:.1f}×{dz:.1f}<extra></extra>",
            showlegend=False
        ))
    fig.update_layout(
        scene=dict(
            xaxis=dict(range=[0,L]),
            yaxis=dict(range=[0,W]),
            zaxis=dict(range=[0,H]),
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
    box:Dict[str,Any], 
    fitted:List[Item], 
    unfitted:List[Item], 
    content_wt:float, 
    total_wt:float, 
    util:float, 
    fig:go.Figure
)->str:
    ts=_now_tw().strftime('%Y-%m-%d %H:%M:%S (台灣時間)')
    fig_div=plotly_offline_plot(fig, output_type='div', include_plotlyjs='cdn')
    warn=''
    if unfitted:
        counts={}
        for it in unfitted:
            base=str(it.name).split('_')[0]
            counts[base]=counts.get(base,0)+1
        warn="<div class='warn'><b>注意：</b>有部分商品裝不下！（可能是箱型庫存不足或尺寸不夠）</div>"+''.join(
            [f"<div class='warn2'>⚠ {k}：超過 {v} 個</div>" for k,v in counts.items()]
        )

    return f'''<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/>
    <title>訂單裝箱報告 - {_safe_name(order_name)}</title>
    <style>body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans TC','PingFang TC','Microsoft JhengHei',Arial,sans-serif;margin:0}}
    .container{{max-width:1100px;margin:24px auto;padding:0 16px}} .card{{border:1px solid #e6e6e6;border-radius:14px;padding:16px}}
    h1{{font-size:22px;margin:0 0 12px}} .row{{display:flex;gap:16px;flex-wrap:wrap}} .col{{flex:1;min-width:260px}}
    .kv{{display:flex;gap:10px;margin:6px 0}} .k{{width:110px;color:#666}} .red{{color:#c62828;font-weight:800}}
    .warn{{margin-top:12px;border:1px solid #f2b8b5;background:#fdecea;padding:10px 12px;border-radius:10px}}
    .warn2{{margin-top:8px;border:1px solid #f2b8b5;background:#fdecea;padding:8px 12px;border-radius:10px}}</style></head><body>
    <div class='container'><div class='card'><h1>📦 訂單裝箱報告</h1><div class='row'>
      <div class='col'><div class='kv'><div class='k'>訂單名稱</div><div class='v'><b>{_safe_name(order_name)}</b></div></div>
      <div class='kv'><div class='k'>計算時間</div><div class='v'>{ts}</div></div>
      <div class='kv'><div class='k'>使用外箱</div><div class='v'>{box['name']}（{box['l']}×{box['w']}×{box['h']}）× 1 箱</div></div></div>
      <div class='col'><div class='kv'><div class='k'>內容淨重</div><div class='v'>{content_wt:.2f} kg</div></div>
      <div class='kv'><div class='k'>本次總重</div><div class='v red'>{total_wt:.2f} kg</div></div>
      <div class='kv'><div class='k'>空間利用率</div><div class='v'>{util:.2f}%</div></div></div></div>{warn}</div>
    <div style='height:18px'></div><div class='card'>{fig_div}</div></div></body></html>'''
#------A015：HTML 報告輸出（含 Plotly 內嵌）(結束)：------


#------A016：裝箱計算核心（py3dbp）+ 統計(開始)：------
def pack_and_render(order_name:str, df_box:pd.DataFrame, df_prod:pd.DataFrame)->Dict[str,Any]:
    bins=_build_bins(df_box)
    if not bins:
        return {'ok':False,'error':'請至少勾選 1 個外箱（且數量>0、尺寸>0）'}

    items=_build_items(df_prod)
    if not items:
        return {'ok':False,'error':'請至少勾選 1 個商品（且數量>0、尺寸>0）'}

    packer=Packer()

    # 加入所有外箱（多箱/多箱型）
    for i,b in enumerate(bins, start=1):
        packer.add_bin(Bin(f"{b['name']}#{i}", b['l'], b['w'], b['h'], 999999))

    for it in items:
        packer.add_item(it)

    try:
        packer.pack(bigger_first=True, distribute_items=True)
    except TypeError:
        packer.pack()

    # 整理每個 bin 的結果
    per_bins=[]
    all_fitted=[]
    all_unfitted=[]
    for b0 in packer.bins:
        fitted=list(getattr(b0,'items',[]) or [])
        unfitted=list(getattr(b0,'unfitted_items',[]) or [])

        # b0.name 會是 "箱名#序號"
        # 找回原箱尺寸/重量：用 b0 的 dimension 與 bins 的順序對應（安全起見用 index）
        per_bins.append({
            'bin_name': b0.name,
            'L': float(getattr(b0,'width', 0) or 0),   # 注意：py3dbp 命名有時互換，後面 fig 用 bins 展開資料更可靠
            'W': float(getattr(b0,'height', 0) or 0),
            'H': float(getattr(b0,'depth', 0) or 0),
            'fitted': fitted,
            'unfitted': unfitted,
        })

        all_fitted.extend(fitted)
        # 只有最後一個 bin 的 unfitted_items 才是真正裝不下的（py3dbp 通常放在最後 bin）
        # 但保險起見：把每個 bin 的 unfitted 都收集起來，最後再去重
        all_unfitted.extend(unfitted)

    # 去重（避免重複）
    seen=set()
    uniq_unfitted=[]
    for it in all_unfitted:
        k=str(getattr(it,'name',''))
        if k in seen: 
            continue
        seen.add(k)
        uniq_unfitted.append(it)

    # 統計重量
    content_wt=sum(_to_float(getattr(it,'weight',0)) for it in all_fitted)

    # 本次總重 = 內容淨重 + 「實際有裝到商品的箱子」空箱重
    used_bin_count=0
    tare_total=0.0
    # bins[] 展開順序與 packer.bins 一致
    for i,b0 in enumerate(packer.bins):
        fitted=list(getattr(b0,'items',[]) or [])
        if fitted:
            used_bin_count += 1
            tare_total += _to_float(bins[i].get('tare',0))

    total_wt=content_wt+tare_total

    # 空間利用率（以「實際用到的箱子總體積」為分母）
    used_vol=sum(_to_float(it.width)*_to_float(it.height)*_to_float(it.depth) for it in all_fitted)
    used_box_vol=0.0
    used_bins_meta=[]
    for i,b0 in enumerate(packer.bins):
        fitted=list(getattr(b0,'items',[]) or [])
        if not fitted:
            continue
        bb=bins[i]
        used_box_vol += float(bb['l']*bb['w']*bb['h'])
        used_bins_meta.append(bb)

    util=(used_vol/used_box_vol*100.0) if used_box_vol>0 else 0.0

    # 3D：先預設顯示第一個「有裝到商品」的箱子
    fig=None
    first_used_index=None
    for i,b0 in enumerate(packer.bins):
        if list(getattr(b0,'items',[]) or []):
            first_used_index=i
            break

    if first_used_index is not None:
        box_meta=used_bins_meta[0] if used_bins_meta else bins[first_used_index]
        fitted=list(getattr(packer.bins[first_used_index],'items',[]) or [])
        fig=build_3d_fig(box_meta,fitted)
    else:
        # 全部都沒裝到（理論上不會發生，除非 items 全部裝不下）
        fig=go.Figure()

    # 報告 html：仍以第一個使用的箱子做 3D 展示（UI 會提供切換）
    html=build_report_html(order_name, (used_bins_meta[0] if used_bins_meta else bins[0]),
                           (list(getattr(packer.bins[first_used_index],'items',[]) or []) if first_used_index is not None else []),
                           uniq_unfitted, content_wt, total_wt, util, fig)

    return {
        'ok':True,
        'bins_input': bins,             # 你選的所有箱子（展開後）
        'packer_bins': packer.bins,     # py3dbp 的 bins（含 items）
        'used_bin_count': used_bin_count,
        'fitted_all': all_fitted,
        'unfitted': uniq_unfitted,
        'content_wt': content_wt,
        'total_wt': total_wt,
        'util': util,
        'fig': fig,
        'report_html': html
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

    if st.button('🚀 開始計算與 3D 模擬', use_container_width=True, key='run_pack'):
        # ✅ 以「畫面上的真實資料」為準（不需要按套用變更）
        df_box_src = st.session_state.get('_box_live_df', st.session_state.df_box)
        df_prod_src = st.session_state.get('_prod_live_df', st.session_state.df_prod)

        st.session_state.df_box = _sanitize_box(df_box_src)
        st.session_state.df_prod = _sanitize_prod(df_prod_src)

        with st.spinner('計算中...'):
            st.session_state.last_result = pack_and_render(
                st.session_state.order_name,
                st.session_state.df_box,
                st.session_state.df_prod
            )

        _force_rerun()

    res = st.session_state.get('last_result')
    if not res:
        return
    if not res.get('ok'):
        st.error(res.get('error','計算失敗'))
        return

    # ===== 報告式 UI =====
    st.markdown("### 🧾 訂單裝箱報告")
    st.markdown('<div class="soft-card">', unsafe_allow_html=True)

    used_bin_count = int(res.get('used_bin_count', 0))
    st.markdown(
        f"""
        <div style="display:flex;flex-direction:column;gap:8px">
          <div>🧾 <b>訂單名稱</b>　<span style="color:#1f6feb;font-weight:800">{st.session_state.order_name}</span></div>
          <div>🕒 <b>計算時間</b>　{_now_tw().strftime('%Y-%m-%d %H:%M:%S (台灣時間)')}</div>
          <div>📦 <b>使用箱數</b>　<b>{used_bin_count}</b> 箱（可混用不同箱型）</div>
          <div>⚖️ <b>內容淨重</b>　{res['content_wt']:.2f} kg</div>
          <div>🔴 <b>本次總重</b>　<span style="color:#c62828;font-weight:900">{res['total_wt']:.2f} kg</span></div>
          <div>📊 <b>整體空間利用率</b>　{res['util']:.2f}%（以實際用到的箱子總體積計算）</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if res['unfitted']:
        counts={}
        for it in res['unfitted']:
            base=str(it.name).split('_')[0]
            counts[base]=counts.get(base,0)+1

        st.markdown(
            """
            <div style="margin-top:12px;border:1px solid #f2b8b5;background:#fdecea;padding:10px 12px;border-radius:10px">
              ❌ <b>注意：</b>有部分商品裝不下！（可能是箱型庫存不足或尺寸不夠）
            </div>
            """,
            unsafe_allow_html=True
        )
        for k,v in counts.items():
            st.markdown(
                f"""
                <div style="margin-top:8px;border:1px solid #f2b8b5;background:#fdecea;padding:8px 12px;border-radius:10px">
                  ⚠️ <b>{k}</b>：超過 <b>{v}</b> 個
                </div>
                """,
                unsafe_allow_html=True
            )

    st.markdown('</div>', unsafe_allow_html=True)

    # 下載
    ts=_now_tw().strftime('%Y%m%d_%H%M')
    fname=f"{_safe_name(st.session_state.order_name)}_{ts}_總數{_total_items(st.session_state.df_prod)}件.html"
    st.download_button(
        '⬇️ 下載完整裝箱報告（.html）',
        data=res['report_html'].encode('utf-8'),
        file_name=fname,
        mime='text/html',
        use_container_width=True,
        key='dl_report'
    )

    # ===== 3D：提供切換要看的箱子 =====
    packer_bins = res.get('packer_bins') or []
    bins_input = res.get('bins_input') or []

    used_indices=[]
    labels=[]
    for i,b0 in enumerate(packer_bins):
        fitted=list(getattr(b0,'items',[]) or [])
        if not fitted:
            continue
        used_indices.append(i)
        labels.append(f"{b0.name}（裝入 {len(fitted)} 件）")

    if used_indices:
        sel = st.selectbox("選擇要查看的箱子 3D 模擬", labels, index=0, key="sel_bin_3d")
        idx = used_indices[labels.index(sel)]

        box_meta = bins_input[idx]
        fitted = list(getattr(packer_bins[idx],'items',[]) or [])
        fig = build_3d_fig(box_meta, fitted)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("本次沒有任何箱子成功裝入商品（可能全部商品尺寸不合）。")
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
