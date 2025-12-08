import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import datetime

# ==========================
# 頁面設定與 CSS 強制優化 (純淨版)
# ==========================
st.set_page_config(layout="wide", page_title="3D 智能裝箱系統")

# V19 CSS 注入：隱藏所有 Streamlit 官方標記
st.markdown("""
<style>
    /* 1. 強制背景白、文字黑 */
    .stApp {
        background-color: #ffffff !important;
        color: #000000 !important;
    }
    div[data-baseweb="input"] input,
    div[data-baseweb="select"] div,
    .stDataFrame, .stTable {
        color: #000000 !important;
        background-color: #ffffff !important;
    }
    
    /* 2. 隱藏 Streamlit 官方元素 (關鍵修改) */
    #MainMenu {visibility: hidden;} /* 隱藏右上角漢堡選單 */
    footer {visibility: hidden;}    /* 隱藏頁尾 Made with Streamlit */
    header {visibility: hidden;}    /* 隱藏頂部標題列 */
    [data-testid="stToolbar"] {display: none !important;} /* 隱藏工具列 */
    [data-testid="stDecoration"] {display: none !important;} /* 隱藏頂部彩條 */
    [data-testid="stStatusWidget"] {display: none !important;} /* 隱藏連線狀態 */
    .stDeployButton {display:none;} /* 隱藏 Deploy 按鈕 */
    
    /* 3. 報表卡片樣式 */
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
    
    /* 4. 圖表樣式 */
    .js-plotly-plot .plotly .bg {
        fill: #ffffff !important;
    }
    .xtick text, .ytick text, .ztick text {
        fill: #000000 !important;
        font-weight: bold !important;
    }
    
    /* 5. 調整頂部間距 (因為隱藏了 header，把內容往上推) */
    .block-container {
        padding-top: 1rem !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D 智能裝箱系統 (專業版 V19)")
st.markdown("---")

# ==========================
# 側邊欄：設定區
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
    st.info("💡 修改下方商品清單後，請點擊執行按鈕。")
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

# ==========================
# 運算邏輯
# ==========================
if run_button:
    with st.spinner('正在進行 3D 運算...'):
        # 準備數據
        max_weight_limit = 999999
        packer = Packer()
        # 建立外箱
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
            backgroundcolor="white",
            showbackground=True,
            zerolinecolor="#000000", 
            gridcolor="#888888",    
            linecolor="#000000",    
            tickfont=dict(color="#000000", size=12) 
        )
        
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            scene=dict(
                xaxis={**axis_config, 'title': '長 (L)'},
                yaxis={**axis_config, 'title': '寬 (W)'},
                zaxis={**axis_config, 'title': '高 (H)'},
                aspectmode='data'
            ),
            margin=dict(t=30, b=0, l=0, r=0), height=600
        )

        # 畫外箱 (黑線)
        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
            z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
            mode='lines', line=dict(color='#000000', width=5), name='外箱'
        ))

        total_vol = 0
        packed_counts = {}
        
        # 畫商品
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
                hover_text = f"{item.name}<br>實際佔用: {idim_w}x{idim_d}x{idim_h}<br>重量: {i_weight:.2f}kg<br>位置:({x},{y},{z})"
                
                fig.add_trace(go.Mesh3d(
                    x=[x, x+idim_w, x+idim_w, x, x, x+idim_w, x+idim_w, x],
                    y=[y, y, y+idim_d, y+idim_d, y, y, y+idim_d, y+idim_d],
                    z=[z, z, z, z, z+idim_h, z+idim_h, z+idim_h, z+idim_h],
                    i = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
                    j = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
                    k = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=color, opacity=1, name=item.name, showlegend=True,
                    text=hover_text, hoverinfo='text',
                    lighting=dict(ambient=0.8, diffuse=0.8, specular=0.1, roughness=0.5), 
                    lightposition=dict(x=1000, y=1000, z=2000)
                ))
                fig.add_trace(go.Scatter3d(
                    x=[x, x+idim_w, x+idim_w, x, x, x, x+idim_w, x+idim_w, x, x, x, x, x+idim_w, x+idim_w, x+idim_w, x+idim_w],
                    y=[y, y, y+idim_d, y+idim_d, y, y, y, y, y+idim_d, y+idim_d, y, y+idim_d, y+idim_d, y, y, y+idim_d],
                    z=[z, z, z, z, z, z+idim_h, z+idim_h, z+idim_h, z+idim_h, z+idim_h, z, z+idim_h, z+idim_h, z+idim_h, z, z],
                    mode='lines', line=dict(color='#000000', width=2), showlegend=False
                ))

        # 整理圖表
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))
        
        # 統計
        box_vol = box_l * box_w * box_h
        utilization = (total_vol / box_vol) * 100 if box_vol > 0 else 0
        gross_weight = total_net_weight + box_weight
        
        # 台灣時間
        tw_time = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        now_str = tw_time.strftime("%Y-%m-%d %H:%M")
        file_time_str = tw_time.strftime("%Y%m%d_%H%M")
        
        # 檢查
        all_fitted = True
        missing_items_html = ""
