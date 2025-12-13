import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import datetime
from itertools import permutations

# ==========================
# 智慧判斷核心（只影響演算法）
# ==========================

def is_foldable_item(l, w, h):
    return min(l, w, h) <= 0.5

def is_unstable_item(l, w, h):
    base = max(l, w)
    return h > base * 1.5

def get_best_orientation_advanced(l, w, h, box_l, box_w, box_h, layer=0):
    candidates = []
    for dims in set(permutations([l, w, h], 3)):
        dl, dw, dh = dims
        if dl <= box_l and dw <= box_w and dh <= box_h:
            base_area = dl * dw
            height = dh

            stability = base_area
            efficiency = 1 / height if height > 0 else 0

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
# CSS
# ==========================
st.markdown("""
<style>
.stApp { background-color:#fff !important; color:#000 !important; }
[data-testid="stSidebar"], footer, #MainMenu { display:none !important; }
.section-header {
    font-size:1.2rem;font-weight:bold;border-left:5px solid #FF4B4B;
    padding-left:10px;margin:10px 0;
}
.report-card {
    padding:20px;border:2px solid #e0e0e0;border-radius:10px;
    background:#fff;box-shadow:0 4px 6px rgba(0,0,0,0.05);
}
</style>
""", unsafe_allow_html=True)

st.title("📦 3D裝箱系統")
st.markdown("---")

# ==========================
# 上半部：輸入
# ==========================
col_left, col_right = st.columns([1, 2], gap="large")

with col_left:
    st.markdown('<div class="section-header">1. 訂單與外箱設定</div>', unsafe_allow_html=True)
    order_name = st.text_input("訂單名稱", value="訂單_20241208")

    st.caption("外箱尺寸 (cm)")
    c1, c2, c3 = st.columns(3)
    box_l = c1.number_input("長", value=35.0)
    box_w = c2.number_input("寬", value=25.0)
    box_h = c3.number_input("高", value=20.0)

    box_weight = st.number_input("空箱重量 (kg)", value=0.5)

with col_right:
    st.markdown('<div class="section-header">2. 商品清單 (直接編輯表格)</div>', unsafe_allow_html=True)
    if 'df' not in st.session_state:
        st.session_state.df = pd.DataFrame([
            {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 5},
            {"商品名稱": "紙袋", "長": 28.0, "寬": 24.3, "高": 0.3, "重量(kg)": 0.05, "數量": 5},
        ])

    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        height=260
    )

st.markdown("---")
run_button = st.button("🚀 開始計算與 3D 模擬", use_container_width=True)

# ==========================
# 下半部：運算
# ==========================
if run_button:
    with st.spinner("正在進行智慧裝箱運算..."):
        packer = Packer()
        max_weight_limit = 999999

        # ✅ 多箱自動拆箱
        for i in range(30):
            packer.add_bin(Bin(f"Box_{i+1}", box_l, box_w, box_h, max_weight_limit))

        requested_counts = {}
        unique_products = []
        total_qty = 0
        total_net_weight = 0

        edited_df['base_area'] = edited_df['長'] * edited_df['寬']
        sorted_df = edited_df.sort_values(by='base_area', ascending=False)

        for _, row in sorted_df.iterrows():
            name = str(row["商品名稱"])
            l, w, h = float(row["長"]), float(row["寬"]), float(row["高"])
            weight = float(row["重量(kg)"])
            qty = int(row["數量"])

            if name not in unique_products:
                unique_products.append(name)
                requested_counts[name] = 0

            for _ in range(qty):
                foldable = is_foldable_item(l, w, h)
                unstable = is_unstable_item(l, w, h)

                best_l, best_w, best_h = get_best_orientation_advanced(
                    l, w, h, box_l, box_w, box_h, layer=0
                )

                if foldable:
                    dims = sorted([l, w, h])
                    best_l, best_w, best_h = dims[2], dims[1], dims[0]

                item = Item(name, best_l, best_w, best_h, weight)
                packer.add_item(item)

                requested_counts[name] += 1
                total_qty += 1

        packer.pack(bigger_first=False)

        # ==========================
        # 3D 繪圖
        # ==========================
        fig = go.Figure()

        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w],
            z=[0, 0, 0, 0, box_h, box_h, box_h, box_h],
            mode='lines', line=dict(color='black', width=6), name='外箱'
        ))

        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD']
        colors = {n: palette[i % len(palette)] for i, n in enumerate(unique_products)}

        packed_counts = {}

        for b in packer.bins:
            for item in b.items:
                packed_counts[item.name] = packed_counts.get(item.name, 0) + 1
                x, y, z = map(float, item.position)
                w, d, h = map(float, item.get_dimension())
                total_net_weight += item.weight

                fig.add_trace(go.Mesh3d(
                    x=[x, x+w, x+w, x, x, x+w, x+w, x],
                    y=[y, y, y+d, y+d, y, y, y+d, y+d],
                    z=[z, z, z, z, z+h, z+h, z+h, z+h],
                    color=colors[item.name],
                    opacity=0.95,
                    name=item.name
                ))

        fig.update_layout(
            scene=dict(
                xaxis_title="長", yaxis_title="寬", zaxis_title="高",
                aspectmode="data",
                camera=dict(eye=dict(x=1.6, y=1.6, z=1.6))
            ),
            height=600,
            margin=dict(l=0, r=0, b=0, t=30)
        )

        # ==========================
        # 報表
        # ==========================
        box_vol = box_l * box_w * box_h
        utilization = sum(
            float(item.get_dimension()[0]) *
            float(item.get_dimension()[1]) *
            float(item.get_dimension()[2])
            for b in packer.bins for item in b.items
        ) / box_vol * 100

        tw_time = datetime.datetime.utcnow() + datetime.timedelta(hours=8)

        st.markdown('<div class="section-header">3. 裝箱結果與模擬</div>', unsafe_allow_html=True)
        st.markdown(f"""
        <div class="report-card">
        <b>訂單：</b>{order_name}<br>
        <b>時間：</b>{tw_time.strftime('%Y-%m-%d %H:%M')}<br>
        <b>箱數：</b>{len([b for b in packer.bins if b.items])}<br>
        <b>總重：</b>{total_net_weight + box_weight:.2f} kg<br>
        <b>空間利用率：</b>{utilization:.2f}%
        </div>
        """, unsafe_allow_html=True)

        st.plotly_chart(fig, use_container_width=True, theme=None)
