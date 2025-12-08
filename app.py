import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import datetime

# ==========================
# 頁面設定 (恢復側邊欄佈局)
# ==========================
st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="expanded")

# ==========================
# V34 CSS：經典側邊欄 + 手機圖表滿版優化
# ==========================
st.markdown("""
<style>
    /* 1. 全域設定 */
    .stApp {
        background-color: #ffffff !important;
        color: #000000 !important;
    }
    
    /* 2. 隱藏官方雜訊 */
    [data-testid="stDecoration"] { display: none !important; }
    .stDeployButton { display: none !important; }
    footer { display: none !important; }
    #MainMenu { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    
    /* 3. 處理 Header (讓點擊穿透) */
    [data-testid="stHeader"] {
        background-color: transparent !important;
        pointer-events: none !important;
    }
    
    /* === 4. 側邊欄開關按鈕 (強制顯示黑色按鈕) === */
    [data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarExpandedControl"] {
        display: block !important;
        visibility: visible !important;
        pointer-events: auto !important;
        
        /* 固定在左上角 */
        position: fixed !important;
        top: 15px !important;
        left: 15px !important;
        z-index: 1000000 !important;
        
        /* 樣式：黑色圓形 */
        background-color: #000000 !important;
        color: #ffffff !important;
        border-radius: 50% !important;
        width: 40px !important;
        height: 40px !important;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2) !important;
        
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    
    /* 按鈕圖示轉白 */
    [data-testid="stSidebarCollapsedControl"] svg, [data-testid="stSidebarExpandedControl"] svg {
        fill: #ffffff !important;
        stroke: #ffffff !important;
    }

    /* 5. 輸入框與表格樣式 */
    div[data-baseweb="input"] input,
    div[data-baseweb="select"] div,
    .stDataFrame, .stTable {
        color: #000000 !important;
        background-color: #ffffff !important;
    }

    /* 6. 報表卡片樣式 */
    .report-card {
        font-family: sans-serif; 
        padding: 15px; 
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
    
    /* 8. 針對手機調整頂部與左右邊距 */
    .block-container {
        padding-top: 3.5rem !important;
        /* 極大化手機寬度利用，減少留白 */
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統")
st.markdown("---")

# ==========================
# 側邊欄：設定區 (恢復)
# ==========================
with st.sidebar:
    st.header("📝 1. 訂單與外箱設定")
    
    order_name = st.text_input("訂單名稱", value="訂單_20241208")
    
    st.caption("外箱規格 (cm)")
    col1, col2, col3 = st.columns(3)
    box_l = col1.number_input("長", value=45.0, step=1.0)
    box_w = col2.number_input("寬", value=30.0, step=1.0)
    box_h = col3.number_input("高", value=30.0, step=1.0)
    
    box_weight = st.number_input("空箱重量 (kg)", value=0.5, step=0.1)
    
    st.markdown("---")
    
    st.header("🎁 2. 商品清單")
    # 預設數據
    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame(
            [
                {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 7},
                {"商品名稱": "禮盒(茶葉)", "長": 10.0, "寬": 10.0, "高": 15.0, "重量(kg)": 0.3, "數量": 2},
            ]
        )

    # 可編輯表格
    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "數量": st.column_config.NumberColumn(min_value=1, step=1, format="%d"),
            "長": st.column_config.NumberColumn(format="%.1f"),
            "寬": st.column_config.NumberColumn(format="%.1f"),
            "高": st.column_config.NumberColumn(format="%.1f"),
            "重量(kg)": st.column_config.NumberColumn(format="%.2f"),
        }
    )
    
    st.markdown("<br>", unsafe_allow_html=True)
    run_button = st.button("🔄 執行裝箱運算", type="primary", use_container_width=True)

# ==========================
# 主畫面：運算邏輯與結果
# ==========================
if run_button:
    with st.spinner('正在進行 3D 運算...'):
        # 準備數據
        max_weight_limit = 999999
        packer = Packer()
        box = Bin('StandardBox', box_l, box_w, box_h, max_weight_limit)
        packer.add_bin(box)
        
        requested_counts = {}
        unique_products = []
        total_qty = 0
        total_net_weight = 0
        
        # 讀取表格數據
        for index, row in edited_df.iterrows():
            try:
                name = str(row["商品名稱"])
                l = float(row["長"])
                w = float(row["寬"])
                h = float(row["高"])
                weight = float(row["重量(kg)"])
                qty = int(row["數量"])
                
                if qty > 0:
                    total_qty += qty
                    if name not in requested_counts:
                        requested_counts[name] = 0
                        unique_products.append(name)
                    requested_counts[name] += qty
                    
                    for _ in range(qty):
                        item = Item(name, l, w, h, weight)
                        packer.add_item(item)
            except:
                pass

        # 顏色分配
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        # 裝箱 (優先大物件)
        packer.pack(bigger_first=True)
        
        # 準備繪圖
        fig = go.Figure()
        
        # 座標軸設定 (黑字)
        axis_config = dict(
            backgroundcolor="white", showbackground=True, zerolinecolor="#000000", 
            gridcolor="#888888", linecolor="#000000", tickfont=dict(color="#000000", size=11) 
        )
        
        # === V34 關鍵修改：針對手機的 3D 圖表滿版優化 ===
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            autosize=True, # 確保圖表自動適應容器
            scene=dict(
                xaxis={**axis_config, 'title': 'L'},
                yaxis={**axis_config, 'title': 'W'},
                zaxis={**axis_config, 'title': 'H'},
                aspectmode='data'
            ),
            # ★★★ 關鍵：將左右邊距 (l, r) 設為 0 ★★★
            # 這樣圖表就會直接貼齊手機螢幕邊緣，不會被留白擠壓
            margin=dict(t=10, b=10, l=0, r=0), 
            height=500 
        )

        # 畫外箱 (黑線)
        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
            z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
            mode='lines', line=dict(color='#000000', width=4), name='外箱'
        ))

        total_vol = 0
        packed_counts = {}
        
        for b in packer.bins:
            for item in b.items:
                packed_counts[item.name] = packed_counts.get(item.name, 0) + 1
                x, y, z = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                idim_w, idim_d, idim_h = float(dim[0]), float(dim[1]), float(dim[2])
                i_weight = float(item.weight)
                total_vol += (idim_w * idim_d * idim_h)
                total_net_weight += i_weight
                
                color = product_colors.get(item.name, '#888')
                hover_text = f"{item.name}<br>{idim_w}x{idim_d}x{idim_h}<br>{i_weight:.2f}kg"
                
                fig.add_trace(go.Mesh3d(
                    x=[x, x+idim_w, x+idim_w, x, x, x+idim_w, x+idim_w, x],
                    y=[y, y, y+idim_d, y+idim_d, y, y, y+idim_d, y+idim_d],
                    z=[z, z, z, z, z+idim_h, z+idim_h, z+idim_h, z+idim_h],
                    i = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
                    j = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
                    k = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=color, opacity=1, name=item.name, showlegend=True,
                    text=hover_text, hoverinfo='text'
                ))
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
                missing_items_html += f"<li style='color: #D8000C; background-color: #FFD2D2; padding: 5px; margin: 3px 0; border-radius: 4px;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status_html = "<div style='color: #155724; background-color: #d4edda; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold;'>✅ 完美！所有商品皆已裝入。</div>" if all_fitted else f"<div style='color: #721c24; background-color: #f8d7da; padding: 10px; border-radius: 5px; font-weight: bold;'>❌ 注意：有部分商品裝不下！</div><ul style='padding-left: 20px; font-size: 0.9em;'>{missing_items_html}</ul>"

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

        # 顯示區域
        st.header("📊 3. 裝箱結果")
        st.markdown(report_html, unsafe_allow_html=True)
        
        # 下載按鈕
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

        # 顯示 3D 圖 (填滿容器)
        st.plotly_chart(fig, use_container_width=True)
