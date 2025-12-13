import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item  # 保留原 import（但本版演算法不依賴 py3dbp）
import plotly.graph_objects as go
import datetime
import copy
import math
from itertools import permutations

# ==========================
# 安全轉型
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
# 彎折選項
# ==========================
FOLD_NONE = "否"
FOLD_90 = "90度彎"
FOLD_HALF = "可對折"

def _thickness(l, w, h):
    vals = [v for v in [l, w, h] if v and v > 0]
    return min(vals) if vals else 0.0

def fold_orientations(name, l, w, h, fold_type, box_l, box_w, box_h):
    """
    回傳允許的 orientations（dx,dy,dz），並且：
    - 90度彎：強制「直立」（dz 取大邊），不允許攤平
    - 可對折：提供「薄片平放」+「薄片立放靠牆」兩種，讓系統選更省空間的
    - 否：6 旋轉
    """
    l = max(_to_float(l), 0.0)
    w = max(_to_float(w), 0.0)
    h = max(_to_float(h), 0.0)
    if l <= 0 or w <= 0 or h <= 0:
        return []

    t = _thickness(l, w, h)
    a = max(l, w)
    b = min(l, w)

    oris = []

    if fold_type == FOLD_90:
        # 90度彎：視為「薄邊貼牆」的直立板
        # 高度 dz = a（大邊）
        # 底面為 (t, b) 或 (b, t)
        candidates = [
            (t, b, a),
            (b, t, a),
        ]
        # 強制直立：不允許 dz = t 之類的攤平
        for dx, dy, dz in candidates:
            if dx <= box_l and dy <= box_w and dz <= box_h:
                oris.append((dx, dy, dz))
        return oris

    if fold_type == FOLD_HALF:
        # 對折：厚度變 2t，長或寬變一半
        # 先給「平放薄片」：dz 小
        flat_candidates = [
            (l / 2.0, w, 2.0 * t),
            (l, w / 2.0, 2.0 * t),
        ]
        # 再給「立放靠牆」：讓薄片像文件夾一樣立起來貼牆（底面小）
        # 立放：dz 取較大平面邊，底面取(2t, 另一邊)
        stand_candidates = []
        for fx, fy, fz in flat_candidates:
            # 以折完後的平面 (fx,fy) 來做立放
            big = max(fx, fy)
            small = min(fx, fy)
            stand_candidates += [
                (2.0 * t, small, big),
                (small, 2.0 * t, big),
            ]

        candidates = flat_candidates + stand_candidates
        for dx, dy, dz in candidates:
            if dx <= box_l and dy <= box_w and dz <= box_h:
                oris.append((dx, dy, dz))
        # 去重
        oris = list({(round(x,6), round(y,6), round(z,6)) for x,y,z in oris})
        return [(x,y,z) for x,y,z in oris]

    # fold none：六種旋轉
    for dx, dy, dz in set(permutations([l, w, h], 3)):
        if dx <= box_l and dy <= box_w and dz <= box_h:
            oris.append((dx, dy, dz))
    return oris

# ==========================
# 碰撞檢查
# ==========================
def _collide(a, b):
    return not (
        a["x"] + a["dx"] <= b["x"] or
        b["x"] + b["dx"] <= a["x"] or
        a["y"] + a["dy"] <= b["y"] or
        b["y"] + b["dy"] <= a["y"] or
        a["z"] + a["dz"] <= b["z"] or
        b["z"] + b["dz"] <= a["z"]
    )

def _inside_box(x, y, z, dx, dy, dz, box_l, box_w, box_h):
    return (x >= 0 and y >= 0 and z >= 0 and
            x + dx <= box_l and y + dy <= box_w and z + dz <= box_h)

def _point_is_covered(px, py, pz, placed):
    # 點若落在已放置的盒子內，視為無效點
    for b in placed:
        if (b["x"] <= px < b["x"] + b["dx"] and
            b["y"] <= py < b["y"] + b["dy"] and
            b["z"] <= pz < b["z"] + b["dz"]):
            return True
    return False

# ==========================
# 人類式靠牆裝箱：Extreme-Points / Corner-first
# - 一律從 (0,0,0) 角落開始塞
# - 先找最低 z，再找最低 y，再找最低 x（像人類靠牆排）
# - 90度彎：只允許直立 orientations（上面已限制）
# - 對折：提供立放/平放，並用評分挑最省空間
# ==========================
def pack_one_bin(items, box_l, box_w, box_h):
    placed = []
    points = {(0.0, 0.0, 0.0)}

    def score_candidate(x, y, z, dx, dy, dz):
        # 目標：越靠牆越好（x,y,z 小），同時底面積越小越好（不擋路），高度也不要亂爆
        base = dx * dy
        return (z, y, x, base, dz)

    for it in items:
        best = None
        best_s = None

        # points 由「更像人類」順序排序：z→y→x
        pts = sorted(points, key=lambda p: (p[2], p[1], p[0]))

        for (px, py, pz) in pts:
            # 已被覆蓋的點不試
            if _point_is_covered(px, py, pz, placed):
                continue

            for (dx, dy, dz) in it["oris"]:
                if not _inside_box(px, py, pz, dx, dy, dz, box_l, box_w, box_h):
                    continue

                cand_box = {"x": px, "y": py, "z": pz, "dx": dx, "dy": dy, "dz": dz}
                if any(_collide(cand_box, p) for p in placed):
                    continue

                s = score_candidate(px, py, pz, dx, dy, dz)
                if best is None or s < best_s:
                    best = cand_box
                    best_s = s

            # 這個點若能放到，通常就是最靠牆的解；可提早 break 但會少一些最佳化
            # 這裡保守不 break，避免錯過更小底面積的 orientation

        if best is None:
            # 這個 item 放不進本箱
            it["placed"] = False
            continue

        # 放置成功
        it["placed"] = True
        it["x"], it["y"], it["z"] = best["x"], best["y"], best["z"]
        it["dx"], it["dy"], it["dz"] = best["dx"], best["dy"], best["dz"]

        placed.append({
            "name": it["name"],
            "x": it["x"], "y": it["y"], "z": it["z"],
            "dx": it["dx"], "dy": it["dy"], "dz": it["dz"],
            "weight": it["weight"]
        })

        # 新極點：沿 x、y、z 推出 3 個點（經典 extreme points）
        new_pts = [
            (it["x"] + it["dx"], it["y"], it["z"]),
            (it["x"], it["y"] + it["dy"], it["z"]),
            (it["x"], it["y"], it["z"] + it["dz"]),
        ]
        for np in new_pts:
            nx, ny, nz = np
            if nx <= box_l and ny <= box_w and nz <= box_h:
                points.add((float(nx), float(ny), float(nz)))

        # 修剪 points：移除落在盒子內的點（減少亂塞中間）
        points = {p for p in points if not _point_is_covered(p[0], p[1], p[2], placed)}

    return placed

def pack_multi_bins(items, box_l, box_w, box_h, max_bins=50):
    remaining = items[:]
    bins = []
    for _ in range(max_bins):
        if not remaining:
            break

        # 嘗試在本箱放置
        placed = pack_one_bin(remaining, box_l, box_w, box_h)

        if not placed:
            # 一個都放不進就停止（避免無限開箱）
            break

        bins.append(placed)

        # 更新 remaining（沒被放進去的）
        still = []
        placed_count = 0
        for it in remaining:
            if it.get("placed"):
                placed_count += 1
                # 清除旗標，避免下一箱誤判
                it.pop("placed", None)
            else:
                still.append(it)
                it.pop("placed", None)
        remaining = still

    return bins, remaining

# ==========================
# 頁面設定（保留你原檔）
# ==========================
st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="collapsed")

# ==========================
# CSS：完全保留你原檔（不改顏色/布局）
# ==========================
st.markdown("""
<style>
    .stApp {
        background-color: #ffffff !important;
        color: #000000 !important;
    }
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="stSidebarCollapsedControl"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    .stDeployButton { display: none !important; }
    footer { display: none !important; }
    #MainMenu { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stHeader"] { background-color: transparent !important; pointer-events: none; }

    div[data-baseweb="input"] input,
    div[data-baseweb="select"] div,
    .stDataFrame, .stTable {
        color: #000000 !important;
        background-color: #f9f9f9 !important;
        border-color: #cccccc !important;
    }

    .section-header {
        font-size: 1.2rem;
        font-weight: bold;
        color: #333;
        margin-top: 10px;
        margin-bottom: 5px;
        border-left: 5px solid #FF4B4B;
        padding-left: 10px;
    }

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

    .js-plotly-plot .plotly .bg { fill: #ffffff !important; }
    .xtick text, .ytick text, .ztick text {
        fill: #000000 !important;
        font-weight: bold !important;
    }

    .block-container {
        padding-top: 2rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統")
st.markdown("---")

# ==========================
# 上半部：輸入區域（保留你原檔）
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
            ),
        }
    )

st.markdown("---")

b1, b2, b3 = st.columns([1, 2, 1])
with b2:
    run_button = st.button("🚀 開始計算與 3D 模擬", type="primary", use_container_width=True)

# ==========================
# 下半部：裝箱結果與模擬
# ==========================
if run_button:
    with st.spinner('正在進行智慧裝箱運算...'):

        df = edited_df.copy()
        if "彎折" not in df.columns:
            df["彎折"] = FOLD_NONE

        # 清洗
        df["長"] = df["長"].apply(_to_float)
        df["寬"] = df["寬"].apply(_to_float)
        df["高"] = df["高"].apply(_to_float)
        df["重量(kg)"] = df["重量(kg)"].apply(_to_float)
        df["數量"] = df["數量"].apply(_to_int)
        df["彎折"] = df["彎折"].fillna(FOLD_NONE).astype(str)

        # 保留你原本的排序精神：底面積大先（紙袋先鋪/靠邊）
        df["base_area"] = df["長"] * df["寬"]
        df["volume"] = df["長"] * df["寬"] * df["高"]
        df = df.sort_values(by=["base_area", "volume"], ascending=[False, False])

        # 建立精準 items（完全依照數量，不幻想）
        items = []
        requested_counts = {}
        unique_products = []
        total_qty = 0

        for _, r in df.iterrows():
            name = str(r.get("商品名稱", "")).strip()
            if not name:
                continue
            l, w, h = r["長"], r["寬"], r["高"]
            weight = r["重量(kg)"]
            qty = r["數量"]
            fold = r["彎折"].strip() if r["彎折"] else FOLD_NONE

            if qty <= 0:
                continue

            requested_counts[name] = requested_counts.get(name, 0) + qty
            if name not in unique_products:
                unique_products.append(name)

            total_qty += qty

            oris = fold_orientations(name, l, w, h, fold, box_l, box_w, box_h)
            if not oris:
                # 任何姿態都不可能進箱 -> 直接都當作 unfit
                for _ in range(qty):
                    items.append({"name": name, "oris": [], "weight": weight})
                continue

            for _ in range(qty):
                items.append({"name": name, "oris": oris, "weight": weight})

        # 多箱逐箱裝（箱1裝不下的才進箱2）
        bins, remaining = pack_multi_bins(items, box_l, box_w, box_h, max_bins=50)

        # 統計
        packed_counts = {}
        total_vol = 0.0
        total_net_weight = 0.0

        for b in bins:
            for it in b:
                packed_counts[it["name"]] = packed_counts.get(it["name"], 0) + 1
                total_vol += (it["dx"] * it["dy"] * it["dz"])
                total_net_weight += it["weight"]

        used_box_count = max(1, len(bins)) if bins else 1

        # 空間利用率：以實際用到的箱數計算
        box_vol = box_l * box_w * box_h
        utilization = (total_vol / (box_vol * used_box_count)) * 100 if box_vol > 0 else 0.0

        gross_weight = float(total_net_weight) + float(box_weight) * used_box_count

        # 報表狀態
        all_fitted = True
        missing_items_html = ""
        for name, req_qty in requested_counts.items():
            real_qty = packed_counts.get(name, 0)
            if real_qty < req_qty:
                all_fitted = False
                diff = req_qty - real_qty
                missing_items_html += f"<li style='color: #D8000C; background-color: #FFD2D2; padding: 8px; margin: 5px 0; border-radius: 4px; font-weight: bold;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status_html = "<h3 style='color: #155724; background-color: #d4edda; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #c3e6cb;'>✅ 完美！所有商品皆已裝入。</h3>" if all_fitted else f"<h3 style='color: #721c24; background-color: #f8d7da; padding: 10px; border-radius: 8px; border: 1px solid #f5c6cb;'>❌ 注意：有部分商品裝不下！</h3><ul style='padding-left: 20px;'>{missing_items_html}</ul>"

        # 時間
        tw_time = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        now_str = tw_time.strftime("%Y-%m-%d %H:%M")
        file_time_str = tw_time.strftime("%Y%m%d_%H%M")

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

        # ==========================
        # 3D 繪圖：支援多箱（箱2會顯示）
        # ==========================
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

        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        # 多箱在 x 方向平移顯示
        spacing = box_l * 1.25

        def draw_box(offset_x, label="外箱"):
            fig.add_trace(go.Scatter3d(
                x=[offset_x+0, offset_x+box_l, offset_x+box_l, offset_x+0, offset_x+0, offset_x+0, offset_x+box_l, offset_x+box_l, offset_x+0, offset_x+0, offset_x+0, offset_x+0, offset_x+box_l, offset_x+box_l, offset_x+box_l, offset_x+box_l],
                y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
                z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
                mode='lines', line=dict(color='#000000', width=6), name=label
            ))

        if not bins:
            # 至少畫一個空箱
            draw_box(0, "外箱")
        else:
            for bi, b in enumerate(bins):
                ox = bi * spacing
                draw_box(ox, "外箱" if bi == 0 else f"外箱_{bi+1}")

                for it in b:
                    name = it["name"]
                    color = product_colors.get(name, "#888")
                    x, y, z = it["x"], it["y"], it["z"]
                    dx, dy, dz = it["dx"], it["dy"], it["dz"]
                    wgt = it["weight"]

                    hover_text = f"{name}<br>實際佔用: {dx}x{dy}x{dz}<br>重量: {wgt:.2f}kg<br>位置:({x},{y},{z})<br>箱: {bi+1}"

                    fig.add_trace(go.Mesh3d(
                        x=[ox+x, ox+x+dx, ox+x+dx, ox+x, ox+x, ox+x+dx, ox+x+dx, ox+x],
                        y=[y, y, y+dy, y+dy, y, y, y+dy, y+dy],
                        z=[z, z, z, z, z+dz, z+dz, z+dz, z+dz],
                        i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
                        j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
                        k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                        color=color, opacity=1, name=name, showlegend=True,
                        text=hover_text, hoverinfo='text',
                        lighting=dict(ambient=0.8, diffuse=0.8, specular=0.1, roughness=0.5),
                        lightposition=dict(x=1000, y=1000, z=2000)
                    ))

                    fig.add_trace(go.Scatter3d(
                        x=[ox+x, ox+x+dx, ox+x+dx, ox+x, ox+x, ox+x, ox+x+dx, ox+x+dx, ox+x, ox+x, ox+x, ox+x, ox+x+dx, ox+x+dx, ox+x+dx, ox+x+dx],
                        y=[y, y, y+dy, y+dy, y, y, y, y, y+dy, y+dy, y, y+dy, y+dy, y, y, y+dy],
                        z=[z, z, z, z, z, z+dz, z+dz, z+dz, z+dz, z+dz, z, z+dz, z+dz, z+dz, z, z],
                        mode='lines', line=dict(color='#000000', width=2), showlegend=False
                    ))

        # legend 去重（保留你原本做法）
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # 下載報告（保留你原本格式）
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
