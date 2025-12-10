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
# CSS 優化
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
    
    /* 強制圖例與坐標軸文字為黑色 */
    .g-gtitle, .g-xtitle, .g-ytitle, .g-ztitle, .legendtext, .tick text {
        fill: #000000 !important;
        color: #000000 !important;
        font-family: Arial, sans-serif !important;
        font-weight: bold !important;
    }
    
    .block-container { padding-top: 2rem !important; }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統 (穩定修復版)")
st.markdown("---")

# ==========================
# 輸入區
# ==========================
col_left, col_right = st.columns([1, 2], gap="large")

with col_left:
    st.markdown('### 1. 訂單與外箱')
    with st.container():
        order_name = st.text_input("訂單名稱", value="訂單_20241208")
        st.caption("外箱尺寸 (cm)")
        c1, c2, c3 = st.columns(3)
        box_l = c1.number_input("長", value=30.0, step=1.0)
        box_w = c2.number_input("寬", value=25.0, step=1.0)
        box_h = c3.number_input("高", value=15.0, step=1.0)
        box_weight = st.number_input("空箱重量 (kg)", value=0.5, step=0.1)

with col_right:
    st.markdown('### 2. 商品清單')
    shape_options = ["不變形", "對折 (長度/2, 高度x2)", "L型彎折 (作為內襯墊底)"]
    
    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame([
            {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 3, "變形模式": "不變形"},
            {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 3, "變形模式": "不變形"}, 
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
    with st.spinner('正在進行智慧演算...'):
        
        # 1. 變數初始化 (Single Source of Truth)
        requested_counts = {}   # 客戶需求
        packed_ledger = {}      # 總帳本
        
        packer_items = []       # 一般物品 (給演算法)
        lining_config = None    # L型內襯 (手動處理)
        
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
                    requested_counts[name] = requested_counts.get(name, 0) + qty
                    
                    # === 分流 A: L型內襯 (手動強制安裝) ===
                    if mode == "L型彎折 (作為內襯墊底)":
                        total_wall_thick = h * qty  
                        total_floor_h = h * qty     
                        visual_wall_h = l * 0.3 
                        
                        lining_config = {
                            'name': name, 'l': l, 'w': w, 'h': h, 'qty': qty,
                            'offset_x': total_wall_thick, 
                            'offset_z': total_floor_h,    
                            'visual_wall_h': visual_wall_h,
                            'weight': weight
                        }
                        
                        # 直接記入總帳本
                        packed_ledger[name] = packed_ledger.get(name, 0) + qty
                        total_net_weight += (weight * qty)
                        
                    # === 分流 B: 丟給演算法 (對折/不變形) ===
                    else:
                        current_l, current_h = l, h
                        suffix = ""
                        
                        if "對折" in mode:
                            current_l = l / 2
                            current_h = h * 2
                            suffix = "(對折)"
                        
                        # 優先級邏輯：極薄物品(紙袋)最優先放入
                        vol = current_l * w * current_h
                        
                        # 判斷是否為「薄板」(例如紙袋)，給予極高優先權 (priority=0)
                        # 其他物品依體積排序，小的先放 (priority=vol)
                        # 這樣可以確保「大面積但很薄」的紙袋先鋪在底下
                        priority = vol
                        if h < 1.0: priority = 0 
                        elif "對折" in mode: priority = vol * 0.5 # 對折的稍微優先一點
                        
                        for _ in range(qty):
                            packer_items.append({
                                'item': Item(f"{name}{suffix}", current_l, w, current_h, weight),
                                'priority': priority,
                                'base_name': name 
                            })
                            
            except Exception as e:
                pass

        # 3. 準備 Packer 環境
        packer = Packer()
        
        # L型內襯空間扣除
        if lining_config:
            eff_l = box_l - lining_config['offset_x']
            eff_h = box_h - lining_config['offset_z']
            offset_x = lining_config['offset_x']
            offset_z = lining_config['offset_z']
            
            if eff_l <= 0 or eff_h <= 0:
                st.error("❌ 錯誤：L型內襯太厚，已佔滿箱子！")
                st.stop()
            box = Bin('StandardBox', eff_l, box_w, eff_h, 999999)
        else:
            box = Bin('StandardBox', box_l, box_w, box_h, 999999)
            offset_x = 0
            offset_z = 0
            
        packer.add_bin(box)

        # 4. 關鍵排序與裝箱
        packer_items.sort(key=lambda x: x['priority'])
        
        for p_data in packer_items:
            packer.add_item(p_data['item'])
            
        packer.pack(bigger_first=False) 

        # ==========================
        # 繪圖與報表整合
        # ==========================
        fig = go.Figure()
        
        # 畫外箱
        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
            z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
            mode='lines', line=dict(color='black', width=5), name='外箱', showlegend=True
        ))

        # 顏色
        unique_names = list(requested_counts.keys())
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF']
        colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_names)}

        # --- A. 繪製手動 L 型內襯 ---
        if lining_config:
            name = lining_config['name']
            qty = lining_config['qty']
            unit_h = lining_config['h']
            l_real = lining_config['l']
            w_real = lining_config['w']
            vis_h = lining_config['visual_wall_h']
            c = colors.get(name, '#888')
            
            for i in range(qty):
                # 底座
                fz = i * unit_h
                fl_draw = min(l_real, box_l)
                
                fig.add_trace(go.Mesh3d(
                    x=[0, fl_draw, fl_draw, 0, 0, fl_draw, fl_draw, 0],
                    y=[0, 0, w_real, w_real, 0, 0, w_real, w_real],
                    z=[fz, fz, fz, fz, fz+unit_h, fz+unit_h, fz+unit_h, fz+unit_h],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=c, opacity=1, name=name, showlegend=(i==0)
                ))
                fig.add_trace(go.Scatter3d(
                    x=[0, fl_draw, fl_draw, 0, 0, 0, fl_draw, fl_draw, 0, 0, 0, 0, fl_draw, fl_draw, fl_draw, fl_draw],
                    y=[0, 0, w_real, w_real, 0, 0, 0, 0, w_real, w_real, 0, w_real, w_real, w_real, 0, 0],
                    z=[fz, fz, fz, fz, fz, fz+unit_h, fz+unit_h, fz+unit_h, fz+unit_h, fz+unit_h, fz, fz+unit_h, fz+unit_h, fz+unit_h, fz, fz],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))

                # 側牆
                wx = i * unit_h
                fig.add_trace(go.Mesh3d(
                    x=[wx, wx+unit_h, wx+unit_h, wx, wx, wx+unit_h, wx+unit_h, wx],
                    y=[0, 0, w_real, w_real, 0, 0, w_real, w_real],
                    z=[0, 0, 0, 0, vis_h, vis_h, vis_h, vis_h],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=c, opacity=1, showlegend=False
                ))
                fig.add_trace(go.Scatter3d(
                    x=[wx, wx+unit_h, wx+unit_h, wx, wx, wx, wx+unit_h, wx+unit_h, wx, wx, wx, wx, wx+unit_h, wx+unit_h, wx+unit_h, wx+unit_h],
                    y=[0, 0, w_real, w_real, 0, 0, 0, 0, w_real, w_real, 0, w_real, w_real, w_real, 0, 0],
                    z=[0, 0, 0, 0, 0, vis_h, vis_h, vis_h, vis_h, vis_h, 0, vis_h, vis_h, vis_h, 0, 0],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))

        # --- B. 繪製 Packer 物品 ---
        total_vol = 0
        
        for b in packer.bins:
            for item in b.items:
                raw_name = item.name
                base_name = raw_name.split('(')[0] 
                
                # 記入總帳本
                packed_ledger[base_name] = packed_ledger.get(base_name, 0) + 1
                total_net_weight += float(item.weight)
                
                x, y, z = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                w, d, h = float(dim[0]), float(dim[1]), float(dim[2])
                
                final_x = x + offset_x
                final_y = y 
                final_z = z + offset_z
                
                total_vol += (w * d * h)
                c = colors.get(base_name, '#888')

                fig.add_trace(go.Mesh3d(
                    x=[final_x, final_x+w, final_x+w, final_x, final_x, final_x+w, final_x+w, final_x], 
                    y=[final_y, final_y, final_y+d, final_y+d, final_y, final_y, final_y+d, final_y+d], 
                    z=[final_z, final_z, final_z, final_z, final_z+h, final_z+h, final_z+h, final_z+h],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=c, opacity=1, name=base_name, showlegend=True, hoverinfo='text', 
                    text=f"{base_name}"
                ))
                fig.add_trace(go.Scatter3d(
                    x=[final_x, final_x+w, final_x+w, final_x, final_x, final_x, final_x+w, final_x+w, final_x, final_x, final_x, final_x, final_x+w, final_x+w, final_x+w, final_x+w],
                    y=[final_y, final_y, final_y+d, final_y+d, final_y, final_y, final_y, final_y, final_y+d, final_y+d, final_y, final_y+d, final_y+d, final_y, final_y, final_y+d],
                    z=[final_z, final_z, final_z, final_z, final_z, final_z+h, final_z+h, final_z+h, final_z+h, final_z+h, final_z, final_z+h, final_z+h, final_z+h, final_z, final_z],
                    mode='lines', line=dict(color='black', width=3), showlegend=False
                ))

        # 去重
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # Layout 設定 (修正版：標準結構)
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
        if lining_config:
            l_v = lining_config['offset_x'] * lining_config['w'] * lining_config['visual_wall_h']
            l_f = (box_l - lining_config['offset_x']) * lining_config['w'] * lining_config['offset_z']
            lining_vol = l_v + l_f

        final_utilization = ((total_vol + lining_vol) / box_vol) * 100 if box_vol > 0 else 0
        gross_weight = total_net_weight + box_weight
        
        all_fitted = True
        missing_html = ""
        
        for name, req in requested_counts.items():
            real = packed_ledger.get(name, 0)
            diff = req - real
            if diff > 0:
                all_fitted = False
                missing_html += f"<li style='color:red; background:#ffd2d2; padding:5px;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status = "<h3 style='color:green; background:#d4edda; padding:10px; border-radius:5px;'>✅ 完美裝箱</h3>" if all_fitted else f"<h3 style='color:red; background:#f8d7da; padding:10px; border-radius:5px;'>❌ 部分遺漏</h3><ul>{missing_html}</ul>"

        report_html = f"""
        <div class="report-card">
            <h2>📋 訂單裝箱報告</h2>
            <p><b>訂單:</b> {order_name} | <b>外箱:</b> {box_l}x{box_w}x{box_h} cm | <b>利用率:</b> {final_utilization:.2f}%</p>
            <p><b>總重量:</b> {gross_weight:.2f} kg</p>
            {status}
        </div>
        """
        st.markdown(report_html, unsafe_allow_html=True)
        st.download_button("📥 下載報告", report_html, "report.html", "text/html", type="primary")
        st.plotly_chart(fig, use_container_width=True, theme=None, config={'displayModeBar': False})
