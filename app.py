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
# CSS
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
    .g-gtitle, .g-xtitle, .g-ytitle, .g-ztitle, .legendtext, .tick text {
        fill: #000000 !important; color: #000000 !important; font-family: Arial !important; font-weight: bold !important;
    }
    .block-container { padding-top: 2rem !important; }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統 (強制分層收納版)")
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
        box_l = c1.number_input("長", value=35.0, step=1.0)
        box_w = c2.number_input("寬", value=25.0, step=1.0)
        box_h = c3.number_input("高", value=20.0, step=1.0)
        box_weight = st.number_input("空箱重量 (kg)", value=0.5, step=0.1)

with col_right:
    st.markdown('### 2. 商品清單')
    shape_options = ["不變形", "對折 (鋪底/靠邊)", "L型彎折 (內襯墊底)"]
    
    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame([
            {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5, "變形模式": "不變形"},
            {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5, "變形模式": "對折 (鋪底/靠邊)"}, 
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
    with st.spinner('正在執行強制分層運算...'):
        
        # 1. 絕對帳本初始化
        ledger_request = {}   # 客戶要幾個
        ledger_packed = {}    # 實際裝了幾個
        total_net_weight = 0
        
        # 分類清單
        layer_bottom_items = [] # 強制鋪底 (紙袋)
        layer_wall_items = []   # 強制貼牆 (L型牆面)
        packer_items = []       # 給演算法的 (禮盒)
        
        # 空間扣除量
        reserved_height = 0.0 # 底部被佔用的高度
        reserved_width_x = 0.0 # 側面被佔用的寬度
        
        # 2. 資料前處理
        for index, row in edited_df.iterrows():
            try:
                name = str(row["商品名稱"])
                l, w, h = float(row["長"]), float(row["寬"]), float(row["高"])
                weight = float(row["重量(kg)"])
                qty = int(row["數量"])
                mode = str(row["變形模式"])
                
                if qty > 0:
                    ledger_request[name] = ledger_request.get(name, 0) + qty
                    
                    # === 模式 A: 對折 (強制鋪底) ===
                    if "對折" in mode:
                        folded_l = l / 2
                        folded_h = h * 2
                        total_stack_h = folded_h * qty
                        
                        # 加入鋪底清單
                        layer_bottom_items.append({
                            'name': name, 'l': folded_l, 'w': w, 'h': folded_h, 'qty': qty,
                            'stack_h': total_stack_h, 'weight': weight, 'type': 'folded'
                        })
                        # 增加底部佔用高度
                        reserved_height += total_stack_h
                        
                        # 記入帳本 (因為我們是強制鋪底，視為已裝入)
                        ledger_packed[name] = ledger_packed.get(name, 0) + qty
                        total_net_weight += (weight * qty)

                    # === 模式 B: L型 (強制內襯) ===
                    elif "L型" in mode:
                        wall_t = h * qty
                        floor_t = h * qty
                        
                        # 加入牆壁清單
                        layer_wall_items.append({
                            'name': name, 'l': l, 'w': w, 'h': h, 'qty': qty,
                            'wall_t': wall_t, 'floor_t': floor_t, 'weight': weight, 'type': 'L'
                        })
                        # 增加佔用空間
                        reserved_width_x += wall_t
                        reserved_height += floor_t
                        
                        # 記入帳本
                        ledger_packed[name] = ledger_packed.get(name, 0) + qty
                        total_net_weight += (weight * qty)
                        
                    # === 模式 C: 一般禮盒 (給演算法) ===
                    else:
                        for _ in range(qty):
                            packer_items.append({
                                'item': Item(name, l, w, h, weight),
                                'base_name': name
                            })
                            
            except Exception as e:
                pass

        # 3. 建立縮小的箱子 (演算法只能在剩下的空間玩)
        packer = Packer()
        
        eff_l = box_l - reserved_width_x
        eff_h = box_h - reserved_height
        
        # 保護機制
        if eff_l <= 0 or eff_h <= 0:
            st.error(f"❌ 錯誤：紙袋堆疊後厚度 ({reserved_height}cm) 或寬度 已超過箱子尺寸！")
            st.stop()
            
        # 建立「剩餘空間」箱子
        # 注意：我們把箱子往上抬高 reserved_height，往右移 reserved_width_x
        bin_obj = Bin('Box', eff_l, box_w, eff_h, 999999)
        packer.add_bin(bin_obj)

        # 4. 裝入禮盒
        for p in packer_items:
            packer.add_item(p['item'])
            
        packer.pack(bigger_first=True)

        # ==========================
        # 繪圖
        # ==========================
        fig = go.Figure()
        
        unique_names = list(ledger_request.keys())
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF']
        color_map = {name: palette[i % len(palette)] for i, name in enumerate(unique_names)}

        # 外箱
        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
            z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
            mode='lines', line=dict(color='black', width=5), name='外箱', showlegend=True
        ))

        # --- A. 畫強制鋪底的物品 (對折 / L型底座) ---
        current_z = 0.0
        
        # 先畫 L 型底座
        for item in layer_wall_items:
            c = color_map.get(item['name'], '#888')
            for i in range(item['qty']):
                # L型底座
                fig.add_trace(go.Mesh3d(
                    x=[0, box_l, box_l, 0, 0, box_l, box_l, 0], # 鋪滿長度
                    y=[0, 0, item['w'], item['w'], 0, 0, item['w'], item['w']],
                    z=[current_z, current_z, current_z, current_z, current_z+item['h'], current_z+item['h'], current_z+item['h'], current_z+item['h']],
                    color=c, opacity=1, name=item['name'], showlegend=(i==0)
                ))
                # 黑框
                fig.add_trace(go.Scatter3d(
                    x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
                    y=[0, 0, item['w'], item['w'], 0, 0, 0, 0, item['w'], item['w'], 0, item['w'], item['w'], item['w'], 0, 0],
                    z=[current_z, current_z, current_z, current_z, current_z, current_z+item['h'], current_z+item['h'], current_z+item['h'], current_z+item['h'], current_z+item['h'], current_z, current_z+item['h'], current_z+item['h'], current_z+item['h'], current_z, current_z],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))
                current_z += item['h']
                
            # 順便畫 L 型側牆 (堆疊在 X 軸)
            current_x_wall = 0
            for i in range(item['qty']):
                vis_h = item['l'] * 0.3
                fig.add_trace(go.Mesh3d(
                    x=[current_x_wall, current_x_wall+item['h'], current_x_wall+item['h'], current_x_wall, current_x_wall, current_x_wall+item['h'], current_x_wall+item['h'], current_x_wall],
                    y=[0, 0, item['w'], item['w'], 0, 0, item['w'], item['w']],
                    z=[0, 0, 0, 0, vis_h, vis_h, vis_h, vis_h],
                    color=c, opacity=1, showlegend=False
                ))
                # 側牆框
                fig.add_trace(go.Scatter3d(
                    x=[current_x_wall, current_x_wall+item['h'], current_x_wall+item['h'], current_x_wall, current_x_wall, current_x_wall, current_x_wall+item['h'], current_x_wall+item['h'], current_x_wall, current_x_wall, current_x_wall, current_x_wall, current_x_wall+item['h'], current_x_wall+item['h'], current_x_wall+item['h'], current_x_wall+item['h']],
                    y=[0, 0, item['w'], item['w'], 0, 0, 0, 0, item['w'], item['w'], 0, item['w'], item['w'], item['w'], 0, 0],
                    z=[0, 0, 0, 0, 0, vis_h, vis_h, vis_h, vis_h, vis_h, 0, vis_h, vis_h, vis_h, 0, 0],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))
                current_x_wall += item['h']

        # 再畫 對折紙袋 (堆疊在 L 型底座之上)
        for item in layer_bottom_items:
            c = color_map.get(item['name'], '#888')
            # 必須把對折紙袋靠角落放 (X=0 或 X=reserved_width_x)
            start_x = reserved_width_x
            
            for i in range(item['qty']):
                unit_h = item['h'] # 對折後的高度
                
                # 繪製實體
                fig.add_trace(go.Mesh3d(
                    x=[start_x, start_x+item['l'], start_x+item['l'], start_x, start_x, start_x+item['l'], start_x+item['l'], start_x],
                    y=[0, 0, item['w'], item['w'], 0, 0, item['w'], item['w']],
                    z=[current_z, current_z, current_z, current_z, current_z+unit_h, current_z+unit_h, current_z+unit_h, current_z+unit_h],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=c, opacity=1, name=item['name'], showlegend=(i==0)
                ))
                # 繪製黑框
                fig.add_trace(go.Scatter3d(
                    x=[start_x, start_x+item['l'], start_x+item['l'], start_x, start_x, start_x, start_x+item['l'], start_x+item['l'], start_x, start_x, start_x, start_x, start_x+item['l'], start_x+item['l'], start_x+item['l'], start_x+item['l']],
                    y=[0, 0, item['w'], item['w'], 0, 0, 0, 0, item['w'], item['w'], 0, item['w'], item['w'], item['w'], 0, 0],
                    z=[current_z, current_z, current_z, current_z, current_z, current_z+unit_h, current_z+unit_h, current_z+unit_h, current_z+unit_h, current_z+unit_h, current_z, current_z+unit_h, current_z+unit_h, current_z+unit_h, current_z, current_z],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))
                current_z += unit_h

        # --- B. 畫 Packer 禮盒 (漂浮在堆疊層之上) ---
        total_vol = 0
        
        for b in packer.bins:
            for item in b.items:
                base_name = item.name
                
                # 記入帳本
                ledger_packed[base_name] = ledger_packed.get(base_name, 0) + 1
                total_net_weight += float(item.weight)
                
                x, y, z = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                w, d, h = float(dim[0]), float(dim[1]), float(dim[2])
                
                # 座標偏移：X 加上 L型牆厚，Z 加上 底部堆疊總高
                fx = x + reserved_width_x
                fy = y 
                fz = z + reserved_height
                
                total_vol += (w * d * h)
                c = color_map.get(base_name, '#888')

                fig.add_trace(go.Mesh3d(
                    x=[fx, fx+w, fx+w, fx, fx, fx+w, fx+w, fx], 
                    y=[fy, fy, fy+d, fy+d, fy, fy, fy+d, fy+d], 
                    z=[fz, fz, fz, fz, fz+h, fz+h, fz+h, fz+h],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=c, opacity=1, name=base_name, showlegend=True, hoverinfo='text', text=base_name
                ))
                fig.add_trace(go.Scatter3d(
                    x=[fx, fx+w, fx+w, fx, fx, fx, fx+w, fx+w, fx, fx, fx, fx, fx+w, fx+w, fx+w, fx+w],
                    y=[fy, fy, fy+d, fy+d, fy, fy, fy, fy, fy+d, fy+d, fy, fy+d, fy+d, fy+d, fy, fy],
                    z=[fz, fz, fz, fz, fz, fz+h, fz+h, fz+h, fz+h, fz+h, fz, fz+h, fz+h, fz+h, fz, fz],
                    mode='lines', line=dict(color='black', width=3), showlegend=False
                ))

        # 去重
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # Layout
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

        # 5. 報表
        box_vol = box_l * box_w * box_h
        # 內襯體積
        lining_vol = 0
        for item in layer_bottom_items:
            lining_vol += (item['l'] * item['w'] * item['stack_h'])
        for item in layer_wall_items:
            lining_vol += (item['l'] * item['w'] * item['floor_t']) # 底
            lining_vol += (item['wall_t'] * item['w'] * (item['l']*0.3)) # 牆 (模擬高度)
        
        utilization = ((total_vol + lining_vol) / box_vol) * 100 if box_vol > 0 else 0
        gross_weight = total_net_weight + box_weight
        
        all_fitted = True
        missing_html = ""
        
        for name, req in ledger_request.items():
            real = ledger_packed.get(name, 0)
            diff = req - real
            if diff > 0:
                all_fitted = False
                missing_html += f"<li style='color:red; background:#ffd2d2; padding:5px;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status = "<h3 style='color:green; background:#d4edda; padding:10px; border-radius:5px;'>✅ 完美裝箱</h3>" if all_fitted else f"<h3 style='color:red; background:#f8d7da; padding:10px; border-radius:5px;'>❌ 部分遺漏</h3><ul>{missing_html}</ul>"

        report_html = f"""
        <div class="report-card">
            <h2>📋 訂單裝箱報告</h2>
            <p><b>訂單:</b> {order_name} | <b>外箱:</b> {box_l}x{box_w}x{box_h} cm | <b>利用率:</b> {utilization:.2f}%</p>
            <p><b>總重量:</b> {gross_weight:.2f} kg</p>
            {status}
        </div>
        """
        st.markdown(report_html, unsafe_allow_html=True)
        st.download_button("📥 下載報告", report_html, "report.html", "text/html", type="primary")
        st.plotly_chart(fig, use_container_width=True, theme=None, config={'displayModeBar': False})
