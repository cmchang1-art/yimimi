import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import datetime

# ==========================
# 頁面設定
# ==========================
st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="collapsed")

# ==========================
# CSS (修復字體顏色與介面)
# ==========================
st.markdown("""
<style>
    .stApp { background-color: #ffffff !important; color: #000000 !important; }
    [data-testid="stSidebar"], [data-testid="stDecoration"], .stDeployButton, footer, #MainMenu, [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stHeader"] { background-color: transparent !important; pointer-events: none; }
    div[data-baseweb="input"] input, div[data-baseweb="select"] div, .stDataFrame, .stTable {
        color: #000000 !important; background-color: #f9f9f9 !important; border-color: #cccccc !important;
    }
    .report-card {
        padding: 20px; border: 2px solid #e0e0e0; border-radius: 10px; 
        background: #ffffff; color: #333333; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 20px;
    }
    /* 強制所有圖表文字黑色 */
    .g-gtitle, .g-xtitle, .g-ytitle, .g-ztitle, .legendtext, .tick text {
        fill: #000000 !important; color: #000000 !important; font-family: Arial !important; font-weight: bold !important;
    }
    .block-container { padding-top: 2rem !important; }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統 (會計帳本修正版)")
st.markdown("---")

# ==========================
# 輸入區
# ==========================
col_left, col_right = st.columns([1, 2], gap="large")

with col_left:
    st.markdown('### 1. 訂單與外箱')
    with st.container():
        order_name = st.text_input("訂單名稱", value="訂單_20241208")
        c1, c2, c3 = st.columns(3)
        box_l = c1.number_input("長", value=35.0, step=1.0) # 依照您截圖調整預設值
        box_w = c2.number_input("寬", value=25.0, step=1.0)
        box_h = c3.number_input("高", value=20.0, step=1.0)
        box_weight = st.number_input("空箱重量 (kg)", value=0.5, step=0.1)

with col_right:
    st.markdown('### 2. 商品清單')
    shape_options = ["不變形", "對折 (長度/2, 高度x2)", "L型彎折 (內襯墊底)"]
    
    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame([
            {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5, "變形模式": "不變形"},
            {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5, "變形模式": "對折 (長度/2, 高度x2)"}, 
        ])

    edited_df = st.data_editor(
        st.session_state.df, num_rows="dynamic", use_container_width=True, height=280,
        column_config={
            "數量": st.column_config.NumberColumn(min_value=1, step=1, format="%d"),
            "長": st.column_config.NumberColumn(format="%.1f"),
            "寬": st.column_config.NumberColumn(format="%.1f"),
            "高": st.column_config.NumberColumn(format="%.1f"),
            "重量(kg)": st.column_config.NumberColumn(format="%.2f"),
            "變形模式": st.column_config.SelectboxColumn(label="變形策略", width="medium", options=shape_options, required=True)
        }
    )

st.markdown("---")
b1, b2, b3 = st.columns([1, 2, 1])
with b2:
    run_button = st.button("🚀 開始計算與 3D 模擬", type="primary", use_container_width=True)

# ==========================
# 核心運算
# ==========================
if run_button:
    with st.spinner('正在進行最佳化演算...'):
        
        # 1. 變數初始化 (絕對真理帳本)
        # ledger_request: 客戶要幾個
        # ledger_actual: 實際上裝了幾個 (無論是手動還是自動)
        ledger_request = {}   
        ledger_actual = {}      
        
        packer_items = []       # 給演算法的清單
        lining_data = None      # 手動 L 型內襯資料
        total_net_weight = 0
        
        # 2. 資料分類與預處理
        for index, row in edited_df.iterrows():
            try:
                name = str(row["商品名稱"])
                l, w, h = float(row["長"]), float(row["寬"]), float(row["高"])
                weight = float(row["重量(kg)"])
                qty = int(row["數量"])
                mode = str(row["變形模式"])
                
                if qty > 0:
                    ledger_request[name] = ledger_request.get(name, 0) + qty
                    
                    # === 策略 A: L型內襯 (手動繪製，物理扣除) ===
                    if mode == "L型彎折 (內襯墊底)":
                        # 計算佔用空間
                        wall_thickness = h * qty
                        floor_thickness = h * qty
                        
                        lining_data = {
                            'name': name, 'l': l, 'w': w, 'h': h, 'qty': qty,
                            'off_x': wall_thickness, 
                            'off_z': floor_thickness,    
                            'vis_h': l * 0.3,
                            'weight': weight
                        }
                        
                        # 【關鍵修正】手動處理的直接寫入「實際帳本」
                        ledger_actual[name] = ledger_actual.get(name, 0) + qty
                        total_net_weight += (weight * qty)
                        
                    # === 策略 B: 對折 (實體綑綁堆疊 - 解決佔位問題) ===
                    elif "對折" in mode:
                        folded_l = l / 2
                        folded_h = h * 2
                        
                        # 【關鍵修正】將 5 個對折紙袋「捆」成 1 個大包
                        # 這樣演算法就會把它當作一個整體，放在角落，不會散落各地
                        stack_h = folded_h * qty
                        stack_weight = weight * qty
                        
                        packer_items.append({
                            'item': Item(f"{name}(Stack)", folded_l, w, stack_h, stack_weight),
                            'area': 999999, # 設定超大權重，保證第一個放入 (靠角落)
                            'base_name': name,
                            'is_stack': True,
                            'stack_qty': qty, # 記住這一包裡面有幾個
                            'unit_h': folded_h
                        })
                        
                    # === 策略 C: 攤平/不變形 (底面積排序 - 解決放不下問題) ===
                    else:
                        area = l * w 
                        # 這裡我們不捆綁，因為攤平通常是為了鋪滿底部
                        # 但我們要確保它比禮盒先放入
                        for _ in range(qty):
                            packer_items.append({
                                'item': Item(name, l, w, h, weight),
                                'area': area, # 面積大的先放
                                'base_name': name,
                                'is_stack': False,
                                'stack_qty': 1,
                                'unit_h': h
                            })
                            
            except Exception as e:
                pass

        # 3. 準備 Packer (如果有L型，縮小箱子)
        packer = Packer()
        
        # 內襯空間扣除邏輯
        if lining_data:
            eff_l = box_l - lining_data['off_x']
            eff_h = box_h - lining_data['off_z']
            offset_x = lining_data['off_x']
            offset_z = lining_data['off_z']
            
            if eff_l <= 0 or eff_h <= 0:
                st.error("❌ 錯誤：內襯太厚，已佔滿整個箱子！")
                st.stop()
            bin_obj = Bin('Box', eff_l, box_w, eff_h, 999999)
        else:
            bin_obj = Bin('Box', box_l, box_w, box_h, 999999)
            offset_x = 0
            offset_z = 0
            
        packer.add_bin(bin_obj)

        # 4. 排序並裝箱
        # 排序邏輯：綑綁包(Stack) -> 大面積薄板(Flat) -> 小體積盒子
        packer_items.sort(key=lambda x: x['area'], reverse=True)
        
        for p in packer_items:
            packer.add_item(p['item'])
            
        # 執行裝箱 (bigger_first=False: 嚴格遵守我們設定的順序)
        packer.pack(bigger_first=False)

        # ==========================
        # 繪圖與帳本核對
        # ==========================
        fig = go.Figure()
        
        # 顏色
        unique_names = list(ledger_request.keys())
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF']
        color_map = {name: palette[i % len(palette)] for i, name in enumerate(unique_names)}

        # 1. 畫外箱
        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
            z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
            mode='lines', line=dict(color='black', width=5), name='外箱', showlegend=True
        ))

        # 2. 畫 L 型內襯 (如果有的話)
        # 注意：L型的數量已經在上面加過 ledger_actual 了，這裡只負責畫
        if lining_data:
            lname = lining_data['name']
            lqty = lining_data['qty']
            uh = lining_data['h']
            lc = color_map.get(lname, '#888')
            
            for i in range(lqty):
                fz = i * uh
                l_draw = min(lining_data['l'], box_l)
                
                # 底座 Mesh + Wireframe
                fig.add_trace(go.Mesh3d(
                    x=[0, l_draw, l_draw, 0, 0, l_draw, l_draw, 0],
                    y=[0, 0, lining_data['w'], lining_data['w'], 0, 0, lining_data['w'], lining_data['w']],
                    z=[fz, fz, fz, fz, fz+uh, fz+uh, fz+uh, fz+uh],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=lc, opacity=1, name=lname, showlegend=(i==0)
                ))
                fig.add_trace(go.Scatter3d(
                    x=[0, l_draw, l_draw, 0, 0, 0, l_draw, l_draw, 0, 0, 0, 0, l_draw, l_draw, l_draw, l_draw],
                    y=[0, 0, lining_data['w'], lining_data['w'], 0, 0, 0, 0, lining_data['w'], lining_data['w'], 0, lining_data['w'], lining_data['w'], lining_data['w'], 0, 0],
                    z=[fz, fz, fz, fz, fz, fz+uh, fz+uh, fz+uh, fz+uh, fz+uh, fz, fz+unit_h, fz+unit_h, fz+unit_h, fz, fz],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))
                
                # 側牆 Mesh + Wireframe
                wx = i * uh
                fig.add_trace(go.Mesh3d(
                    x=[wx, wx+uh, wx+uh, wx, wx, wx+uh, wx+uh, wx],
                    y=[0, 0, lining_data['w'], lining_data['w'], 0, 0, lining_data['w'], lining_data['w']],
                    z=[0, 0, 0, 0, lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h']],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=lc, opacity=1, showlegend=False
                ))
                fig.add_trace(go.Scatter3d(
                    x=[wx, wx+uh, wx+uh, wx, wx, wx, wx+uh, wx+uh, wx, wx, wx, wx, wx+uh, wx+uh, wx+uh, wx+uh],
                    y=[0, 0, lining_data['w'], lining_data['w'], 0, 0, 0, 0, lining_data['w'], lining_data['w'], 0, lining_data['w'], lining_data['w'], lining_data['w'], 0, 0],
                    z=[0, 0, 0, 0, 0, lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h'], 0, lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h'], 0, 0],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))

        # 3. 畫 Packer 物品
        total_vol = 0
        packer_data_map = {p['item'].name: p for p in packer_items} 

        for b in packer.bins:
            for item in b.items:
                raw_name = item.name
                base_name = raw_name.split('(')[0]
                
                # 取得資料
                p_data = packer_data_map.get(raw_name)
                is_stack = p_data.get('is_stack', False) if p_data else False
                stack_qty = p_data.get('stack_qty', 1) if p_data else 1
                unit_h = p_data.get('unit_h', 0) if p_data else 0
                
                # 【關鍵修正】這時候才將演算法的結果寫入「實際帳本」
                ledger_actual[base_name] = ledger_actual.get(base_name, 0) + stack_qty
                total_net_weight += float(item.weight)
                
                # 座標處理
                x, y, z = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                w, d, h = float(dim[0]), float(dim[1]), float(dim[2])
                
                fx, fy, fz = x + offset_x, y, z + offset_z
                total_vol += (w * d * h)
                pc = color_map.get(base_name, '#888')

                if is_stack:
                    # 堆疊包：畫出整體與分隔線
                    fig.add_trace(go.Mesh3d(
                        x=[fx, fx+w, fx+w, fx, fx, fx+w, fx+w, fx], 
                        y=[fy, fy, fy+d, fy+d, fy, fy, fy+d, fy+d], 
                        z=[fz, fz, fz, fz, fz+h, fz+h, fz+h, fz+h],
                        i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                        color=pc, opacity=1, name=base_name, showlegend=True, hoverinfo='text', text=f"{base_name} (堆疊x{stack_qty})"
                    ))
                    fig.add_trace(go.Scatter3d(
                        x=[fx, fx+w, fx+w, fx, fx, fx, fx+w, fx+w, fx, fx, fx, fx, fx+w, fx+w, fx+w, fx+w],
                        y=[fy, fy, fy+d, fy+d, fy, fy, fy, fy, fy+d, fy+d, fy, fy+d, fy+d, fy+d, fy, fy],
                        z=[fz, fz, fz, fz, fz, fz+h, fz+h, fz+h, fz+h, fz+h, fz, fz+h, fz+h, fz+h, fz, fz],
                        mode='lines', line=dict(color='black', width=3), showlegend=False
                    ))
                    for i in range(1, stack_qty):
                        lz = fz + (i * unit_h)
                        fig.add_trace(go.Scatter3d(
                            x=[fx, fx+w, fx+w, fx, fx],
                            y=[fy, fy, fy+d, fy+d, fy],
                            z=[lz, lz, lz, lz, lz],
                            mode='lines', line=dict(color='black', width=1), showlegend=False
                        ))
                else:
                    # 一般物品
                    fig.add_trace(go.Mesh3d(
                        x=[fx, fx+w, fx+w, fx, fx, fx+w, fx+w, fx], 
                        y=[fy, fy, fy+d, fy+d, fy, fy, fy+d, fy+d], 
                        z=[fz, fz, fz, fz, fz+h, fz+h, fz+h, fz+h],
                        i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                        color=pc, opacity=1, name=base_name, showlegend=True, hoverinfo='text', text=base_name
                    ))
                    fig.add_trace(go.Scatter3d(
                        x=[fx, fx+w, fx+w, fx, fx, fx, fx+w, fx+w, fx, fx, fx, fx, fx+w, fx+w, fx+w, fx+w],
                        y=[fy, fy, fy+d, fy+d, fy, fy, fy, fy, fy+d, fy+d, fy, fy+d, fy+d, fy+d, fy, fy],
                        z=[fz, fz, fz, fz, fz, fz+h, fz+h, fz+h, fz+h, fz+h, fz, fz+h, fz+h, fz+h, fz, fz],
                        mode='lines', line=dict(color='black', width=3), showlegend=False
                    ))

        # 去重圖例
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # Layout 設定 (標準結構)
        fig.update_layout(
            template="plotly_white",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color="black"),
            scene=dict(
                xaxis=dict(title=dict(text='長 (L)', font=dict(color="black")), tickfont=dict(color="black"), backgroundcolor="white", gridcolor="#999999", showbackground=True),
                yaxis=dict(title=dict(text='寬 (W)', font=dict(color="black")), tickfont=dict(color="black"), backgroundcolor="white", gridcolor="#999999", showbackground=True),
                zaxis=dict(title=dict(text='高 (H)', font=dict(color="black")), tickfont=dict(color="black"), backgroundcolor="white", gridcolor="#999999", showbackground=True),
                aspectmode='data',
                camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))
            ),
            margin=dict(t=30, b=0, l=0, r=0),
            height=600,
            legend=dict(x=0, y=1, bgcolor="rgba(255,255,255,0.8)", borderwidth=1, font=dict(color="black"))
        )

        # 4. 產生報表
        box_vol = box_l * box_w * box_h
        lining_vol = 0
        if lining_data:
            lining_vol = (lining_data['off_x'] * lining_data['w'] * lining_data['vis_h']) + \
                         ((box_l - lining_data['off_x']) * lining_data['w'] * lining_data['off_z'])
        
        utilization = ((total_vol + lining_vol) / box_vol) * 100 if box_vol > 0 else 0
        gross_weight = total_net_weight + box_weight
        
        all_fitted = True
        missing_html = ""
        
        # 比對 ledger_request vs ledger_actual (這就是最精準的比較)
        for name, req in ledger_request.items():
            real = ledger_actual.get(name, 0)
            diff = req - real
            if diff > 0:
                all_fitted = False
                missing_html += f"<li style='color:red; background:#ffd2d2; padding:5px;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status = "<h3 style='color:green; background:#d4edda; padding:10px; border-radius:5px;'>✅ 完美裝箱</h3>" if all_fitted else f"<h3 style='color:red; background:#f8d7da; padding:10px; border-radius:5px;'>❌ 部分遺漏</h3><ul>{missing_html}</ul>"

        report_html = f"""
        <div class="report-card">
            <h2>📋 訂單裝箱報告</h2>
            <p><b>訂單:</b> {order_name} | <b>外箱:</b> {box_l}x{box_w}x{box_h} cm | <b>利用率:</b> {utilization:.2f}%</p>
            <p><b>裝入數/需求數:</b> {str(ledger_actual)} / {str(ledger_request)}</p>
            <p><b>總重量:</b> {gross_weight:.2f} kg</p>
            {status}
        </div>
        """
        st.markdown(report_html, unsafe_allow_html=True)
        st.download_button("📥 下載報告", report_html, "report.html", "text/html", type="primary")
        st.plotly_chart(fig, use_container_width=True, theme=None, config={'displayModeBar': False})
