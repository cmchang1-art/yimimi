# @title 3D 裝箱互動系統 (V15 重量錯誤修復版)
# 安裝必要套件
!pip install py3dbp plotly pandas ipywidgets -q

import ipywidgets as widgets
from IPython.display import display, clear_output, IFrame, HTML
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import base64
import datetime

# ==========================================
# 1. 定義計算與繪圖邏輯
# ==========================================

def calculate_and_plot(order_name, box_dims, box_weight, product_list, output_widget):
    with output_widget:
        clear_output(wait=True)
        print("正在進行 3D 運算、重量統計與報表生成...")
        
        box_L, box_W, box_H = box_dims
        # 設定一個超大的載重限制，避免 py3dbp 因為重量拒絕裝箱 (我們只用來統計，不限制)
        max_weight_limit = 999999 

        packer = Packer()
        # 加入外箱
        packer.add_bin(Bin('StandardBox', box_L, box_W, box_H, max_weight_limit))

        # 1. 統計需求 & 建立顏色映射表
        requested_counts = {}
        unique_products = []
        total_qty_requested = 0 
        
        for prod in product_list:
            name, l, w, h, weight, qty = prod 
            total_qty_requested += qty
            if name not in requested_counts:
                requested_counts[name] = 0
                unique_products.append(name) 
            requested_counts[name] += qty
            
            for _ in range(qty):
                # 將真實重量傳入 Item
                packer.add_item(Item(name, l, w, h, weight))

        # 顏色池
        palette = ['#FF5733', '#33FF57', '#3357FF', '#F1C40F', '#8E44AD', '#00FFFF', '#FF00FF', '#E74C3C', '#2ECC71', '#3498DB']
        product_colors = {}
        for i, p_name in enumerate(unique_products):
            product_colors[p_name] = palette[i % len(palette)]

        # 執行計算
        packer.pack()

        # 開始繪圖
        fig = go.Figure()
        
        # 畫外箱
        fig.add_trace(go.Scatter3d(
            x=[0, box_L, box_L, 0, 0, 0, box_L, box_L, 0, 0, 0, 0, box_L, box_L, box_L, box_L],
            y=[0, 0, box_W, box_W, 0, 0, 0, box_W, box_W, 0, 0, box_W, box_W, 0, 0, box_W],
            z=[0, 0, 0, 0, 0, box_H, box_H, box_H, box_H, box_H, 0, box_H, box_H, box_H, 0, 0],
            mode='lines', line=dict(color='blue', width=5), name='外箱邊界'
        ))

        total_vol = 0
        total_net_weight = 0 
        box_vol = box_L * box_W * box_H
        packed_counts = {} 
        
        # 畫商品
        for b in packer.bins:
            for item in b.items:
                if item.name in packed_counts:
                    packed_counts[item.name] += 1
                else:
                    packed_counts[item.name] = 1

                x, y, z = float(item.position[0]), float(item.position[1]), float(item.position[2])
                dim = item.get_dimension()
                w, d, h = float(dim[0]), float(dim[1]), float(dim[2])
                
                # === V15 修正點：直接讀取 weight 屬性，而不是呼叫函數 ===
                item_weight = float(item.weight) 
                
                total_vol += (w * d * h)
                total_net_weight += item_weight 

                color = product_colors.get(item.name, '#888888')
                hover_text = f"{item.name}<br>尺寸: {w}x{d}x{h}<br>重量: {item_weight}kg<br>位置: ({x}, {y}, {z})"

                fig.add_trace(go.Mesh3d(
                    x=[x, x+w, x+w, x, x, x+w, x+w, x],
                    y=[y, y, y+d, y+d, y, y, y+d, y+d],
                    z=[z, z, z, z, z+h, z+h, z+h, z+h],
                    i = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
                    j = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
                    k = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
                    color=color, opacity=1, name=item.name, showlegend=True,
                    text=hover_text, hoverinfo='text'
                ))
                fig.add_trace(go.Scatter3d(
                    x=[x, x+w, x+w, x, x, x, x+w, x+w, x, x, x, x, x+w, x+w, x+w, x+w],
                    y=[y, y, y+d, y+d, y, y, y, y, y+d, y+d, y, y+d, y+d, y, y, y+d],
                    z=[z, z, z, z, z, z+h, z+h, z+h, z+h, z+h, z, z+h, z+h, z+h, z, z],
                    mode='lines', line=dict(color='black', width=3), showlegend=False
                ))
            
            # === 生成詳細報告 HTML ===
            utilization = (total_vol / box_vol) * 100
            total_gross_weight = total_net_weight + box_weight 
            
            tw_time = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
            now_str = tw_time.strftime("%Y-%m-%d %H:%M")
            file_time_str = tw_time.strftime("%Y%m%d_%H%M")
            
            report_html = f"""
            <div style="font-family: sans-serif; padding: 15px; border: 2px solid #ccc; border-radius: 8px; background: #ffffff; color: #000000; margin-bottom: 15px;">
                <h2 style="margin-top:0; color: #2c3e50; border-bottom: 2px solid #2c3e50;">📋 訂單裝箱報告</h2>
                
                <table style="border-collapse: collapse; margin-bottom: 10px;">
                    <tr>
                        <td style="padding: 5px 15px 5px 5px; font-weight: bold; white-space: nowrap;">📝 訂單名稱:</td>
                        <td style="padding: 5px; color: #0000FF; font-size: 1.2em;">{order_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px 15px 5px 5px; font-weight: bold; white-space: nowrap;">🕒 計算時間:</td>
                        <td style="padding: 5px;">{now_str} (台灣時間)</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px 15px 5px 5px; font-weight: bold; white-space: nowrap;">📦 外箱尺寸:</td>
                        <td style="padding: 5px;">{box_L} x {box_W} x {box_H}</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px 15px 5px 5px; font-weight: bold; white-space: nowrap;">⚖️ 內容淨重:</td>
                        <td style="padding: 5px;">{total_net_weight:.2f} kg</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px 15px 5px 5px; font-weight: bold; white-space: nowrap;">📦 空箱重量:</td>
                        <td style="padding: 5px; color: #666;">{box_weight:.2f} kg</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px 15px 5px 5px; font-weight: bold; white-space: nowrap; color: #d35400;">🚛 本箱總重 (毛重):</td>
                        <td style="padding: 5px; font-weight: bold; color: #d35400; font-size: 1.1em;">{total_gross_weight:.2f} kg</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px 15px 5px 5px; font-weight: bold; white-space: nowrap;">📊 空間利用率:</td>
                        <td style="padding: 5px;">{utilization:.2f}%</td>
                    </tr>
                </table>
                <hr>
            """
            
            all_fitted = True
            missing_items_html = ""
            
            for name, req_qty in requested_counts.items():
                real_qty = packed_counts.get(name, 0)
                if real_qty < req_qty:
                    diff = req_qty - real_qty
                    all_fitted = False
                    missing_items_html += f"<li style='color: #D8000C; font-weight: bold; background-color: #FFD2D2; padding: 5px; margin: 5px 0;'>⚠️ {name}: 遺漏 {diff} 個 (需求 {req_qty} / 實裝 {real_qty})</li>"
            
            if all_fitted:
                report_html += "<h3 style='color: #270; background-color: #DFF2BF; padding: 10px;'>✅ 完美！所有商品皆已裝入。</h3>"
            else:
                report_html += f"""
                <h3 style='color: #D8000C;'>❌ 注意：有部分商品裝不下！</h3>
                <ul style='padding-left: 0; list-style: none;'>
                    {missing_items_html}
                </ul>
                <p style='color: #333; font-weight: bold;'>💡 建議：嘗試更換更大的外箱，或減少商品數量。</p>
                """
            
            report_html += "</div>"
            display(HTML(report_html))

        # 設定圖表標題
        fig.update_layout(
            scene=dict(xaxis_title='長', yaxis_title='寬', zaxis_title='高', aspectmode='data'),
            title=f"3D 模擬圖: {order_name} (總重: {total_gross_weight:.2f}kg)", 
            margin=dict(t=40, b=0, l=0, r=0),
            height=600, autosize=True,
            legend=dict(itemsizing='constant')
        )
        
        names = set()
        fig.for_each_trace(
            lambda trace:
                trace.update(showlegend=False)
                if (trace.name in names) else names.add(trace.name))

        # === 智能生成檔案 ===
        try:
            plot_html = fig.to_html(include_plotlyjs='cdn', full_html=False)
            
            full_html_content = f"""
            <html>
            <head><title>裝箱報告 - {order_name}</title></head>
            <body style="font-family: sans-serif; background-color: #f4f4f4; padding: 20px;">
                <div style="max-width: 1000px; margin: 0 auto;">
                    {report_html}
                    <div style="background: white; padding: 10px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
                        {plot_html}
                    </div>
                </div>
            </body>
            </html>
            """
            
            b64_str = base64.b64encode(full_html_content.encode('utf-8')).decode('utf-8')
            plot_only_b64 = base64.b64encode(fig.to_html(include_plotlyjs='cdn', full_html=True).encode('utf-8')).decode('utf-8')
            display(IFrame(src=f"data:text/html;base64,{plot_only_b64}", width='100%', height='650px'))
            
            # 檔名邏輯
            safe_order_name = order_name.replace(" ", "_").replace("/", "-") 
            filename = f"{safe_order_name}_{file_time_str}_總數{total_qty_requested}.html"
            
            download_btn = f'''
            <div style="text-align: center; margin-top: 20px;">
                <a download="{filename}" href="data:text/html;base64,{b64_str}" target="_blank" 
                   style="background-color: #28a745; color: white; padding: 12px 30px; text-decoration: none; font-size: 16px; border-radius: 8px; font-weight: bold; box-shadow: 2px 2px 5px rgba(0,0,0,0.2); cursor: pointer;">
                   📥 下載裝箱報告
                </a>
                <div style="margin-top: 10px; color: #888; font-size: 12px;">(已自動命名為: {filename})</div>
            </div>
            '''
            display(HTML(download_btn))
            
        except Exception as e:
            print(f"顯示錯誤: {e}")

# ==========================================
# 2. 建立互動介面 (UI)
# ==========================================

layout_box_input = widgets.Layout(width='180px') 
style_box_input = {'description_width': '80px'}  

# 商品欄位的樣式
layout_prod_input = widgets.Layout(width='110px') 
style_prod_input = {'description_width': '25px'}
layout_name = widgets.Layout(width='150px')
layout_qty = widgets.Layout(width='100px')

order_header = widgets.HTML("<h3>📝 步驟一：輸入訂單資訊</h3>")
w_order_name = widgets.Text(value="訂單_001", description='訂單名稱:', placeholder='例如: 蝦皮-A123', style={'description_width': '80px'}, layout=widgets.Layout(width='300px'))

box_header = widgets.HTML("<h3>📦 步驟二：設定外箱尺寸與重量</h3>")
w_box_L = widgets.FloatText(value=45, description='長(L):', layout=layout_box_input, style=style_box_input)
w_box_W = widgets.FloatText(value=30, description='寬(W):', layout=layout_box_input, style=style_box_input)
w_box_H = widgets.FloatText(value=30, description='高(H):', layout=layout_box_input, style=style_box_input)
w_box_Weight = widgets.FloatText(value=0.5, description='空箱重(kg):', layout=layout_box_input, style=style_box_input)

box_ui = widgets.HBox([w_box_L, w_box_W, w_box_H, w_box_Weight])

prod_header = widgets.HTML("<h3>🎁 步驟三：設定商品 (含單重)</h3>")
items_container = widgets.VBox() 

def create_product_row(index):
    default_name = f"商品_{index+1}"
    w_name = widgets.Text(value=default_name, placeholder='品名', layout=layout_name)
    w_l = widgets.FloatText(value=21, description='長:', layout=layout_prod_input, style=style_prod_input)
    w_w = widgets.FloatText(value=14, description='寬:', layout=layout_prod_input, style=style_prod_input)
    w_h = widgets.FloatText(value=8.5, description='高:', layout=layout_prod_input, style=style_prod_input)
    # 重量欄位
    w_weight = widgets.FloatText(value=0.5, description='重(kg):', layout=layout_prod_input, style={'description_width': '50px'}) 
    w_qty = widgets.IntText(value=7, description='數:', layout=layout_qty, style=style_prod_input)
    
    btn_del = widgets.Button(description="刪", button_style='danger', icon='trash', layout=widgets.Layout(width='50px'))
    
    row = widgets.HBox([w_name, w_l, w_w, w_h, w_weight, w_qty, btn_del])
    def delete_row(b): row.close()
    btn_del.on_click(delete_row)
    return row

items_container.children += (create_product_row(0),)
btn_add_prod = widgets.Button(description="＋ 新增商品尺寸", button_style='info', icon='plus', layout=widgets.Layout(width='300px'))
def on_add_click(b):
    items_container.children += (create_product_row(len(items_container.children)),)
btn_add_prod.on_click(on_add_click)

action_header = widgets.HTML("<h3>🚀 步驟四：執行運算</h3>")
btn_run = widgets.Button(description="生成報告與圖表", button_style='success', layout=widgets.Layout(width='300px', height='50px'), icon='cube')
output_area = widgets.Output(layout={'border': '1px solid #ccc', 'min_height': '800px', 'padding': '5px'})

def on_run_click(b):
    order_name = w_order_name.value
    if not order_name: order_name = "未命名訂單"
    
    box_dims = (w_box_L.value, w_box_W.value, w_box_H.value)
    box_w = w_box_Weight.value 
    
    products = []
    for row in items_container.children:
        try:
            # row structure: Name, L, W, H, Weight, Qty, Del
            p_name = row.children[0].value
            p_l = float(row.children[1].value)
            p_w = float(row.children[2].value)
            p_h = float(row.children[3].value)
            p_weight = float(row.children[4].value)
            p_qty = int(row.children[5].value)
            
            if p_qty > 0: products.append((p_name, p_l, p_w, p_h, p_weight, p_qty))
        except: pass
    calculate_and_plot(order_name, box_dims, box_w, products, output_area)

btn_run.on_click(on_run_click)

ui = widgets.VBox([
    order_header, w_order_name, widgets.HTML("<hr>"),
    box_header, box_ui, widgets.HTML("<hr>"),
    prod_header, items_container, btn_add_prod, widgets.HTML("<hr>"),
    action_header, btn_run, widgets.HTML("<hr>"),
    output_area
])
display(ui)
