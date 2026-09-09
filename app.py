"""
demo/app.py

Standalone Streamlit demo for ContractGuard's upload + AI extraction flow.
Run with:  streamlit run demo/app.py

This calls your FastAPI backend directly — it does not talk to Groq itself.
Set API_BASE_URL if your backend isn't on localhost:8000.
"""

import os
import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="ContractGuard Demo", layout="centered")

# --- Session state defaults ---
if "token" not in st.session_state:
    st.session_state.token = None
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "full_name" not in st.session_state:
    st.session_state.full_name = None


# =========================================================
# 1. RESET-PASSWORD FLOW (only when a token is in the URL)
# =========================================================
reset_token = st.query_params.get("token")

if reset_token:
    st.title("🔑 Reset your password")
    new_password = st.text_input("New password", type="password", key="new_pw")
    confirm_password = st.text_input("Confirm new password", type="password", key="confirm_pw")

    if st.button("Reset password"):
        if new_password != confirm_password:
            st.error("Passwords don't match.")
        elif len(new_password) < 6:
            st.error("Password must be at least 6 characters.")
        else:
            with st.spinner("Resetting..."):
                resp = requests.post(
                    f"{API_BASE_URL}/auth/reset-password",
                    json={"token": reset_token, "new_password": new_password},
                )
            if resp.status_code == 200:
                st.success("Password reset! Clear the link from your browser and sign in below.")
            else:
                st.error(f"Reset failed: {resp.status_code} — {resp.text}")

    st.stop()


# =========================================================
# 2. AUTH — Sign In / Sign Up / Forgot Password
# =========================================================
if not st.session_state.token:
    st.title(" ContractGuard")
    st.caption("Sign in to upload and extract vendor contract terms.")

    tab_signin, tab_signup, tab_forgot = st.tabs(["Sign In", "Sign Up", "Forgot Password"])

    # --- Sign In ---
    with tab_signin:
        email = st.text_input("Email", key="signin_email")
        password = st.text_input("Password", type="password", key="signin_password")

        if st.button("Sign In", key="signin_btn"):
            with st.spinner("Signing in..."):
                resp = requests.post(
                    f"{API_BASE_URL}/auth/signin",
                    json={"email": email, "password": password},
                )
            if resp.status_code == 200:
                st.session_state.token = resp.json()["access_token"]

                me_resp = requests.get(
                    f"{API_BASE_URL}/auth/me",
                    headers={"Authorization": f"Bearer {st.session_state.token}"},
                )
                st.session_state.full_name = (
                    me_resp.json().get("full_name") if me_resp.status_code == 200 else None
                )
                st.session_state.user_email = email
                st.rerun()
            else:
                st.error(f"Sign in failed: {resp.json().get('detail', resp.text)}")

    # --- Sign Up ---
    with tab_signup:
        su_email = st.text_input("Email", key="signup_email")
        su_password = st.text_input("Password", type="password", key="signup_password")
        su_full_name = st.text_input("Full name (optional)", key="signup_full_name")

        if st.button("Sign Up", key="signup_btn"):
            if len(su_password) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                with st.spinner("Creating account..."):
                    resp = requests.post(
                        f"{API_BASE_URL}/auth/signup",
                        json={
                            "email": su_email,
                            "password": su_password,
                            "full_name": su_full_name or None,
                        },
                    )
                if resp.status_code == 201:
                    st.session_state.token = resp.json()["access_token"]
                    st.session_state.full_name = su_full_name or None
                    st.session_state.user_email = su_email
                    st.rerun()
                else:
                    st.error(f"Sign up failed: {resp.json().get('detail', resp.text)}")

    # --- Forgot Password ---
    with tab_forgot:
        fp_email = st.text_input("Email", key="forgot_email")

        if st.button("Send reset link", key="forgot_btn"):
            with st.spinner("Sending..."):
                resp = requests.post(
                    f"{API_BASE_URL}/auth/forgot-password",
                    json={"email": fp_email},
                )
            if resp.status_code == 200:
                st.success(resp.json().get("message", "If that email is registered, a reset link has been sent."))
            else:
                st.error(f"Request failed: {resp.status_code} — {resp.text}")

    st.stop()


# =========================================================
# 3. LOGGED IN — Upload & Extract UI
# =========================================================
headers = {"Authorization": f"Bearer {st.session_state.token}"}

with st.sidebar:
    st.subheader("Account")
    display_name = st.session_state.full_name or st.session_state.user_email
    st.write(f"Signed in as **{display_name}**")
    if st.button("Logout"):
        st.session_state.token = None
        st.session_state.user_email = None
        st.session_state.full_name = None
        st.rerun()

st.title("ContractGuard — Contract Extraction Demo")
st.caption("Upload a vendor contract and let Groq pull out the key renewal terms.")

uploaded_file = st.file_uploader("Upload a contract", type=["pdf", "docx"])

if uploaded_file and st.button("Upload & Extract"):
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