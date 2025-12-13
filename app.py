import requests, json
import streamlit as st

def _gs_ping():
    base = st.secrets["GS_API_URL"]
    token = st.secrets["GS_TOKEN"]
    r = requests.get(
        base,
        params={"action": "list", "sheet": "box_presets", "token": token},
        timeout=20,
    )
    return r.status_code, r.text

with st.sidebar:
    st.markdown("### Google Sheet 測試")
    if st.button("✅ 測試連線"):
        code, text = _gs_ping()
        st.write("HTTP:", code)
        st.code(text)
