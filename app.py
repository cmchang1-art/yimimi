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
# CSS 樣式優化
# ==========================
st.markdown("""
<style>
    .stApp { background-color: #ffffff !important; color: #000000 !important; }
    [data-testid="stSidebar"], [data-testid="stDecoration"], .stDeployButton, footer, #MainMenu, [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stHeader"] { background-color: transparent !important; pointer-events: none; }
    
    div[data-baseweb="input"] input, div[data-baseweb="select"] div, .stDataFrame, .stTable {
        color: #000000 !important; background-color: #f9f9f9 !important; border-color: #cccccc !important;
    }
    
    .section-header {
        font-size: 1.2rem; font-weight: bold; color: #333; margin-top: 10px; margin-bottom: 5px;
        border-left: 5px solid #FF4B4B; padding-left: 10px;
    }

    .report-card {
        padding: 20px; border: 2px solid #e0e0e0; border-radius: 10px; 
        background: #ffffff; color: #333333; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 20px;
    }
    
    .block-container { padding-top: 2rem !important; }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統 (內襯縮減終極版)")
st.markdown("---")

# ==========================
# 輸入區域
# ==========================
col_left, col_right = st.columns([1, 2], gap="large")

with col_left:
    st.markdown('<div class="section-header">1. 訂單與外箱設定</div>', unsafe_allow_html=True)
    with st.container():
        order_name = st.text_input("訂單名稱", value="訂單_20241208")
        st.caption("外箱尺寸 (cm)")
        c1, c2, c3 = st.columns(3)
        box_l = c1.number_input("長", value=30.0, step=1.0)
        box_w = c2.number_input("寬", value=25.0, step=1.0)
        box_h = c3.number_input("高", value=15.0, step=1.0)
        box_weight = st.number_input("空箱重量 (kg)", value=0.5, step=0.1)

with col_right:
    st.markdown('<div class="section-header">2. 商品清單</div>', unsafe_allow_html=True)
    
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
# 核心運算邏輯
# ==========================
if run_button:
    with st.spinner('正在進行內襯演算與空間模擬...'):
        
        # 1. 初始化變數
        requested_counts = {}
        unique_products = []
        total_net_weight = 0
        normal_items_to_pack = []
        
        # L型內襯參數 (Wall = 牆壁, Floor = 底座)
        lining_offset_x = 0.0 # 牆壁佔用的厚度
        lining_offset_z = 0.0 # 底座佔用的高度
        lining_items = [] # 儲存L型商品資訊以便繪圖
        
        # 2. 資料前處理：分離「L型內襯」與「一般商品」
        for index, row in edited_df.iterrows():
            try:
                name = str(row["商品名稱"])
                l, w, h = float(row["長"]), float(row["寬"]), float(row["高"])
                weight = float(row["重量(kg)"])
                qty = int(row["數量"])
                mode = str(row["變形模式"])
                
                if qty > 0:
                    if name not in requested_counts:
                        requested_counts[name] = 0
                        unique_products.append(name)
                    requested_counts[name] += qty
                    total_net_weight += weight * qty

                    if mode == "L型彎折 (作為內襯墊底)":
                        # === 關鍵邏輯：不放入 Packer，而是直接計算佔用空間 ===
                        # 牆壁厚度：這裡假設將紙袋原本的「高」作為厚度 (0.3cm * qty)
                        # 底座高度：同上 (0.3cm * qty)
                        current_wall_thick = h * qty
                        current_floor_height = h * qty
                        
                        # 累加佔用空間 (如果有多種L型，會越疊越厚)
                        lining_offset_x += current_wall_thick
                        lining_offset_z += current_floor_height
                        
                        # 記錄下來給繪圖用
                        lining_items.append({
                            'name': name,
                            'l': l, 'w': w, 'h': h,
                            'qty': qty,
                            'wall_thick_total': current_wall_thick,
                            'floor_height_total': current_floor_height,
                            # 視覺高度：牆壁豎起來的高度 (模擬值，例如設為長度的30%)
                            'visual_wall_h': l * 0.3 
                        })
                        
                    elif "對折" in mode:
                        for _ in range(qty):
                            normal_items_to_pack.append(Item(f"{name}(Folded)", l/2, w, h*2, weight))
                    else:
                        for _ in range(qty):
                            normal_items_to_pack.append(Item(name, l, w, h, weight))
            except: pass

        # 3. 建立「縮小版」的外箱
        # 我們告訴演算法：箱子變小了！請把禮盒裝進剩下的空間
        # 實際可用長度 = 原長度 - 牆壁總厚度
        # 實際可用高度 = 原高度 - 底座總高度
        effective_l = box_l - lining_offset_x
        effective_h = box_h - lining_offset_z
        
        packer = Packer()
        # 注意：如果內襯太厚導致空間 < 0，要保護一下
        if effective_l <= 0 or effective_h <= 0:
            st.error("❌ 錯誤：紙袋/內襯數量太多，已塞滿整個箱子，無法放入其他物品！")
            st.stop()
            
        box = Bin('StandardBox', effective_l, box_w, effective_h, 999999)
        packer.add_bin(box)

        # 4. 裝入一般商品 (禮盒)
        for item in normal_items_to_pack:
            packer.add_item(item)

        packer.pack(bigger_first=True) 
        
        # ==========================
        # 視覺化與報表
        # ==========================
        fig = go.Figure()
        
        # 座標軸設定
        axis_config = dict(backgroundcolor="white", showbackground=True, zerolinecolor="black", gridcolor="#999999", linecolor="black", showgrid=True, showline=True, tickfont=dict(color="black"), title=dict(font=dict(color="black")))
        fig.update_layout(
            template="plotly_white", font=dict(color="black"), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            scene=dict(xaxis={**axis_config, 'title':'長(L)'}, yaxis={**axis_config, 'title':'寬(W)'}, zaxis={**axis_config, 'title':'高(H)'}, aspectmode='data', camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))),
            margin=dict(t=30, b=0, l=0, r=0), height=600, legend=dict(x=0, y=1, bgcolor="rgba(255,255,255,0.8)", borderwidth=1)
        )

        # 畫真實外箱 (黑色框線)
        fig.add_trace(go.Scatter3d(x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l], y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w], z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0], mode='lines', line=dict(color='black', width=6), name='外箱'))

        # 顏色
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        # === 步驟 A: 手動繪製 L 型內襯 (固定在角落) ===
        # 這裡我們不依賴 Packer，直接畫出來
        
        # 為了美觀，如果有多種L型，我們可以疊加，但這裡簡化為統一畫在原點
        current_x = 0
        current_z = 0
        
        packed_counts_merged = {} 

        for l_item in lining_items:
            name = l_item['name']
            qty = l_item['qty']
            h_unit = l_item['h'] # 單個厚度
            w_real = l_item['w']
            l_real = l_item['l']
            
            color = product_colors.get(name, '#888')
            packed_counts_merged[name] = qty # 這些肯定裝進去了

            # 繪製每一層 (讓視覺上有堆疊感)
            for i in range(qty):
                # 1. 繪製底座 (Floor)
                # 位置：Z軸從 0 開始堆疊
                floor_z = current_z + (i * h_unit)
                # 長度：要延伸到箱子邊緣，或者保持原長 (這裡我們讓它貼滿底部長度，符合內襯概念)
                floor_len_draw = box_l - current_x # 簡單處理：鋪滿剩餘長度
                if floor_len_draw > l_real: floor_len_draw = l_real # 但不能超過原長
                
                # Floor Mesh
                fig.add_trace(go.Mesh3d(
                    x=[0, floor_len_draw, floor_len_draw, 0, 0, floor_len_draw, floor_len_draw, 0],
                    y=[0, 0, w_real, w_real, 0, 0, w_real, w_real],
                    z=[floor_z, floor_z, floor_z, floor_z, floor_z+h_unit, floor_z+h_unit, floor_z+h_unit, floor_z+h_unit],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=color, opacity=1, name=name, showlegend=(i==0 and current_x==0), hoverinfo='text', text=f"{name}(內襯)"
                ))
                # Floor Wireframe (黑線)
                fig.add_trace(go.Scatter3d(
                    x=[0, floor_len_draw, floor_len_draw, 0, 0, 0, floor_len_draw, floor_len_draw, 0, 0, 0, 0, floor_len_draw, floor_len_draw, floor_len_draw, floor_len_draw],
                    y=[0, 0, w_real, w_real, 0, 0, 0, 0, w_real, w_real, 0, w_real, w_real, w_real, 0, 0],
                    z=[floor_z, floor_z, floor_z, floor_z, floor_z, floor_z+h_unit, floor_z+h_unit, floor_z+h_unit, floor_z+h_unit, floor_z+h_unit, floor_z, floor_z+h_unit, floor_z+h_unit, floor_z+h_unit, floor_z, floor_z],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))

                # 2. 繪製牆壁 (Wall)
                # 位置：X軸從 0 開始堆疊 (厚度方向)
                wall_x = current_x + (i * h_unit)
                wall_h_draw = l_item['visual_wall_h'] # 視覺高度
                
                # Wall Mesh
                fig.add_trace(go.Mesh3d(
                    x=[wall_x, wall_x+h_unit, wall_x+h_unit, wall_x, wall_x, wall_x+h_unit, wall_x+h_unit, wall_x],
                    y=[0, 0, w_real, w_real, 0, 0, w_real, w_real],
                    z=[0, 0, 0, 0, wall_h_draw, wall_h_draw, wall_h_draw, wall_h_draw],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=color, opacity=1, showlegend=False
                ))
                # Wall Wireframe
                fig.add_trace(go.Scatter3d(
                    x=[wall_x, wall_x+h_unit, wall_x+h_unit, wall_x, wall_x, wall_x, wall_x+h_unit, wall_x+h_unit, wall_x, wall_x, wall_x, wall_x, wall_x+h_unit, wall_x+h_unit, wall_x+h_unit, wall_x+h_unit],
                    y=[0, 0, w_real, w_real, 0, 0, 0, 0, w_real, w_real, 0, w_real, w_real, w_real, 0, 0],
                    z=[0, 0, 0, 0, 0, wall_h_draw, wall_h_draw, wall_h_draw, wall_h_draw, wall_h_draw, 0, wall_h_draw, wall_h_draw, wall_h_draw, 0, 0],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))

            # 更新偏移量 (雖然這裡只畫一次，但邏輯上是這樣)
            current_x += l_item['wall_thick_total']
            current_z += l_item['floor_height_total']


        # === 步驟 B: 繪製 Packer 算出來的禮盒 ===
        total_vol = 0 # 這裡僅計算禮盒體積，L型體積稍複雜先略
        
        for b in packer.bins:
            for item in b.items:
                raw_name = item.name
                base_name = raw_name.split('(')[0]
                packed_counts_merged[base_name] = packed_counts_merged.get(base_name, 0) + 1

                # 原始座標 (相對於縮小後的箱子)
                x_raw, y_raw, z_raw = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                w, d, h = float(dim[0]), float(dim[1]), float(dim[2])
                
                # === 關鍵修正：座標偏移 ===
                # 我們把禮盒的座標，加上 L 型內襯的厚度
                # 這樣禮盒就會乖乖地「浮」在內襯上面，絕對不會穿模
                x_final = x_raw + lining_offset_x
                y_final = y_raw # 寬度方向通常沒變，除非也有側面內襯
                z_final = z_raw + lining_offset_z
                
                total_vol += (w * d * h)
                color = product_colors.get(base_name, '#888')

                # 繪圖
                fig.add_trace(go.Mesh3d(
                    x=[x_final, x_final+w, x_final+w, x_final, x_final, x_final+w, x_final+w, x_final], 
                    y=[y_final, y_final, y_final+d, y_final+d, y_final, y_final, y_final+d, y_final+d], 
                    z=[z_final, z_final, z_final, z_final, z_final+h, z_final+h, z_final+h, z_final+h],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=color, opacity=1, name=base_name, showlegend=True, hoverinfo='text', 
                    text=f"{base_name}<br>Pos:({x_final},{y_final},{z_final})"
                ))
                fig.add_trace(go.Scatter3d(
                    x=[x_final, x_final+w, x_final+w, x_final, x_final, x_final, x_final+w, x_final+w, x_final, x_final, x_final, x_final, x_final+w, x_final+w, x_final+w, x_final+w],
                    y=[y_final, y_final, y_final+d, y_final+d, y_final, y_final, y_final, y_final, y_final+d, y_final+d, y_final, y_final+d, y_final+d, y_final, y_final, y_final+d],
                    z=[z_final, z_final, z_final, z_final, z_final, z_final+h, z_final+h, z_final+h, z_final+h, z_final+h, z_final, z_final+h, z_final+h, z_final+h, z_final, z_final],
                    mode='lines', line=dict(color='black', width=3), showlegend=False
                ))

        # 去除圖例重複
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # 報表生成
        box_vol = box_l * box_w * box_h
        utilization = (total_vol / box_vol) * 100 if box_vol > 0 else 0
        gross_weight = total_net_weight + box_weight
        now_str = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
        
        all_fitted, missing_html = True, ""
        for name, req in requested_counts.items():
            real = packed_counts_merged.get(name, 0)
            diff = req - real
            if diff > 0:
                all_fitted = False
                missing_html += f"<li style='color:red; background:#ffd2d2; padding:5px;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status = "<h3 style='color:green; bg:#d4edda;'>✅ 完美裝箱</h3>" if all_fitted else f"<h3 style='color:red; bg:#f8d7da;'>❌ 部分遺漏</h3><ul>{missing_html}</ul>"
        
        report_html = f"""
        <div class="report-card">
            <h2>📋 訂單裝箱報告</h2>
            <p><b>訂單:</b> {order_name} | <b>外箱:</b> {box_l}x{box_w}x{box_h} cm | <b>利用率:</b> {utilization:.2f}%</p>
            {status}
        </div>
        """
        st.markdown(report_html, unsafe_allow_html=True)
        st.download_button("📥 下載報告", report_html, "report.html", "text/html", type="primary")
        st.plotly_chart(fig, use_container_width=True, theme=None, config={'displayModeBar': False})
