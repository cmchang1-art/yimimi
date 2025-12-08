import streamlit as st
import pandas as pd
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import datetime

# ==========================
# 頁面設定
# ==========================
st.set_page_config(layout="wide", page_title="3D 智能裝箱系統")

# 自定義 CSS 讓介面更漂亮
st.markdown("""
<style>
    .report-card {
        font-family: sans-serif; 
        padding: 15px; 
        border: 2px solid #ccc; 
        border-radius: 8px; 
        background: #ffffff; 
        color: #000000; 
        margin-bottom: 15px;
    }
    .stApp {
        background-color: #f0f2f6;
    }
</style>
""", unsafe_allow_html=True)

st.title("📦 3D 智能裝箱系統 (專業版)")
st.markdown("---")

# ==========================
# 側邊欄：設定區
# ==========================
with st.sidebar:
    st.header("📝 1. 訂單與外箱設定")
    
    order_name = st.text_input("訂單名稱", value="訂單_20241208")
    
    st.subheader("外箱規格")
    col1, col2, col3 = st.columns(3)
    box_l = col1.number_input("長 (cm)", value=45.0, step=1.0)
    box_w = col2.number_input("寬 (cm)", value=30.0, step=1.0)
    box_h = col3.number_input("高 (cm)", value=30.0, step=1.0)
    
    box_weight = st.number_input("空箱重量 (kg)", value=0.5, step=0.1)
    
    st.markdown("---")
    st.info("💡 修改下方商品清單後，請點擊執行按鈕。")
    run_button = st.button("🔄 執行裝箱運算", type="primary")

# ==========================
# 主畫面：商品清單
# ==========================
st.header("🎁 2. 商品清單")

# 預設數據
if 'df' not in st.session_state:
    st.session_state.df = pd.DataFrame(
        [
            {"商品名稱": "禮盒(米餅)", "長": 21.0, "寬": 14.0, "高": 8.5, "重量(kg)": 0.5, "數量": 7},
            {"商品名稱": "禮盒(茶葉)", "長": 10.0, "寬": 10.0, "高": 15.0, "重量(kg)": 0.3, "數量": 2},
        ]
    )

# 可編輯表格
edited_df = st.data_editor(
    st.session_state.df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "數量": st.column_config.NumberColumn(min_value=1, step=1, format="%d"),
        "長": st.column_config.NumberColumn(format="%.1f"),
        "寬": st.column_config.NumberColumn(format="%.1f"),
        "高": st.column_config.NumberColumn(format="%.1f"),
        "重量(kg)": st.column_config.NumberColumn(format="%.2f"),
    }
)

# ==========================
# 運算邏輯
# ==========================
if run_button:
    with st.spinner('正在進行 3D 運算與生成報表...'):
        # 準備數據
        max_weight_limit = 999999
        packer = Packer()
        packer.add_bin(Bin('StandardBox', box_l, box_w, box_h, max_weight_limit))
        
        requested_counts = {}
        unique_products = []
        total_qty = 0
        total_net_weight = 0
        
        # 讀取表格數據
        for index, row in edited_df.iterrows():
            try:
                name = str(row["商品名稱"])
                l = float(row["長"])
                w = float(row["寬"])
                h = float(row["高"])
                weight = float(row["重量(kg)"])
                qty = int(row["數量"])
                
                if qty > 0:
                    total_qty += qty
                    if name not in requested_counts:
                        requested_counts[name] = 0
                        unique_products.append(name)
                    requested_counts[name] += qty
                    
                    for _ in range(qty):
                        packer.add_item(Item(name, l, w, h, weight))
            except:
                pass

        # 顏色分配
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB']
        product_colors = {name: palette[i % len(palette)] for i, name in enumerate(unique_products)}

        # 開始計算
        packer.pack()
        
        # 準備繪圖
        fig = go.Figure()
        
        # 畫外箱
        fig.add_trace(go.Scatter3d(
            x=[0, box_l, box_l, 0, 0, 0, box_l, box_l, 0, 0, 0, 0, box_l, box_l, box_l, box_l],
            y=[0, 0, box_w, box_w, 0, 0, 0, box_w, box_w, 0, 0, box_w, box_w, 0, 0, box_w],
            z=[0, 0, 0, 0, 0, box_h, box_h, box_h, box_h, box_h, 0, box_h, box_h, box_h, 0, 0],
            mode='lines', line=dict(color='blue', width=5), name='外箱'
        ))

        total_vol = 0
        packed_counts = {}
        
        # 畫商品
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
                hover_text = f"{item.name}<br>{idim_w}x{idim_d}x{idim_h}<br>{i_weight}kg"
                
                fig.add_trace(go.Mesh3d(
                    x=[x, x+idim_w, x+idim_w, x, x, x+idim_w, x+idim_w, x],
                    y=[y, y, y+idim_d, y+idim_d, y, y, y+idim_d, y+idim_d],
                    z=[z, z, z, z, z+idim_h, z+idim_h, z+idim_h, z+idim_h],
                    i = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
                    j = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
                    k = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=color, opacity=1, name=item.name, showlegend=True,
                    text=hover_text, hoverinfo='text'
                ))
                fig.add_trace(go.Scatter3d(
                    x=[x, x+idim_w, x+idim_w, x, x, x, x+idim_w, x+idim_w, x, x, x, x, x+idim_w, x+idim_w, x+idim_w, x+idim_w],
                    y=[y, y, y+idim_d, y+idim_d, y, y, y, y, y+idim_d, y+idim_d, y, y+idim_d, y+idim_d, y, y, y+idim_d],
                    z=[z, z, z, z, z, z+idim_h, z+idim_h, z+idim_h, z+idim_h, z+idim_h, z, z+idim_h, z+idim_h, z+idim_h, z, z],
                    mode='lines', line=dict(color='black', width=3), showlegend=False
                ))

        # 整理圖表
        names = set()
        fig.for_each_trace(lambda trace: trace.update(showlegend=False) if (trace.name in names) else names.add(trace.name))
        fig.update_layout(scene=dict(xaxis_title='L', yaxis_title='W', zaxis_title='H', aspectmode='data'), margin=dict(t=0, b=0, l=0, r=0), height=600)

        # 統計與 HTML 生成
        box_vol = box_l * box_w * box_h
        utilization = (total_vol / box_vol) * 100 if box_vol > 0 else 0
        gross_weight = total_net_weight + box_weight
        
        # 台灣時間
        tw_time = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        now_str = tw_time.strftime("%Y-%m-%d %H:%M")
        file_time_str = tw_time.strftime("%Y%m%d_%H%M")
        
        # 檢查遺漏
        all_fitted = True
        missing_items_html = ""
        for name, req_qty in requested_counts.items():
            real_qty = packed_counts.get(name, 0)
            if real_qty < req_qty:
                all_fitted = False
                diff = req_qty - real_qty
                missing_items_html += f"<li style='color: #D8000C; background-color: #FFD2D2; padding: 5px; margin: 5px 0;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        status_html = "<h3 style='color: #270; background-color: #DFF2BF; padding: 10px;'>✅ 完美！所有商品皆已裝入。</h3>" if all_fitted else f"<h3 style='color: #D8000C;'>❌ 注意：有部分商品裝不下！</h3><ul>{missing_items_html}</ul>"

        # 生成 HTML 報告 (用於顯示和下載)
        report_html = f"""
        <div class="report-card">
            <h2 style="margin-top:0; color: #2c3e50; border-bottom: 2px solid #2c3e50;">📋 訂單裝箱報告</h2>
            <table style="border-collapse: collapse; margin-bottom: 10px; width: 100%;">
                <tr><td style="padding: 5px; font-weight: bold;">📝 訂單名稱:</td><td style="color: #0000FF; font-size: 1.2em;">{order_name}</td></tr>
                <tr><td style="padding: 5px; font-weight: bold;">🕒 計算時間:</td><td>{now_str} (台灣時間)</td></tr>
                <tr><td style="padding: 5px; font-weight: bold;">📦 外箱尺寸:</td><td>{box_l} x {box_w} x {box_h} cm</td></tr>
                <tr><td style="padding: 5px; font-weight: bold;">⚖️ 內容淨重:</td><td>{total_net_weight:.2f} kg</td></tr>
                <tr><td style="padding: 5px; font-weight: bold;">🚛 本箱總重:</td><td style="color: #d35400; font-weight: bold;">{gross_weight:.2f} kg</td></tr>
                <tr><td style="padding: 5px; font-weight: bold;">📊 空間利用率:</td><td>{utilization:.2f}%</td></tr>
            </table>
            <hr>
            {status_html}
        </div>
        """

        # ==========================
        # 3. 顯示結果區域
        # ==========================
        st.header("📊 3. 裝箱結果")
        
        # 1. 顯示 HTML 報告卡片
        st.markdown(report_html, unsafe_allow_html=True)
        
        # 2. 下載按鈕 (產生完整 HTML 檔案)
        full_html_content = f"""
        <html>
        <head><title>裝箱報告 - {order_name}</title></head>
        <body style="font-family: sans-serif; background-color: #f4f4f4; padding: 20px;">
            <div style="max-width: 1000px; margin: 0 auto;">
                {report_html.replace('class="report-card"', 'style="padding: 15px; border: 2px solid #ccc; border-radius: 8px; background: #ffffff; color: #000000;"')}
                <div style="background: white; padding: 10px; border-radius: 8px; margin-top: 20px;">
                    {fig.to_html(include_plotlyjs='cdn', full_html=False)}
                </div>
            </div>
        </body>
        </html>
        """
        
        file_name = f"{order_name.replace(' ', '_')}_{file_time_str}.html"
        
        st.download_button(
            label="📥 下載裝箱報告 (.html)",
            data=full_html_content,
            file_name=file_name,
            mime="text/html",
            type="primary"
        )

        # 3. 顯示 3D 圖
        st.plotly_chart(fig, use_container_width=True)
