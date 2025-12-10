import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import datetime
import copy

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

st.title("📦 3D裝箱系統 (智慧容錯版)")
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
    
    shape_options = ["不變形", "對折 (長度/2, 高度x2)", "L型彎折 (智慧堆疊)"]

    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame([
            {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5, "變形模式": "不變形"},
            {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5, "變形模式": "L型彎折 (智慧堆疊)"},
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
# 核心運算邏輯 (封裝成函數以支援重試)
# ==========================
def run_packing_simulation(use_l_shape_logic=True):
    packer = Packer()
    box = Bin('StandardBox', box_l, box_w, box_h, 999999)
    packer.add_bin(box)
    
    items_to_pack = []
    l_shape_groups = {} 
    
    # 1. 解析資料
    for index, row in edited_df.iterrows():
        try:
            name = str(row["商品名稱"])
            l, w, h = float(row["長"]), float(row["寬"]), float(row["高"])
            weight = float(row["重量(kg)"])
            qty = int(row["數量"])
            mode = str(row["變形模式"])
            
            if qty > 0:
                # 策略選擇：如果啟用 L 型邏輯且使用者選擇了 L 型
                if use_l_shape_logic and mode == "L型彎折 (智慧堆疊)":
                    if name not in l_shape_groups:
                        l_shape_groups[name] = {'l': l, 'w': w, 'h': h, 'weight': weight, 'qty': 0}
                    l_shape_groups[name]['qty'] += qty
                else:
                    # 否則 (或降級模式下) 當作一般物品處理
                    # 如果是 L 型模式但被降級，我們預設將其「攤平」處理 (當作超薄墊子)
                    # 這就是解決「攤平也放不下」的關鍵：回到最原始的物理狀態
                    current_l, current_h = l, h
                    
                    if "對折" in mode:
                        current_l, current_h = l/2, h*2
                        name = f"{name}(Folded)"
                    
                    for _ in range(qty):
                        items_to_pack.append({
                            'item': Item(name, current_l, w, current_h, weight),
                            'priority': 10, # 一般優先級
                            'base_name': name,
                            'is_stack': False
                        })
        except: pass

    # 2. 處理 L 型實體堆疊 (如果有的話)
    for name, data in l_shape_groups.items():
        total_qty = data['qty']
        
        # 牆壁厚度 0.5cm
        wall_thick = 0.5
        visual_wall_height = 10.0 # 模擬牆高
        
        # 積木 A: 牆壁堆疊 (Priority 0 - 最高，貼牆)
        items_to_pack.append({
            'item': Item(f"{name}(Wall)", wall_thick, data['w'], visual_wall_height, data['weight']*0.1*total_qty),
            'priority': 0, 
            'base_name': name,
            'is_stack': True,
            'stack_qty': total_qty,
            'stack_type': 'wall',
            'unit_dim': (wall_thick, data['w'], visual_wall_height)
        })
        
        # 積木 B: 地板堆疊 (Priority 1 - 次高，鋪底)
        # 關鍵：這裡的厚度是 h * qty。如果 h 很小(0.3)，5個也才1.5cm，絕對不會擋路
        floor_len = data['l'] - wall_thick
        total_floor_h = data['h'] * total_qty
        
        items_to_pack.append({
            'item': Item(f"{name}(Floor)", floor_len, data['w'], total_floor_h, data['weight']*0.9*total_qty),
            'priority': 1, 
            'base_name': name,
            'is_stack': True,
            'stack_qty': total_qty,
            'stack_type': 'floor',
            'unit_dim': (floor_len, data['w'], data['h'])
        })

    # 3. 排序與裝箱
    items_to_pack.sort(key=lambda x: x['priority'])
    for entry in items_to_pack:
        packer.add_item(entry['item'])

    packer.pack(bigger_first=False) # 讓優先級高的(牆/地)先入
    
    return packer, items_to_pack

if run_button:
    with st.spinner('正在進行智慧裝箱運算...'):
        
        # === 第一階段：嘗試 L 型堆疊模式 ===
        packer, items_list = run_packing_simulation(use_l_shape_logic=True)
        
        # 檢查是否所有物品都裝進去了？
        total_items_count = sum([len(b.items) for b in packer.bins])
        expected_items_count = len(items_list) # 這是我們送進去的積木總數
        
        # 如果有積木沒裝進去，代表 L 型策略失敗 (可能卡住了)
        # 這時候我們啟動「降級機制」，改用全攤平模式
        if total_items_count < expected_items_count:
            # === 第二階段：自動降級為全攤平模式 (保底方案) ===
            # 這能解決「明明放得下卻報錯」的問題
            packer, items_list = run_packing_simulation(use_l_shape_logic=False)

        # --- 以下為共用的繪圖與報表邏輯 (保持不變) ---
        
        # 建立資料查找表
        item_data_map = {entry['item'].name: entry for entry in items_list}
        
        # 顏色分配
        unique_products = list(set([entry['base_name'] for entry in items_list]))
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        # 準備統計
        requested_counts = {}
        for index, row in edited_df.iterrows():
            requested_counts[str(row["商品名稱"])] = requested_counts.get(str(row["商品名稱"]), 0) + int(row["數量"])

        # 3D 繪圖
        fig = go.Figure()
        axis_config = dict(backgroundcolor="white", showbackground=True, zerolinecolor="black", gridcolor="#999999", linecolor="black", showgrid=True, showline=True, tickfont=dict(color="black"), title=dict(font=dict(color="black")))
        fig.update_layout(
            template="plotly_white", font=dict(color="black"), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            scene=dict(xaxis={**axis_config, 'title':'長(L)'}, yaxis={**axis_config, 'title':'寬(W)'}, zaxis={**axis_config, 'title':'高(H)'}, aspectmode='data', camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))),
            margin=dict(t=30, b=0, l=0, r=0), height=600, legend=dict(x=0, y=1, bgcolor="rgba(255,255,255,0.8)", borderwidth=1)
        )
        fig.add_trace(go.Scatter3d(x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l], y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w], z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0], mode='lines', line=dict(color='black', width=6), name='外箱'))

        total_vol = 0
        total_net_weight = 0
        packed_counts_merged = {} 

        for b in packer.bins:
            for item in b.items:
                raw_name = item.name
                entry_data = item_data_map.get(raw_name)
                if not entry_data: continue

                base_name = entry_data['base_name']
                is_stack = entry_data.get('is_stack', False)
                stack_qty = entry_data.get('stack_qty', 1)

                # 統計邏輯：排除 Wall，避免重複
                if "(Wall)" not in raw_name:
                    packed_counts_merged[base_name] = packed_counts_merged.get(base_name, 0) + stack_qty

                x, y, z = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                w, d, h = float(dim[0]), float(dim[1]), float(dim[2])
                
                total_vol += (w * d * h)
                total_net_weight += float(item.weight)
                color = product_colors.get(base_name, '#888')

                # 繪圖
                if is_stack:
                    stack_type = entry_data.get('stack_type')
                    unit_w, unit_d, unit_h = entry_data.get('unit_dim')
                    
                    for i in range(stack_qty):
                        if stack_type == 'wall':
                            sub_x = x + (unit_w * i)
                            sub_y, sub_z = y, z
                            sub_dim_w, sub_dim_d, sub_dim_h = unit_w, unit_d, unit_h
                        else:
                            sub_x, sub_y = x, y
                            sub_z = z + (unit_h * i)
                            sub_dim_w, sub_dim_d, sub_dim_h = unit_w, unit_d, unit_h
                        
                        fig.add_trace(go.Mesh3d(
                            x=[sub_x, sub_x+sub_dim_w, sub_x+sub_dim_w, sub_x, sub_x, sub_x+sub_dim_w, sub_x+sub_dim_w, sub_x],
                            y=[sub_y, sub_y, sub_y+sub_dim_d, sub_y+sub_dim_d, sub_y, sub_y, sub_y+sub_dim_d, sub_y+sub_dim_d],
                            z=[sub_z, sub_z, sub_z, sub_z, sub_z+sub_dim_h, sub_z+sub_dim_h, sub_z+sub_dim_h, sub_z+sub_dim_h],
                            i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                            color=color, opacity=1, name=base_name, showlegend=(i==0), hoverinfo='text', text=f"{base_name} ({i+1}/{stack_qty})"
                        ))
                        fig.add_trace(go.Scatter3d(
                            x=[sub_x, sub_x+sub_dim_w, sub_x+sub_dim_w, sub_x, sub_x, sub_x, sub_x+sub_dim_w, sub_x+sub_dim_w, sub_x, sub_x, sub_x, sub_x, sub_x+sub_dim_w, sub_x+sub_dim_w, sub_x+sub_dim_w, sub_x+sub_dim_w],
                            y=[sub_y, sub_y, sub_y+sub_dim_d, sub_y+sub_dim_d, sub_y, sub_y, sub_y, sub_y, sub_y+sub_dim_d, sub_y+sub_dim_d, sub_y, sub_y+sub_dim_d, sub_y+sub_dim_d, sub_y, sub_y, sub_y+sub_dim_d],
                            z=[sub_z, sub_z, sub_z, sub_z, sub_z, sub_z+sub_dim_h, sub_z+sub_dim_h, sub_z+sub_dim_h, sub_z+sub_dim_h, sub_z+sub_dim_h, sub_z, sub_z+sub_dim_h, sub_z+sub_dim_h, sub_z+sub_dim_h, sub_z, sub_z],
                            mode='lines', line=dict(color='black', width=2), showlegend=False
                        ))
                else:
                    fig.add_trace(go.Mesh3d(
                        x=[x, x+w, x+w, x, x, x+w, x+w, x], y=[y, y, y+d, y+d, y, y, y+d, y+d], z=[z, z, z, z, z+h, z+h, z+h, z+h],
                        i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                        color=color, opacity=1, name=base_name, showlegend=True, hoverinfo='text', text=f"{base_name}<br>Pos:({x},{y},{z})"
                    ))
                    fig.add_trace(go.Scatter3d(
                        x=[x, x+w, x+w, x, x, x, x+w, x+w, x, x, x, x, x+w, x+w, x+w, x+w],
                        y=[y, y, y+d, y+d, y, y, y, y, y+d, y+d, y, y+d, y+d, y, y, y+d],
                        z=[z, z, z, z, z, z+h, z+h, z+h, z+h, z+h, z, z+h, z+h, z+h, z, z],
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
