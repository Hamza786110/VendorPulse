"""
demo/app.py

Standalone Streamlit demo for ContractGuard's upload + AI extraction flow.
Run with:  streamlit run demo/app.py

This calls your FastAPI backend directly — it does not talk to Groq itself.
Set API_BASE_URL if your backend isn't on localhost:8000.
"""

import os
import requests #type:ignore
import streamlit as st #type:ignore
import time 
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8001")

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

STAGES = [
    ("loading",   "Reading the document"),
    ("chunking",  "Splitting into semantic chunks"),
    ("embedding", "Generating embeddings"),
    ("storing",   "Storing vectors in ChromaDB"),
    ("done",      "Ready for retrieval"),
]
STAGE_ORDER = [k for k, _ in STAGES]
 
 
def render_steps(rag: dict) -> str:
    """Builds a checklist of the RAG pipeline from the backend's status."""
    stage = rag.get("stage", "queued")
    lines = []
    for key, label in STAGES:
        if stage == "failed":
            lines.append(f"- ⬜ {label}")
            continue
        cur = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else -1
        idx = STAGE_ORDER.index(key)
        detail = ""
        if key == "chunking" and rag.get("chunks"):
            detail = f" — **{rag['chunks']} chunks**"
        if key == "embedding" and rag.get("dim"):
            detail = f" — **{rag['dim']}-dimension vectors**"
        if key == "storing" and stage == "done":
            detail = f" — **{rag.get('chunks')} vectors saved**"
        if idx < cur or stage == "done":
            lines.append(f"- ✅ {label}{detail}")
        elif idx == cur:
            lines.append(f"- ⏳ {label}{detail}…")
        else:
            lines.append(f"- ⬜ {label}")
    if stage == "failed":
        lines.append(f"- ❌ Failed: {rag.get('error')}")
    return "\n".join(lines)
 
 
if uploaded_file and st.button("Upload & Extract"):
    # ---- Step 1: upload ----
    with st.spinner("Uploading contract..."):
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        resp = requests.post(f"{API_BASE_URL}/contracts/upload", files=files, headers=headers)
 
    if resp.status_code != 200:
        st.error(f"Upload failed: {resp.status_code} — {resp.text}")
        st.stop()
 
    contract_id = resp.json()["contract_id"]
    st.success(f"Uploaded. Contract ID: {contract_id}")
 
    # ---- Step 2: watch the RAG pipeline run (real status from the backend) ----
    with st.status("Processing document (RAG pipeline)…", expanded=True) as status_box:
        placeholder = st.empty()
        rag = {"stage": "queued"}
        deadline = time.time() + 180
        while time.time() < deadline:
            r = requests.get(f"{API_BASE_URL}/contracts/{contract_id}/rag-status", headers=headers)
            if r.status_code == 200:
                rag = r.json()
                placeholder.markdown(render_steps(rag))
                if rag.get("stage") in ("done", "failed"):
                    break
            time.sleep(1.5)
 
        if rag.get("stage") == "done":
            status_box.update(label="Document indexed ✅", state="complete", expanded=True)
        elif rag.get("stage") == "failed":
            status_box.update(label="Indexing failed ❌", state="error", expanded=True)
        else:
            status_box.update(label="Indexing is taking too long", state="error", expanded=True)
 
    # ---- Step 3: field extraction (Groq) ----
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
 
    # ---- Step 4: prove retrieval works by querying the vector DB ----
    if rag.get("stage") == "done":
        with st.expander("🔎 Retrieval check — passages pulled back from the vector DB", expanded=True):
            q = "When does this contract renew and how much notice is needed to cancel?"
            st.caption(f"Test query: {q}")
            ask = requests.get(
                f"{API_BASE_URL}/contracts/{contract_id}/ask",
                params={"question": q},
                headers=headers,
            )
            if ask.status_code == 200:
                for i, m in enumerate(ask.json()["matches"], 1):
                    st.markdown(f"**Match {i}** (distance {m['distance']:.3f})")
                    st.write(m["text"])
            else:
                st.warning(f"Retrieval failed: {ask.status_code} — {ask.text}")