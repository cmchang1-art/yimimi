import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import datetime
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
# 彎折欄位（只新增這欄）
# ==========================
FOLD_NONE = "否"
FOLD_90 = "90度彎"
FOLD_HALF = "可對折"

def fold_candidates(l, w, h, fold_type):
    """回傳可能的「折完後等效長方體」候選尺寸（不會變成超大盒）"""
    l = max(_to_float(l), 0.0)
    w = max(_to_float(w), 0.0)
    h = max(_to_float(h), 0.0)

    if fold_type == FOLD_NONE:
        return [(l, w, h)]

    t = min([d for d in (l, w, h) if d > 0] or [0.0])  # 厚度（薄片用）
    if t <= 0:
        return [(l, w, h)]

    if fold_type == FOLD_HALF:
        # 沿長對折 / 沿寬對折
        return [
            (l / 2.0, w, t * 2.0),
            (l, w / 2.0, t * 2.0),
        ]

    if fold_type == FOLD_90:
        # 90 度彎：等效為「薄邊貼牆」的 L 型包圍盒近似：把厚度當成其中一邊
        # (max(l,w), t, min(l,w)) 與 (min(l,w), t, max(l,w)) 兩種
        a = max(l, w)
        b = min(l, w)
        return [
            (a, t, b),
            (b, t, a),
        ]

    return [(l, w, h)]

# ==========================
# 方向挑選：以「箱內可容納件數最大」為優先（你要的直放/橫放省空間）
# ==========================
def best_orientation_by_capacity(dims, box_l, box_w, box_h, prefer_mode=None):
    """
    dims: (l,w,h)
    prefer_mode: None / 0 / 1 / 2
      - None：純容量最大
      - 0：偏平放
      - 1：偏側放
      - 2：偏直立
    """
    l, w, h = dims
    candidates = list(set(permutations([l, w, h], 3)))

    def capacity_key(dl, dw, dh):
        if dl <= 0 or dw <= 0 or dh <= 0:
            return (-1, 0, 0, 0)
        if dl > box_l or dw > box_w or dh > box_h:
            return (-1, 0, 0, 0)

        nx = int(box_l // dl)
        ny = int(box_w // dw)
        nz = int(box_h // dh)
        count = nx * ny * nz

        # tie-break：高度低、底面小（更好拼版）
        base = dl * dw
        key = (count, -dh, -base)

        # 模式偏好：只當作微弱加權（不會犧牲容量最大）
        if prefer_mode is not None:
            # 模式0：偏平放（dh 越接近原 h 越好）
            if prefer_mode == 0:
                key = (count, -abs(dh - h), -dh, -base)
            # 模式1：偏側放（dw 越接近原 h 越好）
            elif prefer_mode == 1:
                key = (count, -abs(dw - h), -dh, -base)
            # 模式2：偏直立（dl 越接近原 h 越好）
            elif prefer_mode == 2:
                key = (count, -abs(dl - h), -dh, -base)

        return key

    best = None
    best_k = None
    for dl, dw, dh in candidates:
        k = capacity_key(dl, dw, dh)
        if best is None or k > best_k:
            best = (dl, dw, dh)
            best_k = k

    return best if best is not None else (l, w, h)

# ==========================
# 視覺貼牆壓縮（只影響 3D 顯示，不改 packer 判斷）
# ==========================
def compact_positions(items, box_l, box_w, box_h):
    """
    items: list of dict {name, x,y,z, dx,dy,dz, weight}
    回傳新 items（盡量往 (0,0,0) 方向貼牆、貼已放物）
    """
    def collide(a, b):
        return not (
            a["x"] + a["dx"] <= b["x"] or
            b["x"] + b["dx"] <= a["x"] or
            a["y"] + a["dy"] <= b["y"] or
            b["y"] + b["dy"] <= a["y"] or
            a["z"] + a["dz"] <= b["z"] or
            b["z"] + b["dz"] <= a["z"]
        )

    placed = []
    # 先按 z,y,x 排序（更像人類從底到上、從角落開始）
    items_sorted = sorted(items, key=lambda t: (t["z"], t["y"], t["x"]))

    for it in items_sorted:
        cur = dict(it)

        # 往 X 貼牆
        target_x = 0.0
        while True:
            moved = dict(cur)
            moved["x"] = target_x
            if moved["x"] < 0 or moved["x"] + moved["dx"] > box_l:
                break
            if any(collide(moved, p) for p in placed):
                break
            cur = moved
            break

        # 往 Y 貼牆
        target_y = 0.0
        while True:
            moved = dict(cur)
            moved["y"] = target_y
            if moved["y"] < 0 or moved["y"] + moved["dy"] > box_w:
                break
            if any(collide(moved, p) for p in placed):
                break
            cur = moved
            break

        # 往 Z 貼底
        target_z = 0.0
        while True:
            moved = dict(cur)
            moved["z"] = target_z
            if moved["z"] < 0 or moved["z"] + moved["dz"] > box_h:
                break
            if any(collide(moved, p) for p in placed):
                break
            cur = moved
            break

        placed.append(cur)

    return placed

# ==========================
# 頁面設定（保留你原檔）
# ==========================
st.set_page_config(layout="wide", page_title="3D裝箱系統", initial_sidebar_state="collapsed")

# ==========================
# CSS：強制介面修復（保留你原檔）
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
# 核心：多策略嘗試（學 Gemini 那種「能裝下就先贏」的穩健作法）
# ==========================
def build_items(df, prefer_mode=None):
    """
    依照每列商品 + 彎折候選，為該商品選擇「箱內可容納件數最大」的方向，
    然後建立精確 qty 個 Item。
    """
    items = []
    requested_counts = {}
    unique_products = []
    total_qty = 0

    # 保留你原本的「底面積大先放」精神（紙袋先），但加上 volume tie-break
    df2 = df.copy()
    df2["長"] = df2["長"].apply(_to_float)
    df2["寬"] = df2["寬"].apply(_to_float)
    df2["高"] = df2["高"].apply(_to_float)
    df2["重量(kg)"] = df2["重量(kg)"].apply(_to_float)
    df2["數量"] = df2["數量"].apply(_to_int)
    if "彎折" not in df2.columns:
        df2["彎折"] = FOLD_NONE

    df2["base_area"] = df2["長"] * df2["寬"]
    df2["volume"] = df2["長"] * df2["寬"] * df2["高"]
    df2 = df2.sort_values(by=["base_area", "volume"], ascending=[False, False])

    for _, row in df2.iterrows():
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

        # 扁平物（紙袋）判斷：高度遠小於長寬 -> 讓它更容易被當作薄片處理
        is_flat_item = (h > 0 and l > 0 and w > 0 and (h < l * 0.2) and (h < w * 0.2))

        # 取得折疊候選
        cand = fold_candidates(l, w, h, fold)

        # 在候選中挑一個「最佳（容量最大）」的方向（mode 只是偏好，不會犧牲容量）
        best_dims = None
        best_key = None
        for dims in cand:
            # 扁平物：優先保持薄片姿態（但仍用容量最大挑方向）
            chosen = best_orientation_by_capacity(dims, box_l, box_w, box_h, prefer_mode if not is_flat_item else 0)
            dl, dw, dh = chosen
            nx = int(box_l // dl) if dl > 0 else 0
            ny = int(box_w // dw) if dw > 0 else 0
            nz = int(box_h // dh) if dh > 0 else 0
            count = nx * ny * nz
            key = (count, -dh, -(dl * dw))
            if best_dims is None or key > best_key:
                best_dims = chosen
                best_key = key

        final_l, final_w, final_h = best_dims if best_dims else (l, w, h)

        for _i in range(qty):
            items.append(Item(name, final_l, final_w, final_h, weight))

    return items, requested_counts, unique_products, total_qty

def run_pack(items):
    p = Packer()
    b = Bin("StandardBox", box_l, box_w, box_h, 999999)
    p.add_bin(b)
    for it in items:
        p.add_item(it)

    # 嘗試 fix_point 讓它更貼角（不同版本 py3dbp 可能不支援，做相容）
    try:
        p.pack(bigger_first=False, fix_point=True)
    except TypeError:
        p.pack(bigger_first=False)

    fitted = sum(len(bx.items) for bx in p.bins)
    return p, fitted

# ==========================
# 下半部：運算與結果（顯示結構完全維持）
# ==========================
if run_button:
    with st.spinner('正在進行智慧裝箱運算...'):

        # 先準備 df（避免直接污染編輯表）
        df_work = edited_df.copy()
        if "彎折" not in df_work.columns:
            df_work["彎折"] = FOLD_NONE

        # 多策略：模擬 Gemini 那種「多嘗試，選最好」的穩健路線
        # - prefer_mode: None(純容量) / 0(偏平放) / 1(偏側放) / 2(偏直立)
        strategies = [None, 0, 1, 2]

        best_packer = None
        best_fitted = -1
        best_items_meta = None
        best_req = None
        best_unique = None
        best_total_qty = 0

        for mode in strategies:
            items, req_counts, unique_products, total_qty = build_items(df_work, prefer_mode=mode)
            packer, fitted = run_pack(items)

            if fitted > best_fitted:
                best_packer = packer
                best_fitted = fitted
                best_req = req_counts
                best_unique = unique_products
                best_total_qty = total_qty

            if best_fitted == total_qty:
                break

        packer = best_packer
        requested_counts = best_req or {}
        unique_products = best_unique or []
        total_qty = best_total_qty

        # ==============
        # 3D 繪圖（保留你原檔外觀，只改善貼牆視覺）
        # ==============
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

        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
            z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
            mode='lines', line=dict(color='#000000', width=6), name='外箱'
        ))

        # 顏色設定
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB', '#E67E22', '#1ABC9C']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        total_vol = 0.0
        total_net_weight = 0.0
        packed_counts = {}

        # 先取出 packer 的 items，做「視覺貼牆壓縮」
        raw_items = []
        for b in packer.bins:
            for it in b.items:
                x, y, z = float(it.position[0]), float(it.position[1]), float(it.position[2])
                dim = it.get_dimension()
                dx, dy, dz = float(dim[0]), float(dim[1]), float(dim[2])
                raw_items.append({
                    "name": it.name,
                    "x": x, "y": y, "z": z,
                    "dx": dx, "dy": dy, "dz": dz,
                    "weight": float(it.weight)
                })

        compacted = compact_positions(raw_items, box_l, box_w, box_h)

        # 畫出 compacted（更靠牆）
        for it in compacted:
            name = it["name"]
            packed_counts[name] = packed_counts.get(name, 0) + 1

            x, y, z = it["x"], it["y"], it["z"]
            dx, dy, dz = it["dx"], it["dy"], it["dz"]
            wgt = it["weight"]

            total_vol += (dx * dy * dz)
            total_net_weight += wgt

            color = product_colors.get(name, '#888')
            hover_text = f"{name}<br>實際佔用: {dx}x{dy}x{dz}<br>重量: {wgt:.2f}kg<br>位置:({x},{y},{z})"

            fig.add_trace(go.Mesh3d(
                x=[x, x+dx, x+dx, x, x, x+dx, x+dx, x],
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
                x=[x, x+dx, x+dx, x, x, x, x+dx, x+dx, x, x, x, x, x+dx, x+dx, x+dx, x+dx],
                y=[y, y, y+dy, y+dy, y, y, y, y, y+dy, y+dy, y, y+dy, y+dy, y, y, y+dy],
                z=[z, z, z, z, z, z+dz, z+dz, z+dz, z+dz, z+dz, z, z+dz, z+dz, z+dz, z, z],
                mode='lines', line=dict(color='#000000', width=2), showlegend=False
            ))

        # legend 去重（保留你原檔）
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))

        # 報表（保留你原檔欄位）
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
                missing_items_html += f"<li style='color: #D8000C; background-color: #FFD2D2; padding: 8px; margin: 5px 0; border-radius: 4px; font-weight: bold;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status_html = "<h3 style='color: #155724; background-color: #d4edda; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #c3e6cb;'>✅ 完美！所有商品皆已裝入。</h3>" if all_fitted else f"<h3 style='color: #721c24; background-color: #f8d7da; padding: 10px; border-radius: 8px; border: 1px solid #f5c6cb;'>❌ 注意：有部分商品裝不下！</h3><ul style='padding-left: 20px;'>{missing_items_html}</ul>"

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
