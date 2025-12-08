# ... (上面是 fig.for_each_trace 之前的程式碼，保持不變) ...

        # ==========================
        # 這裡開始是修改的區塊
        # ==========================
        
        # 1. 計算數據
        box_vol = box_l * box_w * box_h
        utilization = (total_vol / box_vol) * 100 if box_vol > 0 else 0
        gross_weight = total_net_weight + box_weight
        
        tw_time = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        now_str = tw_time.strftime("%Y-%m-%d %H:%M")
        file_time_str = tw_time.strftime("%Y%m%d_%H%M")
        
        # 2. 判斷裝箱狀態
        all_fitted = True
        missing_items_html = ""
        for name, req_qty in requested_counts.items():
            real_qty = packed_counts.get(name, 0)
            if real_qty < req_qty:
                all_fitted = False
                diff = req_qty - real_qty
                missing_items_html += f"<li style='color: #D8000C; background-color: #FFD2D2; padding: 8px; margin: 5px 0; border-radius: 4px; font-weight: bold;'>⚠️ {name}: 遺漏 {diff} 個</li>"

        # 狀態條 HTML
        status_html = "<div style='color: #155724; background-color: #d4edda; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #c3e6cb; font-size: 1.2rem; font-weight: bold; margin-bottom: 10px;'>✅ 完美！所有商品皆已裝入。</div>" if all_fitted else f"<div style='color: #721c24; background-color: #f8d7da; padding: 10px; border-radius: 8px; border: 1px solid #f5c6cb; margin-bottom: 10px;'>❌ 注意：有部分商品裝不下！</div><ul style='padding-left: 20px;'>{missing_items_html}</ul>"

        # 3. 準備下載用的完整報告 (僅用於生成檔案，不顯示在畫面上)
        report_table_html = f"""
            <table style="border-collapse: collapse; margin-bottom: 20px; width: 100%; font-size: 1.1em;">
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">📝 訂單名稱:</td><td style="color: #0056b3; font-weight: bold;">{order_name}</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">🕒 計算時間:</td><td>{now_str} (台灣時間)</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">📦 外箱尺寸:</td><td>{box_l} x {box_w} x {box_h} cm</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555;">⚖️ 內容淨重:</td><td>{total_net_weight:.2f} kg</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 12px 5px; font-weight: bold; color: #555; color: #d9534f;">🚛 本箱總重:</td><td style="color: #d9534f; font-weight: bold; font-size: 1.2em;">{gross_weight:.2f} kg</td></tr>
                <tr><td style="padding: 12px 5px; font-weight: bold; color: #555;">📊 空間利用率:</td><td>{utilization:.2f}%</td></tr>
            </table>
        """
        
        full_html_content = f"""
        <html>
        <head><title>裝箱報告 - {order_name}</title><meta charset="utf-8"></head>
        <body style="font-family: sans-serif; padding: 30px;">
            <div style="max-width: 800px; margin: 0 auto; border: 1px solid #eee; padding: 20px; border-radius: 10px;">
                <h2>📋 訂單裝箱報告</h2>
                {report_table_html}
                {status_html}
                <hr>
                <h3>🧊 3D 模擬視圖</h3>
                {fig.to_html(include_plotlyjs='cdn', full_html=False)}
            </div>
        </body>
        </html>
        """
        
        file_name = f"{order_name.replace(' ', '_')}_{file_time_str}_總數{total_qty}.html"
        
        # ==========================
        # 4. 畫面顯示 (依照你的截圖順序排列)
        # ==========================
        st.markdown('<div class="section-header">3. 裝箱結果與模擬</div>', unsafe_allow_html=True)
        
        # (A) 空間利用率
        col_util_1, col_util_2 = st.columns([1, 4])
        with col_util_1:
             st.markdown(f"**📊 空間利用率:**")
        with col_util_2:
             st.markdown(f"**{utilization:.2f}%**")

        # (B) 狀態顯示 (綠色/紅色橫條)
        st.markdown(status_html, unsafe_allow_html=True)

        # (C) 下載按鈕 (紅色)
        st.download_button(
            label="📥 下載完整裝箱報告 (.html)",
            data=full_html_content,
            file_name=file_name,
            mime="text/html",
            type="primary"
        )

        # (D) 3D 圖表 (放在按鈕正下方)
        st.plotly_chart(fig, use_container_width=True, theme=None, config={'displayModeBar': False})
