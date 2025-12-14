# -*- coding: utf-8 -*-
import os, json, re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

import requests
import pandas as pd
import streamlit as st
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
from plotly.offline import plot as plotly_offline_plot

st.set_page_config(page_title='3D裝箱系統', layout='wide')
st.markdown('''<style>
.block-container{padding-top:1.25rem;padding-bottom:2rem}
.muted{color:#666;font-size:13px}
.soft-card{border:1px solid #e6e6e6;border-radius:14px;padding:16px;background:#fff}
.soft-title{font-weight:800;font-size:20px;margin-bottom:10px}
</style>''', unsafe_allow_html=True)

def _secret(k:str, d:str='')->str:
    try:
        return str(st.secrets.get(k, d))
    except Exception:
        return os.getenv(k, d) or d

GAS_URL=_secret('GAS_URL','').strip()
GAS_TOKEN=_secret('GAS_TOKEN','').strip()
SHEET_BOX=_secret('SHEET_BOX','box_templates').strip()
SHEET_PROD=_secret('SHEET_PROD','product_templates').strip()

def _to_float(x, default=0.0)->float:
    try:
        return float(x)
    except Exception:
        try: return float(str(x).strip())
        except Exception: return float(default)

def _now_tw()->datetime:
    return datetime.utcnow()+timedelta(hours=8)

def _safe_name(s:str)->str:
    s=(s or '').strip() or '訂單'
    s=re.sub(r'[\\/:*?"<>| ]+','_',s)
    return s[:60]

class GASClient:
    def __init__(self,url:str,token:str):
        self.url=url.strip(); self.token=token.strip()
    @property
    def ready(self)->bool: return bool(self.url and self.token)
    def _call(self, action:str, sheet:str, name:str='', payload:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
        if not self.ready: return {'ok':False,'error':'missing_gas_config'}
        params={'action':action,'sheet':sheet,'token':self.token}
        if name: params['name']=name
        try:
            if action=='upsert':
                r=requests.post(self.url, params=params, json={'payload_json': json.dumps(payload or {}, ensure_ascii=False)})
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
        if not d.get('ok'): return None
        raw=d.get('payload_json') or ''
        try: return json.loads(raw) if raw else {}
        except Exception: return None
    def create_only(self,sheet:str,name:str,payload:Dict[str,Any])->Tuple[bool,str]:
        if name in self.list_names(sheet):
            return False,'同名模板已存在，請改名後再儲存。'
        d=self._call('upsert',sheet,name=name,payload=payload)
        return (True,'已儲存') if d.get('ok') else (False, f"儲存失敗：{d.get('error','未知錯誤')}")
    def delete(self,sheet:str,name:str)->Tuple[bool,str]:
        d=self._call('delete',sheet,name=name)
        return (True,'已刪除') if d.get('ok') else (False, f"刪除失敗：{d.get('error','未知錯誤')}")

gas=GASClient(GAS_URL,GAS_TOKEN)

def _ensure_defaults():
    if 'layout_mode' not in st.session_state: st.session_state.layout_mode='左右 50% / 50%'
    if 'order_name' not in st.session_state: st.session_state.order_name=f"訂單_{_now_tw().strftime('%Y%m%d')}"
    if 'df_box' not in st.session_state:
        st.session_state.df_box=pd.DataFrame([{'選取':True,'名稱':'手動箱','長':35.0,'寬':25.0,'高':20.0,'數量':1,'空箱重量':0.50}])
    if 'df_prod' not in st.session_state:
        st.session_state.df_prod=pd.DataFrame([{'選取':True,'商品名稱':'禮盒(米餅)','長':21.0,'寬':14.0,'高':8.5,'重量(kg)':0.50,'數量':5}])
    if 'active_box_tpl' not in st.session_state: st.session_state.active_box_tpl=''
    if 'active_prod_tpl' not in st.session_state: st.session_state.active_prod_tpl=''
    if 'last_result' not in st.session_state: st.session_state.last_result=None

def _sanitize_box(df:pd.DataFrame)->pd.DataFrame:
    cols=['選取','名稱','長','寬','高','數量','空箱重量']
    if df is None: df=pd.DataFrame()
    df=df.copy()
    for c in cols:
        if c not in df.columns: df[c]='' if c=='名稱' else 0
    df=df[cols].fillna('')
    df['選取']=df['選取'].astype(bool)
    df['名稱']=df['名稱'].astype(str).str.strip()
    for c in ['長','寬','高','空箱重量']: df[c]=df[c].apply(_to_float)
    df['數量']=df['數量'].apply(lambda x:int(_to_float(x,0)))
    def empty(r):
        return (not r['名稱']) and r['長']==0 and r['寬']==0 and r['高']==0 and r['數量']==0
    df=df[~df.apply(empty,axis=1)].reset_index(drop=True)
    if df.empty:
        df=pd.DataFrame([{'選取':True,'名稱':'手動箱','長':35.0,'寬':25.0,'高':20.0,'數量':1,'空箱重量':0.50}])
    return df

def _sanitize_prod(df:pd.DataFrame)->pd.DataFrame:
    cols=['選取','商品名稱','長','寬','高','重量(kg)','數量']
    if df is None: df=pd.DataFrame()
    df=df.copy()
    for c in cols:
        if c not in df.columns: df[c]='' if c=='商品名稱' else 0
    df=df[cols].fillna('')
    df['選取']=df['選取'].astype(bool)
    df['商品名稱']=df['商品名稱'].astype(str).str.strip()
    for c in ['長','寬','高','重量(kg)']: df[c]=df[c].apply(_to_float)
    df['數量']=df['數量'].apply(lambda x:int(_to_float(x,0)))
    def empty(r):
        return (not r['商品名稱']) and r['長']==0 and r['寬']==0 and r['高']==0 and r['數量']==0
    df=df[~df.apply(empty,axis=1)].reset_index(drop=True)
    if df.empty:
        df=pd.DataFrame([{'選取':True,'商品名稱':'禮盒(米餅)','長':21.0,'寬':14.0,'高':8.5,'重量(kg)':0.50,'數量':5}])
    return df

def _box_payload(df):
    rows=[]
    for _,r in df.fillna('').iterrows():
        rows.append({'selected':bool(r['選取']),'name':str(r['名稱']).strip(),'l':_to_float(r['長']),'w':_to_float(r['寬']),'h':_to_float(r['高']),'qty':int(_to_float(r['數量'],0)),'tare':_to_float(r['空箱重量'])})
    return {'rows':rows}
def _box_from(payload):
    if not isinstance(payload,dict): raise ValueError('payload is not dict')
    rows=payload.get('rows',[])
    if not isinstance(rows,list): raise ValueError('rows is not list')
    out=[]
    for r in rows:
        if not isinstance(r,dict): continue
        out.append({'選取':bool(r.get('selected',False)),'名稱':str(r.get('name','')),'長':_to_float(r.get('l',0)),'寬':_to_float(r.get('w',0)),'高':_to_float(r.get('h',0)),'數量':int(_to_float(r.get('qty',0),0)),'空箱重量':_to_float(r.get('tare',0))})
    return _sanitize_box(pd.DataFrame(out))
def _prod_payload(df):
    rows=[]
    for _,r in df.fillna('').iterrows():
        rows.append({'selected':bool(r['選取']),'name':str(r['商品名稱']).strip(),'l':_to_float(r['長']),'w':_to_float(r['寬']),'h':_to_float(r['高']),'wt':_to_float(r['重量(kg)']),'qty':int(_to_float(r['數量'],0))})
    return {'rows':rows}
def _prod_from(payload):
    if not isinstance(payload,dict): raise ValueError('payload is not dict')
    rows=payload.get('rows',[])
    if not isinstance(rows,list): raise ValueError('rows is not list')
    out=[]
    for r in rows:
        if not isinstance(r,dict): continue
        out.append({'選取':bool(r.get('selected',False)),'商品名稱':str(r.get('name','')),'長':_to_float(r.get('l',0)),'寬':_to_float(r.get('w',0)),'高':_to_float(r.get('h',0)),'重量(kg)':_to_float(r.get('wt',0)),'數量':int(_to_float(r.get('qty',0),0))})
    return _sanitize_prod(pd.DataFrame(out))

def template_block(title:str, sheet:str, active_key:str, df_key:str, to_payload, from_payload, key_prefix:str):
    st.markdown(f"### {title}（載入 / 儲存 / 刪除）")
    if not gas.ready:
        st.info('尚未設定 Streamlit Secrets（GAS_URL / GAS_TOKEN）。模板功能暫停。')
        return
    names=['(無)']+sorted(gas.list_names(sheet))
    c1,c2,c3=st.columns([1.25,1,1.25],gap='medium')
    with c1:
        sel=st.selectbox('選擇模板', names, key=f'{key_prefix}_sel')
    with c2:
        load_btn=st.button('⬇️ 載入模板', use_container_width=True, key=f'{key_prefix}_load')
        save_btn=st.button('💾 儲存模板', use_container_width=True, key=f'{key_prefix}_save')
    with c3:
        del_sel=st.selectbox('要刪除的模板', names, key=f'{key_prefix}_del_sel')
        del_btn=st.button('🗑️ 刪除模板', use_container_width=True, key=f'{key_prefix}_del')
    new_name=st.text_input('另存為模板名稱', placeholder='例如：常用A', key=f'{key_prefix}_new')
    st.caption(f"目前套用：{st.session_state.get(active_key) or '未選擇'}")
    if load_btn:
        if sel=='(無)': st.warning('請先選擇要載入的模板')
        else:
            payload=gas.get_payload(sheet, sel)
            if payload is None: st.error('載入失敗：請確認雲端連線 / 權限')
            else:
                try:
                    st.session_state[df_key]=from_payload(payload)
                    st.session_state[active_key]=sel
                    st.success(f'已載入：{sel}')
                except Exception as e:
                    st.error(f'載入解析失敗：{e}')
    if save_btn:
        nm=(new_name or '').strip()
        if not nm: st.warning('請先輸入「另存為模板名稱」')
        else:
            ok,msg=gas.create_only(sheet, nm, to_payload(st.session_state[df_key]))
            if ok: st.session_state[active_key]=nm; st.success(msg)
            else: st.error(msg)
    if del_btn:
        if del_sel=='(無)': st.warning('請先選擇要刪除的模板')
        else:
            ok,msg=gas.delete(sheet, del_sel)
            if ok:
                if st.session_state.get(active_key)==del_sel: st.session_state[active_key]=''
                st.success(msg)
            else: st.error(msg)

def box_table_block():
    st.markdown('### 箱型表格（勾選=參與計算；勾選後可刪除）')
    st.markdown('<div class="muted">只保留一個「選取」欄：要參與裝箱就勾選；要刪除就勾選後按「刪除勾選」。</div>', unsafe_allow_html=True)
    df=_sanitize_box(st.session_state.df_box)
    edited=st.data_editor(df, key='box_editor', hide_index=True, num_rows='dynamic', use_container_width=True, height=320,
        column_config={'選取': st.column_config.CheckboxColumn('選取'),
                       '名稱': st.column_config.TextColumn('名稱'),
                       '長': st.column_config.NumberColumn('長', step=0.1, format='%.2f'),
                       '寬': st.column_config.NumberColumn('寬', step=0.1, format='%.2f'),
                       '高': st.column_config.NumberColumn('高', step=0.1, format='%.2f'),
                       '數量': st.column_config.NumberColumn('數量', step=1),
                       '空箱重量': st.column_config.NumberColumn('空箱重量', step=0.01, format='%.2f')})
    b1,b2,b3=st.columns([1,1,1],gap='medium')
    with b1: apply_btn=st.button('✅ 套用變更（外箱表格）', use_container_width=True, key='box_apply')
    with b2: del_btn=st.button('🗑️ 刪除勾選', use_container_width=True, key='box_del')
    with b3: clear_btn=st.button('🧹 清除全部外箱', use_container_width=True, key='box_clear')
    if apply_btn:
        st.session_state.df_box=_sanitize_box(edited); st.success('已套用外箱表格變更')
    if del_btn:
        d=_sanitize_box(edited)
        d=d[~d['選取']].reset_index(drop=True)
        st.session_state.df_box=_sanitize_box(d); st.success('已刪除勾選外箱')
    if clear_btn:
        st.session_state.df_box=_sanitize_box(pd.DataFrame()); st.success('已清除並重置外箱')

def prod_table_block():
    st.markdown('### 商品表格（勾選=參與計算；勾選後可刪除）')
    st.markdown('<div class="muted">只保留一個「選取」欄：要參與裝箱就勾選；要刪除就勾選後按「刪除勾選」。</div>', unsafe_allow_html=True)
    df=_sanitize_prod(st.session_state.df_prod)
    edited=st.data_editor(df, key='prod_editor', hide_index=True, num_rows='dynamic', use_container_width=True, height=320,
        column_config={'選取': st.column_config.CheckboxColumn('選取'),
                       '商品名稱': st.column_config.TextColumn('商品名稱'),
                       '長': st.column_config.NumberColumn('長', step=0.1, format='%.2f'),
                       '寬': st.column_config.NumberColumn('寬', step=0.1, format='%.2f'),
                       '高': st.column_config.NumberColumn('高', step=0.1, format='%.2f'),
                       '重量(kg)': st.column_config.NumberColumn('重量(kg)', step=0.01, format='%.2f'),
                       '數量': st.column_config.NumberColumn('數量', step=1)})
    b1,b2,b3=st.columns([1,1,1],gap='medium')
    with b1: apply_btn=st.button('✅ 套用變更（商品表格）', use_container_width=True, key='prod_apply')
    with b2: del_btn=st.button('🗑️ 刪除勾選', use_container_width=True, key='prod_del')
    with b3: clear_btn=st.button('🧹 清除全部商品', use_container_width=True, key='prod_clear')
    if apply_btn:
        st.session_state.df_prod=_sanitize_prod(edited); st.success('已套用商品表格變更')
    if del_btn:
        d=_sanitize_prod(edited)
        d=d[~d['選取']].reset_index(drop=True)
        st.session_state.df_prod=_sanitize_prod(d); st.success('已刪除勾選商品')
    if clear_btn:
        st.session_state.df_prod=_sanitize_prod(pd.DataFrame()); st.success('已清除並重置商品')

def _choose_box(df_box:pd.DataFrame)->Optional[Dict[str,Any]]:
    for _,r in df_box.iterrows():
        if not bool(r['選取']): continue
        if int(r['數量'])<=0: continue
        if r['長']<=0 or r['寬']<=0 or r['高']<=0: continue
        return {'name':r['名稱'] or '外箱','l':float(r['長']),'w':float(r['寬']),'h':float(r['高']),'tare':float(r['空箱重量'])}
    return None

def _build_items(df_prod:pd.DataFrame)->List[Item]:
    items=[]
    for _,r in df_prod.iterrows():
        if not bool(r['選取']): continue
        qty=int(r['數量'])
        if qty<=0: continue
        if r['長']<=0 or r['寬']<=0 or r['高']<=0: continue
        nm=r['商品名稱'] or '商品'
        for i in range(qty):
            items.append(Item(f"{nm}_{i+1}", float(r['長']), float(r['寬']), float(r['高']), float(r['重量(kg)'])))
    return items

def build_3d_fig(box:Dict[str,Any], fitted:List[Item])->go.Figure:
    palette=['#2F3A4A','#4C6A92','#6C757D','#8E9AAF','#A3B18A','#B08968','#C9ADA7','#6D6875']
    fig=go.Figure()
    L,W,H=box['l'],box['w'],box['h']
    edges=[((0,0,0),(L,0,0)),((L,0,0),(L,W,0)),((L,W,0),(0,W,0)),((0,W,0),(0,0,0)),
           ((0,0,H),(L,0,H)),((L,0,H),(L,W,H)),((L,W,H),(0,W,H)),((0,W,H),(0,0,H)),
           ((0,0,0),(0,0,H)),((L,0,0),(L,0,H)),((L,W,0),(L,W,H)),((0,W,0),(0,W,H))]
    for a,b in edges:
        fig.add_trace(go.Scatter3d(x=[a[0],b[0]],y=[a[1],b[1]],z=[a[2],b[2]],mode='lines',line=dict(width=4,color='#333'),hoverinfo='skip',showlegend=False))
    for i,it in enumerate(fitted):
        c=palette[i%len(palette)]
        px,py,pz=[_to_float(v) for v in getattr(it,'position',[0,0,0])]
        dx,dy,dz=float(it.depth),float(it.width),float(it.height)
        vx=[px,px+dx,px+dx,px,px,px+dx,px+dx,px]
        vy=[py,py,py+dy,py+dy,py,py,py+dy,py+dy]
        vz=[pz,pz,pz,pz,pz+dz,pz+dz,pz+dz,pz+dz]
        faces=[(0,1,2),(0,2,3),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
        I,J,K=zip(*faces)
        fig.add_trace(go.Mesh3d(x=vx,y=vy,z=vz,i=I,j=J,k=K,opacity=0.65,color=c,hovertemplate=f"{it.name}<br>尺寸:{dx:.1f}×{dy:.1f}×{dz:.1f}<extra></extra>",showlegend=False))
    fig.update_layout(scene=dict(xaxis=dict(range=[0,L]),yaxis=dict(range=[0,W]),zaxis=dict(range=[0,H]),aspectmode='data'),margin=dict(l=0,r=0,t=0,b=0),height=520)
    return fig

def build_report_html(order_name:str, box:Dict[str,Any], fitted:List[Item], unfitted:List[Item], content_wt:float, total_wt:float, util:float, fig:go.Figure)->str:
    ts=_now_tw().strftime('%Y-%m-%d %H:%M:%S (台灣時間)')
    fig_div=plotly_offline_plot(fig, output_type='div', include_plotlyjs='cdn')
    warn=''
    if unfitted:
        counts={}
        for it in unfitted:
            base=str(it.name).split('_')[0]
            counts[base]=counts.get(base,0)+1
        warn="<div class='warn'><b>注意：</b>有部分商品裝不下！（可能是箱型庫存不足或尺寸不夠）</div>"+''.join([f"<div class='warn2'>⚠ {k}：超過 {v} 個</div>" for k,v in counts.items()])
    return f"""<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/>
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
    <div style='height:18px'></div><div class='card'>{fig_div}</div></div></body></html>"""

def pack_and_render(order_name:str, df_box:pd.DataFrame, df_prod:pd.DataFrame)->Dict[str,Any]:
    box=_choose_box(df_box)
    if not box: return {'ok':False,'error':'請至少勾選 1 個外箱（且數量>0）'}
    items=_build_items(df_prod)
    if not items: return {'ok':False,'error':'請至少勾選 1 個商品（且數量>0、尺寸>0）'}
    packer=Packer(); packer.add_bin(Bin(box['name'], box['l'], box['w'], box['h'], 999999))
    for it in items: packer.add_item(it)
    try: packer.pack(bigger_first=True, distribute_items=False)
    except TypeError: packer.pack()
    b0=packer.bins[0]
    fitted=list(getattr(b0,'items',[]) or [])
    unfitted=list(getattr(b0,'unfitted_items',[]) or [])
    content_wt=sum(_to_float(getattr(it,'weight',0)) for it in fitted)
    total_wt=content_wt+_to_float(box.get('tare',0))
    used_vol=sum(_to_float(it.width)*_to_float(it.height)*_to_float(it.depth) for it in fitted)
    box_vol=float(box['l']*box['w']*box['h'])
    util=(used_vol/box_vol*100.0) if box_vol>0 else 0.0
    fig=build_3d_fig(box,fitted)
    html=build_report_html(order_name,box,fitted,unfitted,content_wt,total_wt,util,fig)
    return {'ok':True,'box':box,'fitted':fitted,'unfitted':unfitted,'content_wt':content_wt,'total_wt':total_wt,'util':util,'fig':fig,'report_html':html}

def _total_items(df_prod:pd.DataFrame)->int:
    if df_prod is None or df_prod.empty: return 0
    sel=df_prod['選取'].astype(bool)
    return int(df_prod.loc[sel,'數量'].apply(lambda x:int(_to_float(x,0))).sum())

def result_block():
    st.markdown('## 3. 裝箱結果與模擬')
    if st.button('🚀 開始計算與 3D 模擬', use_container_width=True, key='run_pack'):
        try:
            st.session_state.df_box=_sanitize_box(st.session_state.get('box_editor', st.session_state.df_box))
            st.session_state.df_prod=_sanitize_prod(st.session_state.get('prod_editor', st.session_state.df_prod))
        except Exception:
            pass
        with st.spinner('計算中...'):
            st.session_state.last_result=pack_and_render(st.session_state.order_name, st.session_state.df_box, st.session_state.df_prod)
    res=st.session_state.get('last_result')
    if not res: return
    if not res.get('ok'): st.error(res.get('error','計算失敗')); return
    box=res['box']
    st.markdown('<div class="soft-card">', unsafe_allow_html=True)
    st.markdown('<div class="soft-title">裝箱結果</div>', unsafe_allow_html=True)
    st.write(f"訂單：{st.session_state.order_name}")
    st.write(f"使用外箱：{box['name']}（{box['l']}×{box['w']}×{box['h']}）× 1 箱")
    st.write(f"內容淨重：{res['content_wt']:.2f} kg")
    st.write(f"本次總重：{res['total_wt']:.2f} kg")
    st.write(f"空間利用率：{res['util']:.2f}%")
    if res['unfitted']:
        counts={}
        for it in res['unfitted']:
            base=str(it.name).split('_')[0]
            counts[base]=counts.get(base,0)+1
        st.warning('注意：有部分商品裝不下！（可能是箱型庫存不足或尺寸不夠）')
        for k,v in counts.items(): st.error(f"{k}：超過 {v} 個")
    st.markdown('</div>', unsafe_allow_html=True)
    st.plotly_chart(res['fig'], use_container_width=True)
    ts=_now_tw().strftime('%Y%m%d_%H%M')
    fname=f"{_safe_name(st.session_state.order_name)}_{ts}_總數{_total_items(st.session_state.df_prod)}件.html"
    st.download_button('⬇️ 下載完整裝箱報告（.html）', data=res['report_html'].encode('utf-8'), file_name=fname, mime='text/html', use_container_width=True, key='dl_report')

def main():
    _ensure_defaults()
    st.title('📦 3D裝箱系統')
    st.markdown('#### 版面配置')
    mode=st.radio('', ['左右 50% / 50%','上下（垂直）'], horizontal=True, key='layout_radio', index=0 if st.session_state.layout_mode=='左右 50% / 50%' else 1)
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
        st.divider(); result_block()
    else:
        st.markdown('## 1. 訂單與外箱')
        template_block('箱型模板', SHEET_BOX, 'active_box_tpl', 'df_box', _box_payload, _box_from, 'box_tpl_v')
        box_table_block()
        st.divider()
        st.markdown('## 2. 商品清單')
        template_block('商品模板', SHEET_PROD, 'active_prod_tpl', 'df_prod', _prod_payload, _prod_from, 'prod_tpl_v')
        prod_table_block()
        st.divider(); result_block()

if __name__=='__main__':
    main()
