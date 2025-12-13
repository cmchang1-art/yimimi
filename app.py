import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import datetime
from itertools import permutations
import math

# ==========================
# 安全轉型（避免 TypeError）
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

# ==========================
# 彎折選項（表格欄位）
# ==========================
FOLD_NONE = "否"
FOLD_90 = "90度彎"
FOLD_HALF = "可對折"

# ==========================
# 「人類」方向判斷：以最大可放件數為優先
# 這會解決：明明直放可放2盒，卻只平放1盒的問題
# ==========================
def best_orientation_by_capacity(l, w, h, box_l, box_w, box_h):
    """
    在所有旋轉中，找：
    1) 箱內可容納數量最大（floor(L/dl)*floor(W/dw)*floor(H/dh)）
    2) 若同量，優先高度較低（更好堆疊）
    3) 再同量，優先底面較小（更容易拼版）
    """
    best = None
    best_key = None

    for dl, dw, dh in set(permutations([l, w, h], 3)):
        if dl <= 0 or dw <= 0 or dh <= 0:
            continue
        if dl <= box_l and dw <= box_w and dh <= box_h:
            nx = int(box_l // dl)
            ny = int(box_w // dw)
            nz = int(box_h // dh)
            count = nx * ny * nz

            # key 越大越好：count 最大；dh 越小越好；base 越小越好
            key = (count, -dh, -(dl * dw))

            if best is None or key > best_key:
                best = (dl, dw, dh)
                best_key = key

    return best if best is not None else (l, w, h)

# ==========================
# 彎折模型（修正：不再變成「巨大盒子」）
# 目標：讓薄片/紙袋能以「薄邊靠牆」方式存在
# ==========================
def fold_candidates(l, w, h, fold_type):
    l = _to_float(l); w = _to_float(w); h = _to_float(h)
    l = max(l, 0.0); w = max(w, 0.0); h = max(h, 0.0)

    # 無彎折：就原尺寸
    if fold_type == FOLD_NONE:
        return [(l, w, h)]

    # 可對折：允許沿「長」或「寬」對折（實務上紙袋/薄片常這樣）
    # 對折後：被折那一邊/2，厚度*2（厚度用原本最薄邊 h 近似）
    if fold_type == FOLD_HALF:
        t = min(l, w, h)  # 當作厚度
        # 沿長對折 / 沿寬對折（兩種候選，讓系統選更能塞的）
        return [
            (l / 2.0, w, t * 2.0),
            (l, w / 2.0, t * 2.0),
        ]

    # 90度彎：把薄片「立起來貼牆」，等效為：一個面變成厚度，另一面變成高度
    # 你要的效果是：不要變大盒子、要能靠牆塞邊
    # 所以候選給： (長, 厚, 寬) 或 (寬, 厚, 長)
    if fold_type == FOLD_90:
        t = min(l, w, h)  # 厚度
        a = max(l, w)     # 長邊
        b = min(l, w)     # 短邊
        return [
            (a, t, b),
            (b, t, a),
        ]

    return [(l, w, h)]

# ==========================
# 逐箱裝箱（關鍵：不再一次丟很多箱讓它亂分散）
# ==========================
def pack_sequential(items, box_l, box_w, box_h, max_weight_limit=999999, max_boxes=50):
    remaining = list(items)
    packed_bins = []

    for bi in range(max_boxes):
        if not remaining:
            break

        packer = Packer()
        box = Bin(f"Box_{bi+1}", box_l, box_w, box_h, max_weight_limit)
        packer.add_bin(box)

        for it in remaining:
            packer.add_item(it)

        # 嘗試用 fix_point 讓東西更貼牆貼角（不同版本參數可能不同，做相容）
        packed = False
        for kwargs in [
            dict(bigger_first=False, fix_point=True),
            dict(bigger_first=False),
        ]:
            try:
                packer.pack(**kwargs)
                packed = True
                break
            except TypeError:
                continue

        if not packed:
            packer.pack()

        packed_bins.append(packer.bins[0])
        remaining = list(getattr(packer, "unfit_items", [])) or []

        # 如果這箱一個都裝不進去，直接停止避免無限分箱
        if len(packer.bins[0].items) == 0:
            break

    return [b for b in packed_bins if getattr(b, "items", None)], remaining

# ==========================
# 頁面設定（完全保留你原檔）
# ==========================
st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="collapsed")

# ==========================
# CSS（完全保留你原檔，不改顏色/布局）
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
# 上半部：輸入區域（保留原樣）
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
                {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5, "彎折": "否"},
                {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5, "彎折": "可對折"},
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
            "彎折": st.column_config.SelectboxColumn(
                "彎折",
                options=[FOLD_NONE, FOLD_90, FOLD_HALF],
                help="否 / 90度彎 / 可對折"
            ),
        }
    )

st.markdown("---")

b1, b2, b3 = st.columns([1, 2, 1])
with b2:
    run_button = st.button("🚀 開始計算與 3D 模擬", type="primary", use_container_width=True)

# ==========================
# 下半部：運算邏輯與結果（只改演算法）
# ==========================
if run_button:
    with st.spinner('正在進行智慧裝箱運算...'):
        # 乾淨副本（避免污染顯示）
        tmp = edited_df.copy()
        if "彎折" not in tmp.columns:
            tmp["彎折"] = FOLD_NONE

        # 安全轉型
        tmp["長"] = tmp["長"].apply(_to_float)
        tmp["寬"] = tmp["寬"].apply(_to_float)
        tmp["高"] = tmp["高"].apply(_to_float)
        tmp["重量(kg)"] = tmp["重量(kg)"].apply(_to_float)
        tmp["數量"] = tmp["數量"].apply(_to_int)

        # 更像人類：先放底面大的/薄的（鋪底），再放盒子
        tmp["base_area"] = tmp["長"] * tmp["寬"]
        tmp["volume"] = tmp["長"] * tmp["寬"] * tmp["高"]
        sorted_df = tmp.sort_values(by=["base_area", "volume"], ascending=[False, False])

        requested_counts = {}
        unique_products = []
        total_qty = 0
        total_net_weight = 0.0

        # 建立精準 items（完全照數量，不幻想）
        items_all = []
        for _, row in sorted_df.iterrows():
            name = str(row.get("商品名稱", "")).strip()
            if not name:
                continue

            l = _to_float(row.get("長", 0))
            w = _to_float(row.get("寬", 0))
            h = _to_float(row.get("高", 0))
            weight = _to_float(row.get("重量(kg)", 0))
            qty = _to_int(row.get("數量", 0))
            fold = str(row.get("彎折", FOLD_NONE)).strip() or FOLD_NONE

            if qty <= 0:
                continue

            total_qty += qty
            requested_counts[name] = requested_counts.get(name, 0) + qty
            if name not in unique_products:
                unique_products.append(name)

            # 先產生彎折候選尺寸 -> 每個候選再算最強方向（容量最大）
            cand_dims = fold_candidates(l, w, h, fold)

            # 先挑出「在箱內能容納件數最大」的那個候選（再用同一候選去建立 items）
            best_overall = None
            best_key = None

            for cl, cw, ch in cand_dims:
                dl, dw, dh = best_orientation_by_capacity(cl, cw, ch, box_l, box_w, box_h)
                nx = int(box_l // dl) if dl > 0 else 0
                ny = int(box_w // dw) if dw > 0 else 0
                nz = int(box_h // dh) if dh > 0 else 0
                count = nx * ny * nz
                key = (count, -dh, -(dl * dw))
                if best_overall is None or key > best_key:
                    best_overall = (dl, dw, dh)
                    best_key = key

            best_l, best_w, best_h = best_overall if best_overall else (l, w, h)

            for _i in range(qty):
                items_all.append(Item(name, best_l, best_w, best_h, weight))

        # 逐箱裝箱（才會真正分箱）
        packed_bins, unfit_items = pack_sequential(items_all, box_l, box_w, box_h, max_boxes=50)

        # 顏色
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        # 3D
        fig = go.Figure()
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

        used_bins = packed_bins if packed_bins else []
        spacing = box_l * 1.15

        packed_counts = {}
        total_vol = 0.0
        total_net_weight = 0.0

        # 畫外箱（只畫實際用到的箱子，不會亂出現一排）
        for bi, _b in enumerate(used_bins):
            ox = bi * spacing
            fig.add_trace(go.Scatter3d(
                x=[ox+0, ox+box_l, ox+box_l, ox+0, ox+0, ox+0, ox+box_l, ox+box_l, ox+0, ox+0, ox+0, ox+0, ox+box_l, ox+box_l, ox+box_l, ox+box_l],
                y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
                z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
                mode='lines', line=dict(color='#000000', width=6), name='外箱'
            ))

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

        # legend 去重
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # 報表（維持你原本欄位/文字）
        used_box_count = max(1, len(used_bins))
        box_vol = box_l * box_w * box_h
        total_box_vol = box_vol * used_box_count
        utilization = (total_vol / total_box_vol) * 100 if total_box_vol > 0 else 0.0

        gross_weight = _to_float(total_net_weight) + _to_float(box_weight) * used_box_count

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
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">⚖️ 內容淨重:</td><td>{_to_float(total_net_weight):.2f} kg</td></tr>
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
