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

st.title("📦 3D裝箱系統 (L型物理堆疊修正版)")
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
    
    shape_options = ["不變形", "對折 (長度/2, 高度x2)", "L型彎折 (巢狀堆疊+防穿透)"]

    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame([
            {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5, "變形模式": "不變形"},
            {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5, "變形模式": "L型彎折 (巢狀堆疊+防穿透)"},
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
    with st.spinner('正在進行物理堆疊模擬...'):
        packer = Packer()
        box = Bin('StandardBox', box_l, box_w, box_h, 999999)
        packer.add_bin(box)
        
        requested_counts = {}
        unique_products = []
        total_net_weight = 0
        items_to_pack = []

        # 1. 資料前處理與策略分配
        for index, row in edited_df.iterrows():
            try:
                name_origin = str(row["商品名稱"])
                l_origin, w_origin, h_origin = float(row["長"]), float(row["寬"]), float(row["高"])
                weight_origin = float(row["重量(kg)"])
                qty, mode = int(row["數量"]), str(row["變形模式"])
                
                if qty > 0:
                    # 統計需求
                    if name_origin not in requested_counts:
                        requested_counts[name_origin] = 0
                        unique_products.append(name_origin)
                    requested_counts[name_origin] += qty
                    
                    # === L型核心策略：物理實體分割 + 堆疊 (Stacking) ===
                    if mode == "L型彎折 (巢狀堆疊+防穿透)":
                        # 我們將 所有數量 的紙袋，合併成「1組」堆疊好的實體
                        # 這樣可以避免演算法把紙袋散得到處都是
                        
                        # 積木 A: 牆壁組 (Wall Stack)
                        # 實體厚度 0.5cm，高度模擬 10cm
                        wall_thick = 0.5
                        wall_height = 10.0
                        
                        # Priority 0: 最高優先級 -> 強制先放 -> 必定貼牆
                        items_to_pack.append({
                            'item': Item(f"{name_origin}(WallStack)", wall_thick, w_origin, wall_height, weight_origin*0.1*qty),
                            'priority': 0, 
                            'base_name': name_origin,
                            'stack_qty': qty, # 記錄這一塊代表幾個紙袋
                            'is_stack': True
                        })
                        
                        # 積木 B: 地板組 (Floor Stack)
                        # 長度扣掉牆壁厚度，高度是所有紙袋疊起來的高度
                        floor_height_total = h_origin * qty # 0.3 * 5 = 1.5cm
                        
                        # Priority 1: 第二順位 -> 必定鋪在牆壁前方底部
                        items_to_pack.append({
                            'item': Item(f"{name_origin}(FloorStack)", l_origin - wall_thick, w_origin, floor_height_total, weight_origin*0.9*qty),
                            'priority': 1, 
                            'base_name': name_origin,
                            'stack_qty': qty,
                            'is_stack': True
                        })
                        
                    # === 對折策略 ===
                    elif "對折" in mode:
                        for i in range(qty):
                            items_to_pack.append({
                                'item': Item(f"{name_origin}(Folded)", l_origin/2, w_origin, h_origin*2, weight_origin),
                                'priority': 2,
                                'base_name': name_origin,
                                'stack_qty': 1,
                                'is_stack': False
                            })
                    
                    # === 一般策略 ===
                    else:
                        for i in range(qty):
                            # 一般商品最後放 (Priority 3)，讓它們利用 L 型留下的空間
                            items_to_pack.append({
                                'item': Item(name_origin, l_origin, w_origin, h_origin, weight_origin),
                                'priority': 3,
                                'base_name': name_origin,
                                'stack_qty': 1,
                                'is_stack': False
                            })
            except: pass
        
        # 2. 關鍵排序：Priority 0 (牆) -> 1 (地) -> 2 (其他)
        items_to_pack.sort(key=lambda x: x['priority'])
        
        # 3. 加入裝箱機
        for entry in items_to_pack:
            packer.add_item(entry['item'])

        # 4. 執行裝箱 (bigger_first=False)
        # 讓牆壁組先放入，確保佔據邊角
        packer.pack(bigger_first=False) 
        
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

        # 畫外箱
        fig.add_trace(go.Scatter3d(x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l], y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w], z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0], mode='lines', line=dict(color='black', width=6), name='外箱'))

        # 顏色
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        total_vol = 0
        packed_counts_merged = {} # 用來統計「真實」數量
        
        # 建立 item 對應的 stack_qty 映射 (因為 Packer 裡的 item 物件沒有 stack_qty 屬性)
        item_stack_map = {entry['item'].name: entry['stack_qty'] for entry in items_to_pack}
        
        for b in packer.bins:
            for item in b.items:
                raw_name = item.name
                # 從映射表找回原始 base_name 和 數量
                # 這裡要小心名稱比對，我們用 startswith
                stack_qty = 1
                base_name = raw_name.split('(')[0]
                
                # 找回 stack_qty
                if raw_name in item_stack_map:
                    stack_qty = item_stack_map[raw_name]
                
                # 統計數量 (只統計非Wall的部分，避免重複，但要加上堆疊的數量)
                if "(WallStack)" not in raw_name:
                    packed_counts_merged[base_name] = packed_counts_merged.get(base_name, 0) + stack_qty
                
                x, y, z = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                w, d, h = float(dim[0]), float(dim[1]), float(dim[2])
                
                total_vol += (w * d * h)
                total_net_weight += float(item.weight)
                color = product_colors.get(base_name, '#888')
                
                # === 繪圖 ===
                # 1. 實體 Mesh
                fig.add_trace(go.Mesh3d(
                    x=[x, x+w, x+w, x, x, x+w, x+w, x], y=[y, y, y+d, y+d, y, y, y+d, y+d], z=[z, z, z, z, z+h, z+h, z+h, z+h],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=color, opacity=1, name=base_name, showlegend=True, hoverinfo='text', text=f"{base_name}<br>Pos:({x},{y},{z})<br>Size:{w}x{d}x{h}"
                ))
                
                # 2. 邊框線
                fig.add_trace(go.Scatter3d(
                    x=[x, x+w, x+w, x, x, x, x+w, x+w, x, x, x, x, x+w, x+w, x+w, x+w],
                    y=[y, y, y+d, y+d, y, y, y, y, y+d, y+d, y, y+d, y+d, y, y, y+d],
                    z=[z, z, z, z, z, z+h, z+h, z+h, z+h, z+h, z, z+h, z+h, z+h, z, z],
                    mode='lines', line=dict(color='black', width=3), showlegend=False
                ))

                # 3. 如果是堆疊物件，畫出內部分隔線 (Visual Trick)
                if stack_qty > 1:
                    # 畫出每一層的線條
                    single_h = h / stack_qty
                    for i in range(1, stack_qty):
                        level_z = z + single_h * i
                        fig.add_trace(go.Scatter3d(
                            x=[x, x+w, x+w, x, x],
                            y=[y, y, y+d, y+d, y],
                            z=[level_z, level_z, level_z, level_z, level_z],
                            mode='lines', line=dict(color='black', width=1), showlegend=False
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
