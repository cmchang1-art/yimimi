import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import datetime

# ==========================
# 頁面設定
# ==========================
st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="expanded")

# ==========================
# V30 CSS：還原經典介面 + 手機圖表優化
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
    
    /* 3. Header 透明化 (保留點擊穿透) */
    [data-testid="stHeader"] {
        background-color: transparent !important;
        pointer-events: none !important;
    }
    
    /* 4. 側邊欄開關按鈕 (強制顯示，確保手機版能開合) */
    [data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarExpandedControl"] {
        display: block !important;
        visibility: visible !important;
        pointer-events: auto !important;
        position: fixed !important;
        top: 15px !important;
        left: 15px !important;
        z-index: 1000000 !important;
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
    
    [data-testid="stSidebarCollapsedControl"] svg, [data-testid="stSidebarExpandedControl"] svg {
        fill: #ffffff !important;
        stroke: #ffffff !important;
    }

    /* 5. 輸入框與表格優化 */
    div[data-baseweb="input"] input,
    div[data-baseweb="select"] div,
    .stDataFrame, .stTable {
        color: #000000 !important;
        background-color: #ffffff !important;
    }

    /* 6. 報表卡片 */
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
    
    /* 7. 內容間距調整 */
    .block-container {
        padding-top: 3.5rem !important;
        /* 手機版左右間距縮小，讓圖表變大 */
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    
    /* 8. 圖表坐標軸文字加黑 */
    .xtick text, .ytick text, .ztick text {
        fill: #000000 !important;
        font-weight: bold !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統")
st.markdown("---")

# ==========================
# 側邊欄：恢復設定功能
# ==========================
with st.sidebar:
    st.header("📝 1. 訂單與外箱設定")
    
    order_name = st.text_input("訂單名稱", value="訂單_20241208")
    
    st.subheader("外箱規格")
    col1, col2, col3 = st.columns(3)
    box_l = col1.number_input("長 (cm)", value=45.0, step=1.0)
    box_w = col2.number_input("寬 (cm)", value=30.0, step=1.0)
    box_h = col3.number_input("高 (cm)", value=30.0, step=1.0)
    
    box_weight = st.number_input("空箱重量 (kg)", value=0.5, step=0.1)
    
    st.markdown("---")
    st.info("💡 點擊左上角黑色按鈕可收合/展開此選單。")
    run_button = st.button("🔄 執行裝箱運算 (空間優化)", type="primary")

# ==========================
# 主畫面：商品清單
# ==========================
st.header("🎁 2. 商品清單")

# 預設數據
if 'df' not in st.session_state:
    st.session_state.df = pd.DataFrame(
        [
            {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 7},
            {"商品名稱": "禮盒(茶葉)", "長": 10.0, "寬": 10.0, "高": 15.0, "重量(kg)": 0.3, "數量": 2},
        ]
    )

# 可編輯表格 (高度適中)
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

# ==========================
# 運算邏輯
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

        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        packer.pack(bigger_first=True)
        
        fig = go.Figure()
        
        axis_config = dict(
            backgroundcolor="white", showbackground=True, zerolinecolor="#000000", 
            gridcolor="#888888", linecolor="#000000", tickfont=dict(color="#000000", size=11) 
        )
        
        # === 關鍵修正：針對手機優化的圖表邊距 ===
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            scene=dict(
                xaxis={**axis_config, 'title': 'L'},
                yaxis={**axis_config, 'title': 'W'},
                zaxis={**axis_config, 'title': 'H'},
                aspectmode='data'
            ),
            # 將上下左右邊距設為 0，讓圖表盡可能撐滿容器，避免手機上被截斷
            margin=dict(t=10, b=10, l=0, r=0), 
            height=500 # 設定固定高度
        )

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
                missing_items_html += f"<li style='color: #D8000C; background-color: #FFD2D2; padding: 5px; margin: 3px 0; border-radius: 4px;'>⚠️ {name}: 遺漏 {diff}</li>"

        status_html = "<div style='color: #155724; background-color: #d4edda; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold;'>✅ 完美裝箱</div>" if all_fitted else f"<div style='color: #721c24; background-color: #f8d7da; padding: 10px; border-radius: 5px; font-weight: bold;'>❌ 有遺漏</div><ul style='padding-left: 20px; font-size: 0.9em;'>{missing_items_html}</ul>"

        report_html = f"""
        <div class="report-card">
            <h3 style="margin-top:0; border-bottom: 2px solid #333; padding-bottom: 5px; font-size: 1.2em;">📋 {order_name}</h3>
            <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                <span>📦 尺寸:</span><span>{box_l}x{box_w}x{box_h}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                <span>⚖️ 總重:</span><span style="color: #d9534f; font-weight: bold;">{gross_weight:.2f} kg</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
                <span>📊 利用率:</span><span>{utilization:.2f}%</span>
            </div>
            {status_html}
        </div>
        """

        st.header("📊 3. 裝箱結果")
        st.markdown(report_html, unsafe_allow_html=True)
        
        file_name = f"{order_name.replace(' ', '_')}_{file_time_str}_總數{total_qty}.html"
        full_html = f"<html><body>{report_html}{fig.to_html()}</body></html>"
        
        st.download_button("📥 下載報告", full_html, file_name, "text/html", type="primary")
        
        # 顯示圖表 (已優化手機顯示)
        st.plotly_chart(fig, use_container_width=True)
