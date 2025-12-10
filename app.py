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
# CSS：強制介面修復
# ==========================
st.markdown("""
<style>
    .stApp { background-color: #ffffff !important; color: #000000 !important; }
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="stSidebarCollapsedControl"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    .stDeployButton { display: none !important; }
    footer { display: none !important; }
    #MainMenu { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stHeader"] { background-color: transparent !important; pointer-events: none; }
    
    div[data-baseweb="input"] input, div[data-baseweb="select"] div, .stDataFrame, .stTable {
        color: #000000 !important; background-color: #f9f9f9 !important; border-color: #cccccc !important;
    }
    
    .section-header {
        font-size: 1.2rem; font-weight: bold; color: #333;
        margin-top: 10px; margin-bottom: 5px;
        border-left: 5px solid #FF4B4B; padding-left: 10px;
    }

    .report-card {
        font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; 
        padding: 20px; border: 2px solid #e0e0e0; border-radius: 10px; 
        background: #ffffff; color: #333333; 
        box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 20px;
    }
    
    .js-plotly-plot .plotly .bg { fill: #ffffff !important; }
    .xtick text, .ytick text, .ztick text { fill: #000000 !important; font-weight: bold !important; }
    .block-container { padding-top: 2rem !important; padding-left: 0.5rem !important; padding-right: 0.5rem !important; }
</style>
""", unsafe_allow_html=True)

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
    
    shape_options = ["不變形", "對折 (長度/2, 高度x2)", "L型彎折 (靠邊擺放)"]

    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame([
            {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5, "變形模式": "不變形"},
            {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5, "變形模式": "L型彎折 (靠邊擺放)"},
        ])

    edited_df = st.data_editor(
        st.session_state.df, num_rows="dynamic", use_container_width=True, height=280,
        column_config={
            "數量": st.column_config.NumberColumn(min_value=1, step=1, format="%d"),
            "長": st.column_config.NumberColumn(format="%.1f"),
            "寬": st.column_config.NumberColumn(format="%.1f"),
            "高": st.column_config.NumberColumn(format="%.1f"),
            "重量(kg)": st.column_config.NumberColumn(format="%.2f"),
            "變形模式": st.column_config.SelectboxColumn(label="📦 裝箱變形策略", width="medium", options=shape_options, required=True)
        }
    )

st.markdown("---")
b1, b2, b3 = st.columns([1, 2, 1])
with b2:
    run_button = st.button("🚀 開始計算與 3D 模擬", type="primary", use_container_width=True)

# ==========================
# 下半部：運算邏輯
# ==========================
if run_button:
    with st.spinner('正在進行智慧裝箱運算...'):
        packer = Packer()
        box = Bin('StandardBox', box_l, box_w, box_h, 999999)
        packer.add_bin(box)
        
        requested_counts = {}
        unique_products = []
        total_qty = 0
        total_net_weight = 0
        items_to_pack = []

        # 1. 準備資料與策略
        for index, row in edited_df.iterrows():
            try:
                name_origin = str(row["商品名稱"])
                l_origin, w_origin, h_origin = float(row["長"]), float(row["寬"]), float(row["高"])
                weight_origin = float(row["重量(kg)"])
                qty, mode = int(row["數量"]), str(row["變形模式"])
                
                if qty > 0:
                    total_qty += qty
                    if name_origin not in requested_counts:
                        requested_counts[name_origin] = 0
                        unique_products.append(name_origin)
                    requested_counts[name_origin] += qty
                    
                    for _ in range(qty):
                        # === L型彎折策略 ===
                        if mode == "L型彎折 (靠邊擺放)":
                            # 策略：不縮短長度！讓底座佔滿它需要的空間
                            # 這樣它自然會延伸到箱子邊緣，不會卡在中間
                            l_pack = l_origin 
                            w_pack = w_origin
                            h_pack = h_origin # 維持薄度，讓其他商品可疊在上面
                            
                            # 加上特殊標記，讓繪圖層知道要畫虛擬牆
                            name = f"{name_origin}[L-SHAPE]"
                            items_to_pack.append({'item': Item(name, l_pack, w_pack, h_pack, weight_origin), 'priority': 0})

                        # === 對折策略 ===
                        elif mode == "對折 (長度/2, 高度x2)":
                            items_to_pack.append({'item': Item(f"{name_origin}(對折)", l_origin/2, w_origin, h_origin*2, weight_origin), 'priority': 1})
                        
                        # === 一般策略 ===
                        else:
                            items_to_pack.append({'item': Item(name_origin, l_origin, w_origin, h_origin, weight_origin), 'priority': 2})
            except: pass
        
        # 2. 排序並裝箱
        items_to_pack.sort(key=lambda x: x['priority'])
        for entry in items_to_pack: packer.add_item(entry['item'])
        
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name.replace('[L-SHAPE]', ''): palette[i % len(palette)] for i, name in enumerate(unique_products)}

        packer.pack(bigger_first=False) 
        
        # ==========================
        # 3D 繪圖層
        # ==========================
        fig = go.Figure()
        
        axis_config = dict(backgroundcolor="white", showbackground=True, zerolinecolor="black", gridcolor="#999999", linecolor="black", showgrid=True, showline=True, tickfont=dict(color="black"), title=dict(font=dict(color="black")))
        fig.update_layout(
            template="plotly_white", font=dict(color="black"), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            scene=dict(xaxis={**axis_config, 'title':'長(L)'}, yaxis={**axis_config, 'title':'寬(W)'}, zaxis={**axis_config, 'title':'高(H)'}, aspectmode='data', camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))),
            margin=dict(t=30, b=0, l=0, r=0), height=600, legend=dict(x=0, y=1, bgcolor="rgba(255,255,255,0.8)", borderwidth=1)
        )

        # 畫外箱
        fig.add_trace(go.Scatter3d(x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l], y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w], z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0], mode='lines', line=dict(color='black', width=6), name='外箱'))

        total_vol = 0
        packed_counts = {}
        
        for b in packer.bins:
            for item in b.items:
                is_l_shape = "[L-SHAPE]" in item.name
                base_name = item.name.replace('[L-SHAPE]', '')
                packed_counts[base_name] = packed_counts.get(base_name, 0) + 1
                
                x, y, z = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                w, d, h = float(dim[0]), float(dim[1]), float(dim[2]) # 實際裝箱長寬高
                total_vol += (w * d * h)
                total_net_weight += float(item.weight)
                color = product_colors.get(base_name, '#888')

                # 畫底座 (實體)
                fig.add_trace(go.Mesh3d(
                    x=[x, x+w, x+w, x, x, x+w, x+w, x], y=[y, y, y+d, y+d, y, y, y+d, y+d], z=[z, z, z, z, z+h, z+h, z+h, z+h],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=color, opacity=1, name=base_name, showlegend=True, hoverinfo='text', text=f"{base_name}<br>Pos:({x},{y},{z})"
                ))
                # 畫底座線框 (確保數量可見)
                fig.add_trace(go.Scatter3d(
                    x=[x, x+w, x+w, x, x, x, x+w, x+w, x, x, x, x, x+w, x+w, x+w, x+w],
                    y=[y, y, y+d, y+d, y, y, y, y, y+d, y+d, y, y+d, y+d, y, y, y+d],
                    z=[z, z, z, z, z, z+h, z+h, z+h, z+h, z+h, z, z+h, z+h, z+h, z, z],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))

                if is_l_shape:
                    # === 虛擬牆繪製 (解決數量與位置問題) ===
                    # 邏輯：在底座的「長邊」末端長出一道牆
                    # 自動偵測哪邊是長邊 (因為 packer 可能會旋轉物品)
                    
                    wall_height = 8.0 # 預設側牆高度 (可調整)
                    wall_thick = 0.5
                    
                    # 判斷方向：沿著長邊畫牆
                    if w >= d: # X軸是長邊
                        wx, wy, wz = x + w - wall_thick, y, z
                        ww, wd, wh = wall_thick, d, wall_height
                    else: # Y軸是長邊
                        wx, wy, wz = x, y + d - wall_thick, z
                        ww, wd, wh = w, wall_thick, wall_height
                        
                    # 畫虛擬牆 (Mesh)
                    fig.add_trace(go.Mesh3d(
                        x=[wx, wx+ww, wx+ww, wx, wx, wx+ww, wx+ww, wx], y=[wy, wy, wy+wd, wy+wd, wy, wy, wy+wd, wy+wd], z=[wz, wz, wz, wz, wz+wh, wz+wh, wz+wh, wz+wh],
                        i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                        color=color, opacity=0.8, showlegend=False
                    ))
                    # 畫虛擬牆線框 (關鍵！解決 5個變1個 的視覺問題)
                    fig.add_trace(go.Scatter3d(
                        x=[wx, wx+ww, wx+ww, wx, wx, wx, wx+ww, wx+ww, wx, wx, wx, wx, wx+ww, wx+ww, wx+ww, wx+ww],
                        y=[wy, wy, wy+wd, wy+wd, wy, wy, wy, wy, wy+wd, wy+wd, wy, wy+wd, wy+wd, wy, wy, wy+wd],
                        z=[wz, wz, wz, wz, wz, wz+wh, wz+wh, wz+wh, wz+wh, wz+wh, wz, wz+wh, wz+wh, wz+wh, wz, wz],
                        mode='lines', line=dict(color='black', width=2), showlegend=False
                    ))

        # 報表邏輯
        box_vol = box_l * box_w * box_h
        utilization = (total_vol / box_vol) * 100 if box_vol > 0 else 0
        gross_weight = total_net_weight + box_weight
        now_str = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
        
        all_fitted, missing_html = True, ""
        for name, req in requested_counts.items():
            diff = req - packed_counts.get(name, 0)
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
