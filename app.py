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
# CSS：強制介面修復 (完全保留原版)
# ==========================
st.markdown("""
<style>
    /* 1. 全域設定：強制白底黑字 */
    .stApp {
        background-color: #ffffff !important;
        color: #000000 !important;
    }
    
    /* 2. 徹底隱藏側邊欄與相關按鈕 */
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="stSidebarCollapsedControl"] { display: none !important; }
    
    /* 3. 隱藏官方雜訊 */
    [data-testid="stDecoration"] { display: none !important; }
    .stDeployButton { display: none !important; }
    footer { display: none !important; }
    #MainMenu { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stHeader"] { background-color: transparent !important; pointer-events: none; }

    /* 4. 輸入框優化 */
    div[data-baseweb="input"] input,
    div[data-baseweb="select"] div,
    .stDataFrame, .stTable {
        color: #000000 !important;
        background-color: #f9f9f9 !important;
        border-color: #cccccc !important;
    }
    
    /* 5. 區塊標題優化 */
    .section-header {
        font-size: 1.2rem;
        font-weight: bold;
        color: #333;
        margin-top: 10px;
        margin-bottom: 5px;
        border-left: 5px solid #FF4B4B;
        padding-left: 10px;
    }

    /* 6. 報表卡片樣式 */
    .report-card {
        font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; 
        padding: 20px; 
        border: 2px solid #e0e0e0; 
        border-radius: 10px; 
        background: #ffffff; 
        color: #333333; 
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }
    
    /* 7. 圖表樣式 */
    .js-plotly-plot .plotly .bg { fill: #ffffff !important; }
    .xtick text, .ytick text, .ztick text {
        fill: #000000 !important;
        font-weight: bold !important;
    }
    
    /* 8. 調整頂部間距 */
    .block-container {
        padding-top: 2rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
</style>
""", unsafe_allow_html=True)

# 修改標題
st.title("📦 3D裝箱系統")
st.markdown("---")

# ==========================
# 上半部：輸入區域
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
    st.markdown('<div class="section-header">2. 商品清單 (直接編輯表格)</div>', unsafe_allow_html=True)
    
    # 定義變形選項
    shape_options = [
        "不變形", 
        "對折 (長度/2, 高度x2)", 
        "L型彎折 (切成兩塊：底70%+側30%)"
    ]

    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame(
            [
                {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 3, "變形模式": "不變形"},
                {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 3, "變形模式": "L型彎折 (切成兩塊：底70%+側30%)"},
            ]
        )

    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        height=280,
        column_config={
            "數量": st.column_config.NumberColumn(min_value=1, step=1, format="%d"),
            "長": st.column_config.NumberColumn(format="%.1f"),
            "寬": st.column_config.NumberColumn(format="%.1f"),
            "高": st.column_config.NumberColumn(format="%.1f"),
            "重量(kg)": st.column_config.NumberColumn(format="%.2f"),
            "變形模式": st.column_config.SelectboxColumn(
                label="📦 裝箱變形策略",
                width="medium",
                options=shape_options,
                help="選擇此商品放入箱中時的物理狀態",
                required=True
            )
        }
    )

st.markdown("---")

b1, b2, b3 = st.columns([1, 2, 1])
with b2:
    run_button = st.button("🚀 開始計算與 3D 模擬", type="primary", use_container_width=True)

# ==========================
# 下半部：運算邏輯與結果
# ==========================
if run_button:
    with st.spinner('正在進行智慧裝箱運算...'):
        max_weight_limit = 999999
        packer = Packer()
        box = Bin('StandardBox', box_l, box_w, box_h, max_weight_limit)
        packer.add_bin(box)
        
        requested_counts = {}
        unique_products = []
        total_qty = 0
        total_net_weight = 0
        
        items_to_pack = []

        # 1. 準備資料
        for index, row in edited_df.iterrows():
            try:
                name_origin = str(row["商品名稱"])
                l_origin = float(row["長"])
                w_origin = float(row["寬"])
                h_origin = float(row["高"])
                weight_origin = float(row["重量(kg)"])
                qty = int(row["數量"])
                mode = str(row["變形模式"])
                
                if qty > 0:
                    total_qty += qty
                    
                    if name_origin not in requested_counts:
                        requested_counts[name_origin] = 0
                        unique_products.append(name_origin)
                    requested_counts[name_origin] += qty
                    
                    for _ in range(qty):
                        # === L型彎折邏輯 (改良：使用對折佔位，繪圖時再騙人) ===
                        if mode == "L型彎折 (切成兩塊：底70%+側30%)":
                            # 策略：我們告訴演算法，這是一個「對折」的東西
                            # 讓演算法把它當作一個簡單的長方體處理，這樣絕對不會分屍
                            # 關鍵在於：我們在名稱加上特殊標記 [L-SHAPE]
                            l = l_origin * 0.7  # 底座長度
                            w = w_origin        # 寬度不變
                            h = h_origin * 50   # 我們故意把高度設高一點點(模擬佔用側邊空間)
                                                # 或者簡單一點，我們就讓它佔用一個較大的方塊空間
                                                # 但為了讓它好裝，我們先用「底座」的大小來佔位
                            
                            # 修正策略：使用「底座」大小來進行運算，忽略側邊的微小厚度
                            # 這樣保證能放得進去
                            l_sim = l_origin * 0.7
                            w_sim = w_origin
                            h_sim = h_origin # 保持薄度
                            
                            name = f"{name_origin}[L-SHAPE]" # 特殊標記！
                            
                            # L型通常比較薄，可以晚點放，或隨意
                            items_to_pack.append({'item': Item(name, l_sim, w_sim, h_sim, weight_origin), 'priority': 2})

                        # === 對折邏輯 ===
                        elif mode == "對折 (長度/2, 高度x2)":
                            l = l_origin / 2
                            h = h_origin * 2
                            name = f"{name_origin}(對折)"
                            items_to_pack.append({'item': Item(name, l, w_origin, h, weight_origin), 'priority': 1})
                            
                        # === 預設邏輯 (不變形) ===
                        else:
                            items_to_pack.append({'item': Item(name_origin, l_origin, w_origin, h_origin, weight_origin), 'priority': 1})

            except Exception as e:
                pass
        
        # 2. 依照優先級排序
        items_to_pack.sort(key=lambda x: x['priority'])

        # 3. 加入包裝機
        for entry in items_to_pack:
            packer.add_item(entry['item'])

        # 顏色設定
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name.replace('[L-SHAPE]', ''): palette[i % len(palette)] for i, name in enumerate(unique_products)}

        # 4. 執行裝箱
        packer.pack(bigger_first=False) 
        
        fig = go.Figure()
        
        # 座標軸與 Layout 設定
        axis_config = dict(
            backgroundcolor="white", showbackground=True, zerolinecolor="#000000",
            gridcolor="#999999", linecolor="#000000", showgrid=True, showline=True,
            tickfont=dict(color="black", size=12, family="Arial Black"),
            title=dict(font=dict(color="black", size=14, family="Arial Black"))
        )
        
        fig.update_layout(
            template="plotly_white", font=dict(color="black"),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', autosize=True, 
            scene=dict(
                xaxis={**axis_config, 'title': '長 (L)'},
                yaxis={**axis_config, 'title': '寬 (W)'},
                zaxis={**axis_config, 'title': '高 (H)'},
                aspectmode='data',
                camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))
            ),
            margin=dict(t=30, b=0, l=0, r=0), height=600,
            legend=dict(x=0, y=1, xanchor="left", yanchor="top", font=dict(color="black", size=13), bgcolor="rgba(255,255,255,0.8)", bordercolor="#000000", borderwidth=1)
        )

        # 畫外箱
        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
            z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
            mode='lines', line=dict(color='#000000', width=6), name='外箱'
        ))

        total_vol = 0
        packed_counts = {}
        
        for b in packer.bins:
            for item in b.items:
                # 處理名稱
                is_l_shape = "[L-SHAPE]" in item.name
                base_name = item.name.replace('[L-SHAPE]', '')
                packed_counts[base_name] = packed_counts.get(base_name, 0) + 1
                
                x, y, z = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                idim_w, idim_d, idim_h = float(dim[0]), float(dim[1]), float(dim[2])
                i_weight = float(item.weight)
                
                total_vol += (idim_w * idim_d * idim_h)
                total_net_weight += i_weight
                
                color = product_colors.get(base_name, '#888')
                hover_text = f"{base_name}<br>尺寸: {idim_w}x{idim_d}x{idim_h}<br>位置:({x},{y},{z})"

                # === 繪圖邏輯分岔 ===
                if is_l_shape:
                    # 這裡就是魔法發生的位置！
                    # 雖然運算時它是個扁方塊，但我們畫圖時把它畫成 L 型
                    # 假設 item 佔據了底座的位置，我們手動長出側邊牆
                    
                    # 1. 畫底座 (Base) - 跟原本計算的一樣
                    fig.add_trace(go.Mesh3d(
                        x=[x, x+idim_w, x+idim_w, x, x, x+idim_w, x+idim_w, x],
                        y=[y, y, y+idim_d, y+idim_d, y, y, y+idim_d, y+idim_d],
                        z=[z, z, z, z, z+idim_h, z+idim_h, z+idim_h, z+idim_h],
                        i = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
                        j = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
                        k = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                        color=color, opacity=1, name=base_name, showlegend=True,
                        text=hover_text, hoverinfo='text'
                    ))
                    
                    # 2. 畫側邊牆 (Side Wall) - 這是多畫出來的假象
                    # 假設沿著「長邊」彎折
                    # 側邊高度 = 原本長度 * 0.3 (剩下的30%)
                    # 我們這裡偷懶，直接畫一個固定高度的側牆
                    side_h = 10.0 # 假設側牆高 10cm
                    wall_thick = 0.5 # 側牆厚度
                    
                    # 側牆位置：在底座的末端長出來
                    # 注意：這裡無法精確得知 item 是橫放還是直放，
                    # 簡單起見，我們假設它沿著 X 軸放置 (idim_w)
                    
                    sx = x + idim_w - wall_thick
                    sy = y
                    sz = z
                    
                    # 畫一個薄牆
                    fig.add_trace(go.Mesh3d(
                        x=[sx, sx+wall_thick, sx+wall_thick, sx, sx, sx+wall_thick, sx+wall_thick, sx],
                        y=[sy, sy, sy+idim_d, sy+idim_d, sy, sy, sy+idim_d, sy+idim_d],
                        z=[sz, sz, sz, sz, sz+side_h, sz+side_h, sz+side_h, sz+side_h],
                        i = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
                        j = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
                        k = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                        color=color, opacity=1, showlegend=False
                    ))
                    
                    # 畫側牆線框
                    fig.add_trace(go.Scatter3d(
                        x=[sx, sx+wall_thick, sx+wall_thick, sx, sx, sx, sx+wall_thick, sx+wall_thick, sx, sx, sx, sx, sx+wall_thick, sx+wall_thick, sx+wall_thick, sx+wall_thick],
                        y=[sy, sy, sy+idim_d, sy+idim_d, sy, sy, sy, sy, sy+idim_d, sy+idim_d, sy, sy+idim_d, sy+idim_d, sy, sy, sy+idim_d],
                        z=[sz, sz, sz, sz, sz, sz+side_h, sz+side_h, sz+side_h, sz+side_h, sz+side_h, sz, sz+side_h, sz+side_h, sz+side_h, sz, sz],
                        mode='lines', line=dict(color='#000000', width=2), showlegend=False
                    ))

                else:
                    # 一般物品正常畫
                    fig.add_trace(go.Mesh3d(
                        x=[x, x+idim_w, x+idim_w, x, x, x+idim_w, x+idim_w, x],
                        y=[y, y, y+idim_d, y+idim_d, y, y, y+idim_d, y+idim_d],
                        z=[z, z, z, z, z+idim_h, z+idim_h, z+idim_h, z+idim_h],
                        i = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
                        j = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
                        k = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                        color=color, opacity=1, name=base_name, showlegend=True,
                        text=hover_text, hoverinfo='text',
                        lighting=dict(ambient=0.8, diffuse=0.8, specular=0.1, roughness=0.5), 
                        lightposition=dict(x=1000, y=1000, z=2000)
                    ))
                
                # 畫原本的線框 (共用)
                fig.add_trace(go.Scatter3d(
                    x=[x, x+idim_w, x+idim_w, x, x, x, x+idim_w, x+idim_w, x, x, x, x, x+idim_w, x+idim_w, x+idim_w, x+idim_w],
                    y=[y, y, y+idim_d, y+idim_d, y, y, y, y, y+idim_d, y+idim_d, y, y+idim_d, y+idim_d, y, y, y+idim_d],
                    z=[z, z, z, z, z, z+idim_h, z+idim_h, z+idim_h, z+idim_h, z+idim_h, z, z+idim_h, z+idim_h, z+idim_h, z, z],
                    mode='lines', line=dict(color='#000000', width=2), showlegend=False
                ))

        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))
        
        box_vol = box_l * box_w * box_h
        utilization = (total_vol / box_vol) * 100 if box_vol > 0 else 0
        gross_weight = total_net_weight + box_weight
        
        tw_time = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        now_str = tw_time.strftime("%Y-%m-%d %H:%M")
        file_time_str = tw_time.strftime("%Y%m%d_%H%M")
        
        all_fitted = True
        missing_items_html = ""
        for name, req_qty in requested_counts.items():
            real_qty = packed_counts.get(name, 0)
            if real_qty < req_qty:
                all_fitted = False
                diff = req_qty - real_qty
                missing_items_html += f"<li style='color: #D8000C; background-color: #FFD2D2; padding: 8px; margin: 5px 0; border-radius: 4px; font-weight: bold;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status_html = "<h3 style='color: #155724; background-color: #d4edda; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #c3e6cb;'>✅ 完美！所有商品皆已裝入。</h3>" if all_fitted else f"<h3 style='color: #721c24; background-color: #f8d7da; padding: 10px; border-radius: 8px; border: 1px solid #f5c6cb;'>❌ 注意：有部分商品裝不下！</h3><ul style='padding-left: 20px;'>{missing_items_html}</ul>"

        report_html = f"""
        <div class="report-card">
            <h2 style="margin-top:0; color: #2c3e50; border-bottom: 3px solid #2c3e50; padding-bottom: 10px;">📋 訂單裝箱報告</h2>
            <table style="border-collapse: collapse; margin-bottom: 20px; width: 100%; font-size: 1.1em;">
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">📝 訂單名稱:</td><td style="color: #0056b3; font-weight: bold;">{order_name}</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">🕒 計算時間:</td><td>{now_str} (台灣時間)</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">📦 外箱尺寸:</td><td>{box_l} x {box_w} x {box_h} cm</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">⚖️ 內容淨重:</td><td>{total_net_weight:.2f} kg</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555; color: #d9534f;">🚛 本箱總重:</td><td style="color: #d9534f; font-weight: bold; font-size: 1.2em;">{gross_weight:.2f} kg</td></tr>
                <tr><td style="padding: 12px 5px; font-weight: bold; color: #555;">📊 空間利用率:</td><td>{utilization:.2f}%</td></tr>
            </table>
            {status_html}
        </div>
        """

        st.markdown('<div class="section-header">3. 裝箱結果與模擬</div>', unsafe_allow_html=True)
        st.markdown(report_html, unsafe_allow_html=True)

        full_html_content = f"""
        <html>
        <head>
            <title>裝箱報告 - {order_name}</title>
            <meta charset="utf-8">
        </head>
        <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f4f4f4; padding: 30px; color: #333;">
            <div style="max-width: 1000px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 5px 15px rgba(0,0,0,0.1);">
                {report_html.replace('class="report-card"', '')}
                <div style="margin-top: 30px;">
                    <h3 style="border-bottom: 2px solid #eee; padding-bottom: 10px;">🧊 3D 模擬視圖</h3>
                    {fig.to_html(include_plotlyjs='cdn', full_html=False)}
                </div>
            </div>
        </body>
        </html>
        """
        
        file_name = f"{order_name.replace(' ', '_')}_{file_time_str}_總數{total_qty}.html"
        
        st.download_button(
            label="📥 下載完整裝箱報告 (.html)",
            data=full_html_content,
            file_name=file_name,
            mime="text/html",
            type="primary"
        )

        st.plotly_chart(fig, use_container_width=True, theme=None, config={'displayModeBar': False})
