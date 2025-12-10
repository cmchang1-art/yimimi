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
    .block-container { padding-top: 2rem !important; }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統 (全模式修正版)")
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
            {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 3, "變形模式": "L型彎折 (作為內襯墊底)"},
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
    with st.spinner('運算中...'):
        
        # 初始化變數
        requested_counts = {}   # 原始需求數量
        manual_packed_counts = {} # 手動處理(L型)的數量
        packer_items = []       # 要丟給演算法算的物品
        lining_config = None    # 儲存L型內襯設定
        
        # 1. 資料分類與預處理
        for index, row in edited_df.iterrows():
            try:
                name = str(row["商品名稱"])
                l, w, h = float(row["長"]), float(row["寬"]), float(row["高"])
                weight = float(row["重量(kg)"])
                qty = int(row["數量"])
                mode = str(row["變形模式"])
                
                if qty > 0:
                    # 記錄總需求
                    requested_counts[name] = requested_counts.get(name, 0) + qty
                    
                    # === 模式 A: L型內襯 (手動處理) ===
                    if mode == "L型彎折 (作為內襯墊底)":
                        # 記錄下來，不放入 packer_items
                        # 計算佔用空間：所有數量疊加
                        total_wall_thick = h * qty  # 側牆總厚度 (原高變厚)
                        total_floor_h = h * qty     # 底座總高度
                        
                        # 視覺上側牆豎起來的高度 (模擬為長度的30%)
                        visual_wall_h = l * 0.3 
                        
                        lining_config = {
                            'name': name,
                            'l': l, 'w': w, 'h': h,
                            'qty': qty,
                            'offset_x': total_wall_thick, # 內縮量 X
                            'offset_z': total_floor_h,    # 內縮量 Z
                            'visual_wall_h': visual_wall_h
                        }
                        # 直接標記為「已裝入」，因為我們是強制畫上去的
                        manual_packed_counts[name] = qty
                        
                    # === 模式 B: 對折 (標準演算法) ===
                    elif "對折" in mode:
                        for _ in range(qty):
                            # 對折：長度減半，高度加倍
                            packer_items.append(Item(f"{name}(對折)", l/2, w, h*2, weight))
                            
                    # === 模式 C: 不變形/攤平 (標準演算法) ===
                    else:
                        for _ in range(qty):
                            packer_items.append(Item(name, l, w, h, weight))
            except: pass

        # 2. 設定 Packer 外箱
        packer = Packer()
        
        # 如果有內襯，我們要縮小箱子給 Packer 算
        if lining_config:
            # 剩餘可用空間
            eff_l = box_l - lining_config['offset_x']
            eff_h = box_h - lining_config['offset_z']
            
            # 安全檢查：空間是否足夠
            if eff_l <= 0 or eff_h <= 0:
                st.error("❌ 錯誤：L型內襯太厚，佔滿了整個箱子！")
                st.stop()
                
            box = Bin('StandardBox', eff_l, box_w, eff_h, 999999)
            offset_x = lining_config['offset_x']
            offset_z = lining_config['offset_z']
        else:
            # 沒有內襯，使用完整箱子
            box = Bin('StandardBox', box_l, box_w, box_h, 999999)
            offset_x = 0
            offset_z = 0
            
        packer.add_bin(box)

        # 3. 加入一般物品並運算
        for item in packer_items:
            packer.add_item(item)
            
        packer.pack(bigger_first=True) # 大的先裝

        # ==========================
        # 繪圖與報表整合
        # ==========================
        fig = go.Figure()
        
        # 畫外箱框線
        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
            z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
            mode='lines', line=dict(color='black', width=6), name='外箱'
        ))

        # 顏色管理
        unique_names = list(requested_counts.keys())
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF']
        colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_names)}

        # --- A. 繪製 L 型內襯 (如果有) ---
        if lining_config:
            name = lining_config['name']
            qty = lining_config['qty']
            unit_h = lining_config['h'] # 單個厚度
            l_real = lining_config['l']
            w_real = lining_config['w']
            vis_h = lining_config['visual_wall_h']
            c = colors.get(name, '#888')
            
            # 從 (0,0,0) 開始層層堆疊
            for i in range(qty):
                # 1. 底座 (Floor)
                # 位置 z 隨層數增加
                fz = i * unit_h
                # 長度：延伸到箱底，但最多就是原長
                fl_draw = min(l_real, box_l) 
                
                fig.add_trace(go.Mesh3d(
                    x=[0, fl_draw, fl_draw, 0, 0, fl_draw, fl_draw, 0],
                    y=[0, 0, w_real, w_real, 0, 0, w_real, w_real],
                    z=[fz, fz, fz, fz, fz+unit_h, fz+unit_h, fz+unit_h, fz+unit_h],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=c, opacity=1, name=name, showlegend=(i==0)
                ))
                # 底座黑框
                fig.add_trace(go.Scatter3d(
                    x=[0, fl_draw, fl_draw, 0, 0, 0, fl_draw, fl_draw, 0, 0, 0, 0, fl_draw, fl_draw, fl_draw, fl_draw],
                    y=[0, 0, w_real, w_real, 0, 0, 0, 0, w_real, w_real, 0, w_real, w_real, w_real, 0, 0],
                    z=[fz, fz, fz, fz, fz, fz+unit_h, fz+unit_h, fz+unit_h, fz+unit_h, fz+unit_h, fz, fz+unit_h, fz+unit_h, fz+unit_h, fz, fz],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))

                # 2. 側牆 (Wall)
                # 位置 x 隨層數增加 (厚度方向)
                wx = i * unit_h
                
                fig.add_trace(go.Mesh3d(
                    x=[wx, wx+unit_h, wx+unit_h, wx, wx, wx+unit_h, wx+unit_h, wx],
                    y=[0, 0, w_real, w_real, 0, 0, w_real, w_real],
                    z=[0, 0, 0, 0, vis_h, vis_h, vis_h, vis_h],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=c, opacity=1, showlegend=False
                ))
                # 側牆黑框
                fig.add_trace(go.Scatter3d(
                    x=[wx, wx+unit_h, wx+unit_h, wx, wx, wx, wx+unit_h, wx+unit_h, wx, wx, wx, wx, wx+unit_h, wx+unit_h, wx+unit_h, wx+unit_h],
                    y=[0, 0, w_real, w_real, 0, 0, 0, 0, w_real, w_real, 0, w_real, w_real, w_real, 0, 0],
                    z=[0, 0, 0, 0, 0, vis_h, vis_h, vis_h, vis_h, vis_h, 0, vis_h, vis_h, vis_h, 0, 0],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))

        # --- B. 繪製 Packer 算出來的物品 ---
        # 關鍵：統計最終裝箱數量 (Packer 算出的 + 手動 L 型)
        final_packed_counts = manual_packed_counts.copy() # 先把 L 型的數量加進去
        
        total_vol = 0
        total_net_weight = 0
        
        for b in packer.bins:
            for item in b.items:
                # 處理名稱 (移除括號後綴)
                raw_name = item.name
                base_name = raw_name.split('(')[0]
                
                # 累加 Packer 算出來的數量
                final_packed_counts[base_name] = final_packed_counts.get(base_name, 0) + 1
                
                # 取得 Packer 的相對座標
                px, py, pz = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                dw, dd, dh = float(dim[0]), float(dim[1]), float(dim[2])
                
                # === 座標校正 ===
                # 加上內襯的偏移量，讓禮盒「浮」在內襯上
                final_x = px + offset_x
                final_y = py 
                final_z = pz + offset_z
                
                total_vol += (dw * dd * dh)
                total_net_weight += float(item.weight)
                c = colors.get(base_name, '#888')

                # 繪製實體
                fig.add_trace(go.Mesh3d(
                    x=[final_x, final_x+dw, final_x+dw, final_x, final_x, final_x+dw, final_x+dw, final_x],
                    y=[final_y, final_y, final_y+dd, final_y+dd, final_y, final_y, final_y+dd, final_y+dd],
                    z=[final_z, final_z, final_z, final_z, final_z+dh, final_z+dh, final_z+dh, final_z+dh],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=c, opacity=1, name=base_name, showlegend=True, hoverinfo='text', text=f"{base_name}"
                ))
                # 繪製黑框
                fig.add_trace(go.Scatter3d(
                    x=[final_x, final_x+dw, final_x+dw, final_x, final_x, final_x, final_x+dw, final_x+dw, final_x, final_x, final_x, final_x, final_x+dw, final_x+dw, final_x+dw, final_x+dw],
                    y=[final_y, final_y, final_y+dd, final_y+dd, final_y, final_y, final_y, final_y, final_y+dd, final_y+dd, final_y, final_y+dd, final_y+dd, final_y+dd, final_y, final_y],
                    z=[final_z, final_z, final_z, final_z, final_z, final_z+dh, final_z+dh, final_z+dh, final_z+dh, final_z+dh, final_z, final_z+dh, final_z+dh, final_z+dh, final_z, final_z],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))

        # 去重圖例
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # Layout 設定
        axis_config = dict(backgroundcolor="white", showbackground=True, zerolinecolor="black", gridcolor="#999999", linecolor="black", showgrid=True, showline=True, tickfont=dict(color="black"), title=dict(font=dict(color="black")))
        fig.update_layout(
            template="plotly_white", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            scene=dict(xaxis={**axis_config, 'title':'長'}, yaxis={**axis_config, 'title':'寬'}, zaxis={**axis_config, 'title':'高'}, aspectmode='data', camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))),
            margin=dict(t=30, b=0, l=0, r=0), height=600, legend=dict(x=0, y=1, bgcolor="rgba(255,255,255,0.8)", borderwidth=1)
        )

        # 4. 產生最終報表
        # 計算利用率 (外箱體積 / 裝入物體積)
        box_vol = box_l * box_w * box_h
        # L型內襯的體積也要算進去 (概略估算)
        lining_vol = 0
        if lining_config:
            # 側牆體積 + 底座體積
            lining_vol += (lining_config['offset_x'] * lining_config['w'] * lining_config['visual_wall_h']) 
            lining_vol += ((box_l - lining_config['offset_x']) * lining_config['w'] * lining_config['offset_z'])
            total_net_weight += (0.05 * lining_config['qty']) # 加上紙袋重量

        final_utilization = ((total_vol + lining_vol) / box_vol) * 100 if box_vol > 0 else 0
        gross_weight = total_net_weight + box_weight
        now_str = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")

        # 檢查缺漏 (比對 requested_counts 與 final_packed_counts)
        all_fitted = True
        missing_html = ""
        for name, req in requested_counts.items():
            real = final_packed_counts.get(name, 0)
            diff = req - real
            if diff > 0:
                all_fitted = False
                missing_html += f"<li style='color:red; background:#ffd2d2; padding:5px;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status = "<h3 style='color:green; background:#d4edda; padding:10px; border-radius:5px;'>✅ 完美裝箱</h3>" if all_fitted else f"<h3 style='color:red; background:#f8d7da; padding:10px; border-radius:5px;'>❌ 部分遺漏</h3><ul>{missing_html}</ul>"

        report_html = f"""
        <div class="report-card">
            <h2>📋 訂單裝箱報告</h2>
            <p><b>訂單:</b> {order_name} | <b>外箱:</b> {box_l}x{box_w}x{box_h} cm | <b>利用率:</b> {final_utilization:.2f}%</p>
            {status}
        </div>
        """
        st.markdown(report_html, unsafe_allow_html=True)
        st.download_button("📥 下載報告", report_html, "report.html", "text/html", type="primary")
        st.plotly_chart(fig, use_container_width=True, theme=None, config={'displayModeBar': False})
