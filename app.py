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
# CSS (確保文字清晰)
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
    .g-gtitle, .g-xtitle, .g-ytitle, .g-ztitle, .legendtext, .tick text {
        fill: #000000 !important; color: #000000 !important; font-family: Arial !important; font-weight: bold !important;
    }
    .block-container { padding-top: 2rem !important; }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統 (強制收納邏輯版)")
st.markdown("---")

# ==========================
# 輸入區
# ==========================
col_left, col_right = st.columns([1, 2], gap="large")

with col_left:
    st.markdown('### 1. 訂單與外箱')
    with st.container():
        order_name = st.text_input("訂單名稱", value="訂單_20241208")
        c1, c2, c3 = st.columns(3)
        box_l = c1.number_input("長", value=35.0, step=1.0)
        box_w = c2.number_input("寬", value=25.0, step=1.0)
        box_h = c3.number_input("高", value=20.0, step=1.0)
        box_weight = st.number_input("空箱重量 (kg)", value=0.5, step=0.1)

with col_right:
    st.markdown('### 2. 商品清單')
    shape_options = ["不變形", "對折 (長度/2, 高度x2)", "L型彎折 (內襯墊底)"]
    
    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame([
            {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 3, "變形模式": "不變形"},
            {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 3, "變形模式": "對折 (長度/2, 高度x2)"}, 
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
    with st.spinner('正在進行邏輯演算...'):
        
        # 1. 帳本初始化
        ledger_request = {}   # 需求數量
        ledger_packed = {}    # 實際裝箱數量 (絕對真理)
        
        packer_items = []     # 給演算法的
        lining_data = None    # 手動繪製的L型
        
        total_net_weight = 0
        
        # 2. 資料處理
        for index, row in edited_df.iterrows():
            try:
                name = str(row["商品名稱"])
                l, w, h = float(row["長"]), float(row["寬"]), float(row["高"])
                weight = float(row["重量(kg)"])
                qty = int(row["數量"])
                mode = str(row["變形模式"])
                
                if qty > 0:
                    ledger_request[name] = ledger_request.get(name, 0) + qty
                    
                    # === [A] L型內襯 (完全手動，不進 Packer) ===
                    if mode == "L型彎折 (內襯墊底)":
                        # 計算佔用空間
                        wall_t = h * qty
                        floor_t = h * qty
                        
                        lining_data = {
                            'name': name, 'l': l, 'w': w, 'h': h, 'qty': qty,
                            'off_x': wall_t, 'off_z': floor_t, 'vis_h': l * 0.3,
                            'weight': weight
                        }
                        
                        # 手動記入帳本 (修復報表錯誤)
                        ledger_packed[name] = ledger_packed.get(name, 0) + qty
                        total_net_weight += (weight * qty)
                        
                    # === [B] 對折 (強制綑綁，進 Packer) ===
                    elif "對折" in mode:
                        folded_l = l / 2
                        folded_h = h * 2
                        
                        # 強制堆疊：把 qty 個疊成一個大方塊
                        stack_h = folded_h * qty
                        stack_weight = weight * qty
                        
                        # 建立一個 "Bundled Item"
                        # Area 設為極大，保證最先放入角落
                        packer_items.append({
                            'item': Item(f"{name}(Bundle)", folded_l, w, stack_h, stack_weight),
                            'area': 9999999, 
                            'base_name': name, # 原始名稱
                            'is_stack': True,
                            'stack_qty': qty,
                            'unit_h': folded_h
                        })
                        
                    # === [C] 攤平/不變形 (底面積排序，進 Packer) ===
                    else:
                        area = l * w 
                        # 這裡選擇不綑綁，讓它們自然鋪底
                        for _ in range(qty):
                            packer_items.append({
                                'item': Item(name, l, w, h, weight),
                                'area': area,
                                'base_name': name,
                                'is_stack': False,
                                'stack_qty': 1,
                                'unit_h': h
                            })
                            
            except Exception as e:
                pass

        # 3. Packer 環境準備
        packer = Packer()
        
        # 空間扣除 (L型專用)
        offset_x = 0
        offset_z = 0
        if lining_data:
            eff_l = box_l - lining_data['off_x']
            eff_h = box_h - lining_data['off_z']
            offset_x = lining_data['off_x']
            offset_z = lining_data['off_z']
            
            if eff_l <= 0 or eff_h <= 0:
                st.error("❌ 錯誤：內襯太厚，已佔滿箱子！")
                st.stop()
            bin_obj = Bin('Box', eff_l, box_w, eff_h, 999999)
        else:
            bin_obj = Bin('Box', box_l, box_w, box_h, 999999)
            
        packer.add_bin(bin_obj)

        # 4. 排序與裝箱
        # 綑綁包(Priority Max) -> 大底板 -> 小盒子
        packer_items.sort(key=lambda x: x['area'], reverse=True)
        
        for p in packer_items:
            packer.add_item(p['item'])
            
        packer.pack(bigger_first=False)

        # ==========================
        # 繪圖
        # ==========================
        fig = go.Figure()
        
        unique_names = list(ledger_request.keys())
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF']
        color_map = {name: palette[i % len(palette)] for i, name in enumerate(unique_names)}

        # 外箱
        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
            z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
            mode='lines', line=dict(color='black', width=5), name='外箱', showlegend=True
        ))

        # A. 畫 L 型內襯
        if lining_data:
            lname = lining_data['name']
            lqty = lining_data['qty']
            uh = lining_data['h']
            lc = color_map.get(lname, '#888')
            
            for i in range(lqty):
                # 底座
                fz = i * uh
                l_draw = min(lining_data['l'], box_l)
                
                fig.add_trace(go.Mesh3d(
                    x=[0, l_draw, l_draw, 0, 0, l_draw, l_draw, 0],
                    y=[0, 0, lining_data['w'], lining_data['w'], 0, 0, lining_data['w'], lining_data['w']],
                    z=[fz, fz, fz, fz, fz+uh, fz+uh, fz+uh, fz+uh],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=lc, opacity=1, name=lname, showlegend=(i==0)
                ))
                fig.add_trace(go.Scatter3d(
                    x=[0, l_draw, l_draw, 0, 0, 0, l_draw, l_draw, 0, 0, 0, 0, l_draw, l_draw, l_draw, l_draw],
                    y=[0, 0, lining_data['w'], lining_data['w'], 0, 0, 0, 0, lining_data['w'], lining_data['w'], 0, lining_data['w'], lining_data['w'], lining_data['w'], 0, 0],
                    z=[fz, fz, fz, fz, fz, fz+uh, fz+uh, fz+uh, fz+uh, fz+uh, fz, fz+uh, fz+uh, fz+uh, fz, fz],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))
                # 側牆
                wx = i * uh
                fig.add_trace(go.Mesh3d(
                    x=[wx, wx+uh, wx+uh, wx, wx, wx+uh, wx+uh, wx],
                    y=[0, 0, lining_data['w'], lining_data['w'], 0, 0, lining_data['w'], lining_data['w']],
                    z=[0, 0, 0, 0, lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h']],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=lc, opacity=1, showlegend=False
                ))
                fig.add_trace(go.Scatter3d(
                    x=[wx, wx+uh, wx+uh, wx, wx, wx, wx+uh, wx+uh, wx, wx, wx, wx, wx+uh, wx+uh, wx+uh, wx+uh],
                    y=[0, 0, lining_data['w'], lining_data['w'], 0, 0, 0, 0, lining_data['w'], lining_data['w'], 0, lining_data['w'], lining_data['w'], lining_data['w'], 0, 0],
                    z=[0, 0, 0, 0, 0, lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h'], 0, lining_data['vis_h'], lining_data['vis_h'], lining_data['vis_h'], 0, 0],
                    mode='lines', line=dict(color='black', width=2), showlegend=False
                ))

        # B. 畫 Packer 物品
        total_vol = 0
        packer_data_map = {p['item'].name: p for p in packer_items} 

        for b in packer.bins:
            for item in b.items:
                raw_name = item.name
                base_name = raw_name.split('(')[0]
                
                p_data = packer_data_map.get(raw_name)
                is_stack = p_data.get('is_stack', False) if p_data else False
                stack_qty = p_data.get('stack_qty', 1) if p_data else 1
                unit_h = p_data.get('unit_h', 0) if p_data else 0
                
                # 記入帳本 (修復報表錯誤)
                ledger_packed[base_name] = ledger_packed.get(base_name, 0) + stack_qty
                total_net_weight += float(item.weight)
                
                x, y, z = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                w, d, h = float(dim[0]), float(dim[1]), float(dim[2])
                
                # 座標偏移
                fx, fy, fz = x + offset_x, y, z + offset_z
                total_vol += (w * d * h)
                pc = color_map.get(base_name, '#888')

                if is_stack:
                    # 堆疊包
                    fig.add_trace(go.Mesh3d(
                        x=[fx, fx+w, fx+w, fx, fx, fx+w, fx+w, fx], 
                        y=[fy, fy, fy+d, fy+d, fy, fy, fy+d, fy+d], 
                        z=[fz, fz, fz, fz, fz+h, fz+h, fz+h, fz+h],
                        i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                        color=pc, opacity=1, name=base_name, showlegend=True, hoverinfo='text', text=f"{base_name} (堆疊x{stack_qty})"
                    ))
                    # 外框
                    fig.add_trace(go.Scatter3d(
                        x=[fx, fx+w, fx+w, fx, fx, fx, fx+w, fx+w, fx, fx, fx, fx, fx+w, fx+w, fx+w, fx+w],
                        y=[fy, fy, fy+d, fy+d, fy, fy, fy, fy, fy+d, fy+d, fy, fy+d, fy+d, fy+d, fy, fy],
                        z=[fz, fz, fz, fz, fz, fz+h, fz+h, fz+h, fz+h, fz+h, fz, fz+h, fz+h, fz+h, fz, fz],
                        mode='lines', line=dict(color='black', width=3), showlegend=False
                    ))
                    # 內部線
                    for i in range(1, stack_qty):
                        lz = fz + (i * unit_h)
                        fig.add_trace(go.Scatter3d(
                            x=[fx, fx+w, fx+w, fx, fx],
                            y=[fy, fy, fy+d, fy+d, fy],
                            z=[lz, lz, lz, lz, lz],
                            mode='lines', line=dict(color='black', width=1), showlegend=False
                        ))
                else:
                    # 一般
                    fig.add_trace(go.Mesh3d(
                        x=[fx, fx+w, fx+w, fx, fx, fx+w, fx+w, fx], 
                        y=[fy, fy, fy+d, fy+d, fy, fy, fy+d, fy+d], 
                        z=[fz, fz, fz, fz, fz+h, fz+h, fz+h, fz+h],
                        i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2], j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3], k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                        color=pc, opacity=1, name=base_name, showlegend=True, hoverinfo='text', text=base_name
                    ))
                    fig.add_trace(go.Scatter3d(
                        x=[fx, fx+w, fx+w, fx, fx, fx, fx+w, fx+w, fx, fx, fx, fx, fx+w, fx+w, fx+w, fx+w],
                        y=[fy, fy, fy+d, fy+d, fy, fy, fy, fy, fy+d, fy+d, fy, fy+d, fy+d, fy+d, fy, fy],
                        z=[fz, fz, fz, fz, fz, fz+h, fz+h, fz+h, fz+h, fz+h, fz, fz+h, fz+h, fz+h, fz, fz],
                        mode='lines', line=dict(color='black', width=3), showlegend=False
                    ))

        # 去重圖例
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # Layout
        fig.update_layout(
            template="plotly_white",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color="black"),
            scene=dict(
                xaxis=dict(title=dict(text='長 (L)', font=dict(color="black")), tickfont=dict(color="black"), backgroundcolor="white", gridcolor="#999999", showbackground=True),
                yaxis=dict(title=dict(text='寬 (W)', font=dict(color="black")), tickfont=dict(color="black"), backgroundcolor="white", gridcolor="#999999", showbackground=True),
                zaxis=dict(title=dict(text='高 (H)', font=dict(color="black")), tickfont=dict(color="black"), backgroundcolor="white", gridcolor="#999999", showbackground=True),
                aspectmode='data',
                camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))
            ),
            margin=dict(t=30, b=0, l=0, r=0),
            height=600,
            legend=dict(x=0, y=1, bgcolor="rgba(255,255,255,0.8)", borderwidth=1, font=dict(color="black"))
        )

        # 5. 報表生成
        box_vol = box_l * box_w * box_h
        lining_vol = 0
        if lining_data:
            lining_vol = (lining_data['off_x'] * lining_data['w'] * lining_data['vis_h']) + \
                         ((box_l - lining_data['off_x']) * lining_data['w'] * lining_data['off_z'])
        
        utilization = ((total_vol + lining_vol) / box_vol) * 100 if box_vol > 0 else 0
        gross_weight = total_net_weight + box_weight
        
        all_fitted = True
        missing_html = ""
        
        # 絕對真理比對
        for name, req in ledger_request.items():
            real = ledger_packed.get(name, 0)
            diff = req - real
            if diff > 0:
                all_fitted = False
                missing_html += f"<li style='color:red; background:#ffd2d2; padding:5px;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status = "<h3 style='color:green; background:#d4edda; padding:10px; border-radius:5px;'>✅ 完美裝箱</h3>" if all_fitted else f"<h3 style='color:red; background:#f8d7da; padding:10px; border-radius:5px;'>❌ 部分遺漏</h3><ul>{missing_html}</ul>"

        report_html = f"""
        <div class="report-card">
            <h2>📋 訂單裝箱報告</h2>
            <p><b>訂單:</b> {order_name} | <b>外箱:</b> {box_l}x{box_w}x{box_h} cm | <b>利用率:</b> {utilization:.2f}%</p>
            <p><b>總重量:</b> {gross_weight:.2f} kg</p>
            {status}
        </div>
        """
        st.markdown(report_html, unsafe_allow_html=True)
        st.download_button("📥 下載報告", report_html, "report.html", "text/html", type="primary")
        st.plotly_chart(fig, use_container_width=True, theme=None, config={'displayModeBar': False})
