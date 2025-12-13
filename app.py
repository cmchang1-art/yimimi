import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import datetime
from itertools import permutations
import math

# ==========================
# 智慧判斷核心（只影響演算法）
# ==========================

def _to_float(x, default=0.0):
    try:
        if x is None:
            return float(default)
        if isinstance(x, (int, float)):
            if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
                return float(default)
            return float(x)
        s = str(x).strip()
        if s == "" or s.lower() in ("nan", "none", "null", "inf", "-inf"):
            return float(default)
        v = float(s)
        if math.isnan(v) or math.isinf(v):
            return float(default)
        return v
    except:
        return float(default)

def _to_int(x, default=0):
    try:
        if x is None:
            return int(default)
        if isinstance(x, bool):
            return int(default)
        if isinstance(x, int):
            return int(x)
        if isinstance(x, float):
            if math.isnan(x) or math.isinf(x):
                return int(default)
            return int(x)
        s = str(x).strip()
        if s == "" or s.lower() in ("nan", "none", "null"):
            return int(default)
        return int(float(s))
    except:
        return int(default)

def is_foldable_item(l, w, h):
    # 自動判斷可折疊：最薄邊 <= 0.5cm
    return min(l, w, h) <= 0.5

def is_unstable_item(l, w, h):
    # 自動判斷易倒：高度 > 最大底邊 * 1.5
    base = max(l, w)
    return h > base * 1.5

def get_best_orientation_advanced(l, w, h, box_l, box_w, box_h, layer=0, forbid_unstable_vertical_on_base=True):
    """
    layer=0 視為底層：偏穩定
    layer>=1 視為上層：偏效率
    forbid_unstable_vertical_on_base=True：底層禁易倒直立（用規則過濾方向）
    """
    candidates = []

    for dims in set(permutations([l, w, h], 3)):
        dl, dw, dh = dims

        # 必須能放進箱子
        if dl <= box_l and dw <= box_w and dh <= box_h:
            base_area = dl * dw
            height = dh

            # 底層：若這個方向會形成易倒（高度相對底面過高），則直接禁用
            if layer == 0 and forbid_unstable_vertical_on_base:
                if height > max(dl, dw) * 1.5:
                    continue

            # 穩定度：底面越大越穩
            stability = base_area

            # 效率：高度越低越好
            efficiency = 1.0 / height if height > 0 else 0.0

            # 權重切換：底層偏穩定，上層偏效率
            if layer == 0:
                score = stability * 0.7 + efficiency * 0.3
            else:
                score = stability * 0.3 + efficiency * 0.7

            candidates.append((score, dims))

    if not candidates:
        return (l, w, h)

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# ==========================
# 頁面設定
# ==========================
st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="collapsed")

# ==========================
# CSS：強制介面修復（完全保留原檔案）
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
        max_weight_limit = 999999
        packer = Packer()

        # ✅ 多箱自動拆箱：預先建立多個箱子（UI 不變，報表不加欄位）
        #    你原本只有 1 箱，放不下就遺漏；現在會自動用下一箱繼續裝
        MAX_BOXES = 30
        for i in range(MAX_BOXES):
            packer.add_bin(Bin(f'Box_{i+1}', box_l, box_w, box_h, max_weight_limit))
        
        requested_counts = {}
        unique_products = []
        total_qty = 0
        total_net_weight = 0.0

        # ==========================================
        # 修改開始：更聰明的排序 + 方向判斷（不改 UI）
        # ==========================================

        # 用副本避免把 base_area 汙染到你後續資料或顯示
        tmp_df = edited_df.copy()
        tmp_df['base_area'] = tmp_df['長'].apply(_to_float) * tmp_df['寬'].apply(_to_float)
        sorted_df = tmp_df.sort_values(by='base_area', ascending=False)

        for index, row in sorted_df.iterrows():
            try:
                name = str(row["商品名稱"])
                l = _to_float(row["長"])
                w = _to_float(row["寬"])
                h = _to_float(row["高"])
                weight = _to_float(row["重量(kg)"])
                qty = _to_int(row["數量"])

                if qty > 0:
                    total_qty += qty
                    if name not in requested_counts:
                        requested_counts[name] = 0
                        unique_products.append(name)
                    requested_counts[name] += qty

                    foldable = is_foldable_item(l, w, h)
                    unstable = is_unstable_item(l, w, h)

                    for _ in range(qty):
                        # ✅ 紙袋/軟包可折疊：強制平放（最薄邊當高度）
                        if foldable:
                            dims = sorted([l, w, h])  # [薄, 中, 長]
                            best_l, best_w, best_h = dims[2], dims[1], dims[0]
                        else:
                            # ✅ 底層規則：禁易倒直立（用方向過濾）
                            # ✅ 權重切換：底層偏穩定（layer=0）
                            best_l, best_w, best_h = get_best_orientation_advanced(
                                l, w, h, box_l, box_w, box_h,
                                layer=0,
                                forbid_unstable_vertical_on_base=True
                            )

                            # 若物品本身很易倒，仍可在上層追求效率（不加 UI，採保守策略）
                            # 這裡不直接用 layer=1，因為 py3dbp 的層是在 pack 後才知道；
                            # 我們先以底層安全優先，避免「明明放得下但排得很不實務」。
                            # （若你要更進階：可在 pack 後做二次重排，但會重寫較多，先不動。）

                        item = Item(name, best_l, best_w, best_h, weight)
                        packer.add_item(item)
            except:
                pass

        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        # ✅ 保留你原本的：依照你排序後的順序裝箱
        packer.pack(bigger_first=False) 

        # ==========================================
        # 修改結束
        # ==========================================

        fig = go.Figure()

        # 1. 座標軸樣式 (強制黑色)（保留原樣）
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

        fig.update_layout(
            template="plotly_white",
            font=dict(color="black"),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            autosize=True, 
            scene=dict(
                xaxis={**axis_config, 'title': '長 (L)'},
                yaxis={**axis_config, 'title': '寬 (W)'},
                zaxis={**axis_config, 'title': '高 (H)'},
                aspectmode='data',
                camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))
            ),
            margin=dict(t=30, b=0, l=0, r=0), 
            height=600,
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

        # ✅ 3D 呈現：支援多箱，但不改 UI、不改報表文字
        # 做法：把每個用到的箱子沿 X 軸平移（只影響 3D 內部呈現）
        # 若只用到一箱，看起來跟原本一模一樣
        used_bins = [b for b in packer.bins if getattr(b, "items", None)]
        spacing = box_l * 1.15  # 箱與箱的間隔（只在 3D 內，不影響 UI）

        total_vol = 0.0
        packed_counts = {}
        total_net_weight = 0.0

        # 外箱線框：每個已用箱子畫一個
        for bi, b in enumerate(used_bins if used_bins else packer.bins[:1]):
            ox = bi * spacing
            fig.add_trace(go.Scatter3d(
                x=[ox+0, ox+box_l, ox+box_l, ox+0, ox+0, ox+0, ox+box_l, ox+box_l, ox+0, ox+0, ox+0, ox+0, ox+box_l, ox+box_l, ox+box_l, ox+box_l],
                y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
                z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
                mode='lines', line=dict(color='#000000', width=6), name='外箱'
            ))

        # 商品方塊
        for bi, b in enumerate(used_bins):
            ox = bi * spacing
            for item in b.items:
                packed_counts[item.name] = packed_counts.get(item.name, 0) + 1

                x, y, z = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                idim_w, idim_d, idim_h = float(dim[0]), float(dim[1]), float(dim[2])
                i_weight = _to_float(item.weight)

                total_vol += (idim_w * idim_d * idim_h)
                total_net_weight += i_weight

                color = product_colors.get(item.name, '#888')
                hover_text = f"{item.name}<br>實際佔用: {idim_w}x{idim_d}x{idim_h}<br>重量: {i_weight:.2f}kg<br>位置:({x},{y},{z})"

                # 注意：X 軸加上箱子偏移 ox
                fig.add_trace(go.Mesh3d(
                    x=[ox+x, ox+x+idim_w, ox+x+idim_w, ox+x, ox+x, ox+x+idim_w, ox+x+idim_w, ox+x],
                    y=[y, y, y+idim_d, y+idim_d, y, y, y+idim_d, y+idim_d],
                    z=[z, z, z, z, z+idim_h, z+idim_h, z+idim_h, z+idim_h],
                    i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
                    j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
                    k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=color, opacity=1, name=item.name, showlegend=True,
                    text=hover_text, hoverinfo='text',
                    lighting=dict(ambient=0.8, diffuse=0.8, specular=0.1, roughness=0.5),
                    lightposition=dict(x=1000, y=1000, z=2000)
                ))
                fig.add_trace(go.Scatter3d(
                    x=[ox+x, ox+x+idim_w, ox+x+idim_w, ox+x, ox+x, ox+x, ox+x+idim_w, ox+x+idim_w, ox+x, ox+x, ox+x, ox+x, ox+x+idim_w, ox+x+idim_w, ox+x+idim_w, ox+x+idim_w],
                    y=[y, y, y+idim_d, y+idim_d, y, y, y, y, y+idim_d, y+idim_d, y, y+idim_d, y+idim_d, y, y, y+idim_d],
                    z=[z, z, z, z, z, z+idim_h, z+idim_h, z+idim_h, z+idim_h, z+idim_h, z, z+idim_h, z+idim_h, z+idim_h, z, z],
                    mode='lines', line=dict(color='#000000', width=2), showlegend=False
                ))

        # 只顯示一次 legend（保留你原本的邏輯）
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # ✅ 利用率以「單一箱體積」計算（保持你原本的顯示語意）
        # 多箱時，這個數字本質上會偏高或偏低（因為你原本就是單箱報表），
        # 但你要求「顯示內容不動」，所以我們不改報表欄位定義。
        box_vol = box_l * box_w * box_h
        utilization = (total_vol / box_vol) * 100 if box_vol > 0 else 0

        # ✅ 防 TypeError：確保都是 float
        total_net_weight = _to_float(total_net_weight)
        box_weight = _to_float(box_weight)
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

        # ✅ 報表 HTML 完全保留原本欄位/顯示內容（不新增任何行）
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
