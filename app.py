import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import datetime
import copy  # 新增引用，用於深層複製物件

# ==========================
# 頁面設定
# ==========================
st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="collapsed")

# ==========================
# CSS：強制介面修復
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
        box_l = c1.number_input("長", value=35.0, step=1.0)
        box_w = c2.number_input("寬", value=25.0, step=1.0)
        box_h = c3.number_input("高", value=20.0, step=1.0)
        
        box_weight = st.number_input("空箱重量 (kg)", value=0.5, step=0.1)

with col_right:
    st.markdown('<div class="section-header">2. 商品清單 (直接編輯表格)</div>', unsafe_allow_html=True)
    
    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame(
            [
                {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5},
                {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5},
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
        
        # 準備資料與變數
        max_weight_limit = 999999
        requested_counts = {}
        unique_products = []
        total_qty = 0
        
        # 1. 預處理：排序
        #    保留您的邏輯：先計算底面積，大底面積先放 (解決紙袋問題)
        edited_df['base_area'] = edited_df['長'] * edited_df['寬']
        sorted_df = edited_df.sort_values(by='base_area', ascending=False)
        
        # 統計需求總量
        for index, row in sorted_df.iterrows():
            name = str(row["商品名稱"])
            qty = int(row["數量"])
            if qty > 0:
                total_qty += qty
                if name not in requested_counts:
                    requested_counts[name] = 0
                    unique_products.append(name)
                requested_counts[name] += qty

        # ==========================================
        # 智慧運算核心：多模式嘗試 (Smart Retry Logic)
        # ==========================================
        
        def try_pack(orientation_mode=0):
            """
            嘗試進行裝箱
            orientation_mode: 
               0 = 預設 (平放)
               1 = 側放 (將高度轉為寬度)
               2 = 直立 (將高度轉為長度)
            """
            local_packer = Packer()
            # 建立箱子
            local_box = Bin('StandardBox', box_l, box_w, box_h, max_weight_limit)
            local_packer.add_bin(local_box)
            
            for index, row in sorted_df.iterrows():
                try:
                    name = str(row["商品名稱"])
                    l_orig = float(row["長"])
                    w_orig = float(row["寬"])
                    h_orig = float(row["高"])
                    weight = float(row["重量(kg)"])
                    qty = int(row["數量"])
                    
                    # 判斷是否為「扁平物」(如紙袋)，如果是，強制保持原樣，不旋轉
                    # 判斷標準：如果高度明顯小於長寬 (例如小於 1/5)，視為扁平物
                    is_flat_item = (h_orig < l_orig * 0.2) and (h_orig < w_orig * 0.2)
                    
                    # 決定傳入 Packer 的尺寸
                    if is_flat_item or orientation_mode == 0:
                        # 模式0或扁平物：維持原樣 (L, W, H)
                        final_l, final_w, final_h = l_orig, w_orig, h_orig
                    elif orientation_mode == 1:
                        # 模式1：嘗試側放 (L, H, W) -> 讓原本的高變成寬，引導 Packer 嘗試側立
                        final_l, final_w, final_h = l_orig, h_orig, w_orig
                    elif orientation_mode == 2:
                        # 模式2：嘗試直立 (H, W, L)
                        final_l, final_w, final_h = h_orig, w_orig, l_orig
                        
                    for _ in range(qty):
                        # 注意：這裡雖然改變輸入尺寸順序，py3dbp 內部還是會嘗試旋轉
                        # 但改變輸入順序可以改變 Greedy 演算法的「首選」方向
                        item = Item(name, final_l, final_w, final_h, weight)
                        local_packer.add_item(item)
                except:
                    pass
            
            # 執行裝箱
            # bigger_first=False 是為了尊重我們依照「底面積」排好的順序 (紙袋先)
            local_packer.pack(bigger_first=False)
            return local_packer

        # 開始嘗試不同策略，找出最佳解
        best_packer = None
        best_fitted_count = -1
        
        # 依序嘗試： 0=預設, 1=側放優先, 2=直立優先
        # 這樣如果預設平放就裝得下，就會直接用預設的
        modes_to_try = [0, 1, 2] 
        
        for mode in modes_to_try:
            current_packer = try_pack(mode)
            
            # 計算裝入的數量
            fitted_count = 0
            for b in current_packer.bins:
                fitted_count += len(b.items)
            
            # 如果這個模式裝入的比較多，或者一樣多但我們還沒找到最佳解，就暫存它
            if fitted_count > best_fitted_count:
                best_fitted_count = fitted_count
                best_packer = current_packer
            
            # 如果已經全部裝下了，就不用再試其他模式了，省時間
            if best_fitted_count == total_qty:
                break
        
        # 最終確認使用的 Packer
        packer = best_packer if best_packer else try_pack(0)
        
        # ==========================================
        # 運算結束，準備繪圖
        # ==========================================

        fig = go.Figure()
        
        # 1. 座標軸樣式 (強制黑色)
        axis_config = dict(
            backgroundcolor="white",
            showbackground=True,
            zerolinecolor="#000000",
            gridcolor="#999999",
            linecolor="#000000",
            showgrid=True,
            showline=True,
            tickfont=dict(color="black", size=12, family="Arial Black"),
            title=dict(font=dict(color="black", size=14, family="Arial Black"))
        )
        
        # 修改區塊：調整 layout 設定
        fig.update_layout(
            template="plotly_white", # 強制白底
            font=dict(color="black"), # 全局黑色字體
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            autosize=True, 
            scene=dict(
                xaxis={**axis_config, 'title': '長 (L)'},
                yaxis={**axis_config, 'title': '寬 (W)'},
                zaxis={**axis_config, 'title': '高 (H)'},
                aspectmode='data',
                # 設定相機視角，模擬等角視圖
                camera=dict(
                    eye=dict(x=1.6, y=1.6, z=1.6)
                )
            ),
            margin=dict(t=30, b=0, l=0, r=0), 
            height=600, 
            # 圖例位置調整至左上角
            legend=dict(
                x=0, y=1, 
                xanchor="left",
                yanchor="top",
                font=dict(color="black", size=13),
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="#000000",
                borderwidth=1
            )
        )

        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
            z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
            mode='lines', line=dict(color='#000000', width=6), name='外箱'
        ))

        total_vol = 0
        total_net_weight = 0
        packed_counts = {}
        
        # 顏色設定
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

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
                # 提示文字
                hover_text = f"{item.name}<br>實際佔用: {idim_w}x{idim_d}x{idim_h}<br>重量: {i_weight:.2f}kg<br>位置:({x},{y},{z})"
                
                fig.add_trace(go.Mesh3d(
                    x=[x, x+idim_w, x+idim_w, x, x, x+idim_w, x+idim_w, x],
                    y=[y, y, y+idim_d, y+idim_d, y, y, y+idim_d, y+idim_d],
