"""
demo/app.py

Standalone Streamlit demo for ContractGuard's upload + AI extraction flow.
Run with:  streamlit run demo/app.py

This calls your FastAPI backend directly — it does not talk to Groq itself.
Set API_BASE_URL if your backend isn't on localhost:8000.
"""

import os
import time
import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="ContractGuard Demo", page_icon="📄", layout="centered")
st.title("📄 ContractGuard — Contract Extraction Demo")
st.caption("Upload a vendor contract and let Groq pull out the key renewal terms.")

# --- Auth (simple token input for demo purposes) ---
with st.sidebar:
    st.subheader("Auth")
    token = st.text_input("Bearer token", type="password", help="Paste a JWT from /auth/login")

headers = {"Authorization": f"Bearer {token}"} if token else {}

# --- Upload ---
uploaded_file = st.file_uploader("Upload a contract", type=["pdf", "docx"])

if uploaded_file and st.button("Upload & Extract"):
    if not token:
        st.error("Paste a bearer token in the sidebar first.")
        st.stop()

    with st.spinner("Uploading contract..."):
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        resp = requests.post(f"{API_BASE_URL}/contracts/upload", files=files, headers=headers)

    if resp.status_code != 200:
        st.error(f"Upload failed: {resp.status_code} — {resp.text}")
        st.stop()

    contract_id = resp.json()["contract_id"]
    st.success(f"Uploaded. Contract ID: {contract_id}")

    with st.spinner("Running Groq extraction..."):
        extract_resp = requests.post(
            f"{API_BASE_URL}/contracts/{contract_id}/extract", headers=headers
        )

    if extract_resp.status_code != 200:
        st.error(f"Extraction failed: {extract_resp.status_code} — {extract_resp.text}")
        st.stop()

    data = extract_resp.json()["extracted"]
    st.subheader("Extracted Fields")
    st.table(
        {
            "Field": [
                "Vendor",
                "Renewal Date",
                "Auto-Renew",
                "Cancellation Window (days)",
                "Pricing",
                "Billing Frequency",
            ],
            "Value": [
                data.get("vendor_name") or "—",
                data.get("renewal_date") or "—",
                data.get("auto_renew") if data.get("auto_renew") is not None else "—",
                data.get("cancellation_window_days") or "—",
                f'{data.get("pricing_amount") or "—"} {data.get("pricing_currency") or ""}'.strip(),
                data.get("pricing_frequency") or "—",
            ],
        }
    )

    if data.get("confidence_notes"):
        st.info(f"Model notes: {data['confidence_notes']}")