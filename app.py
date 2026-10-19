import os
import time

import requests  # type: ignore
import streamlit as st  # type: ignore

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8001")

st.set_page_config(page_title="VendorPulse", layout="centered")

# --- Session state defaults ---
for key in ("token", "user_email", "full_name"):
    if key not in st.session_state:
        st.session_state[key] = None


# =========================================================
# Helpers
# =========================================================
def api(method: str, path: str, timeout: int = 30, **kwargs):
    """Call the backend. Returns a Response, or None if it can't be reached."""
    try:
        return requests.request(
            method, f"{API_BASE_URL}{path}", timeout=timeout, **kwargs
        )
    except requests.exceptions.RequestException as e:
        st.error(f"Can't reach the backend at {API_BASE_URL}: {e}")
        return None


def safe_json(resp) -> dict:
    """Parse JSON without crashing on empty / HTML / plain-text bodies."""
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def error_detail(resp) -> str:
    """Human-readable error text for any failed response."""
    detail = safe_json(resp).get("detail")
    if detail:
        return str(detail)
    return f"HTTP {resp.status_code}: {resp.text[:200] or 'empty response'}"


def fmt(value) -> str:
    """Make every table cell a string (keeps Arrow happy) and show a dash for empty."""
    if value is None or value == "":
        return "—"
    return str(value)


# =========================================================
# 1. RESET-PASSWORD FLOW (only when a token is in the URL)
# =========================================================
reset_token = st.query_params.get("token")

if reset_token:
    st.title("🔑 Reset your password")
    new_password = st.text_input("New password", type="password", key="new_pw")
    confirm_password = st.text_input(
        "Confirm new password", type="password", key="confirm_pw"
    )

    if st.button("Reset password"):
        if new_password != confirm_password:
            st.error("Passwords don't match.")
        elif len(new_password) < 6:
            st.error("Password must be at least 6 characters.")
        else:
            with st.spinner("Resetting..."):
                resp = api(
                    "POST",
                    "/auth/reset-password",
                    json={"token": reset_token, "new_password": new_password},
                )
            if resp is not None:
                if resp.status_code == 200:
                    st.success(
                        "Password reset! Clear the link from your browser and sign in below."
                    )
                else:
                    st.error(f"Reset failed: {error_detail(resp)}")

    st.stop()


# =========================================================
# 2. AUTH - Sign In / Sign Up / Forgot Password
# =========================================================
if not st.session_state.token:
    st.title("VendorPulse")
    st.caption("Sign in to upload and extract vendor contract terms.")

    tab_signin, tab_signup, tab_forgot = st.tabs(
        ["Sign In", "Sign Up", "Forgot Password"]
    )

    # --- Sign In ---
    with tab_signin:
        email = st.text_input("Email", key="signin_email")
        password = st.text_input("Password", type="password", key="signin_password")

        if st.button("Sign In", key="signin_btn"):
            with st.spinner("Signing in..."):
                resp = api(
                    "POST",
                    "/auth/signin",
                    json={"email": email, "password": password},
                )

            if resp is not None:
                token = safe_json(resp).get("access_token") if resp.ok else None
                if token:
                    me_resp = api(
                        "GET",
                        "/auth/me",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    full_name = None
                    if me_resp is not None and me_resp.ok:
                        full_name = safe_json(me_resp).get("full_name")

                    st.session_state.token = token
                    st.session_state.full_name = full_name
                    st.session_state.user_email = email
                    st.rerun()
                else:
                    st.error(f"Sign in failed: {error_detail(resp)}")

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
                    resp = api(
                        "POST",
                        "/auth/signup",
                        json={
                            "email": su_email,
                            "password": su_password,
                            "full_name": su_full_name or None,
                        },
                    )

                if resp is not None:
                    token = (
                        safe_json(resp).get("access_token")
                        if resp.status_code in (200, 201)
                        else None
                    )
                    if token:
                        st.session_state.token = token
                        st.session_state.full_name = su_full_name or None
                        st.session_state.user_email = su_email
                        st.rerun()
                    else:
                        st.error(f"Sign up failed: {error_detail(resp)}")

    # --- Forgot Password ---
    with tab_forgot:
        fp_email = st.text_input("Email", key="forgot_email")

        if st.button("Send reset link", key="forgot_btn"):
            with st.spinner("Sending..."):
                resp = api(
                    "POST", "/auth/forgot-password", json={"email": fp_email}
                )
            if resp is not None:
                if resp.status_code == 200:
                    st.success(
                        safe_json(resp).get(
                            "message",
                            "If that email is registered, a reset link has been sent.",
                        )
                    )
                else:
                    st.error(f"Request failed: {error_detail(resp)}")

    st.stop()


# =========================================================
# 3. LOGGED IN - Upload & Extract UI
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
        st.session_state.pop("chat_messages", None)
        st.session_state.pop("chat_history_owner", None)
        st.rerun()

    st.divider()
    page = st.radio("Go to", ["Upload & Extract", "Chatbot"], key="page")

if page == "Chatbot":
    from chat_ui import render_chat

    render_chat(api, headers, safe_json, error_detail)
    st.stop()

st.title("VendorPulse")
st.caption("Upload a vendor contract and let Groq pull out the key renewal terms.")

uploaded_file = st.file_uploader("Upload a contract", type=["pdf", "docx"])

STAGES = [
    ("loading", "Reading the document"),
    ("chunking", "Splitting into semantic chunks"),
    ("embedding", "Generating embeddings"),
    ("storing", "Storing vectors in ChromaDB"),
    ("done", "Ready for retrieval"),
]
STAGE_ORDER = [k for k, _ in STAGES]
RAG_TIMEOUT_SECONDS = 300  # first run may download the embedding model


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
            detail = f" - **{rag['chunks']} chunks**"
        if key == "embedding" and rag.get("dim"):
            detail = f" - **{rag['dim']}-dimension vectors**"
        if key == "storing" and stage == "done":
            detail = f" - **{rag.get('chunks')} vectors saved**"
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
        files = {
            "file": (
                uploaded_file.name,
                uploaded_file.getvalue(),
                uploaded_file.type or "application/octet-stream",
            )
        }
        resp = api("POST", "/contracts/upload", timeout=120, files=files, headers=headers)

    if resp is None:
        st.stop()
    if not resp.ok:
        st.error(f"Upload failed: {error_detail(resp)}")
        st.stop()

    contract_id = safe_json(resp).get("contract_id")
    if not contract_id:
        st.error(f"Upload succeeded but no contract_id came back: {resp.text[:200]}")
        st.stop()
    st.success(f"Uploaded. Contract ID: {contract_id}")

    # ---- Step 2: watch the RAG pipeline run (real status from the backend) ----
    with st.status("Processing document (RAG pipeline)…", expanded=True) as status_box:
        placeholder = st.empty()
        rag = {"stage": "queued"}
        placeholder.markdown(render_steps(rag))
        deadline = time.time() + RAG_TIMEOUT_SECONDS

        while time.time() < deadline:
            try:
                r = requests.get(
                    f"{API_BASE_URL}/contracts/{contract_id}/rag-status",
                    headers=headers,
                    timeout=15,
                )
            except requests.exceptions.RequestException as e:
                placeholder.warning(f"Can't reach rag-status: {e}")
                time.sleep(2)
                continue

            if r.status_code == 200:
                rag = safe_json(r) or rag
                placeholder.markdown(render_steps(rag))
                if rag.get("stage") in ("done", "failed"):
                    break
            else:
                placeholder.warning(
                    f"rag-status returned {r.status_code}: {r.text[:200]}"
                )
            time.sleep(1.5)

        if rag.get("stage") == "done":
            status_box.update(label="Document indexed ✅", state="complete", expanded=True)
        elif rag.get("stage") == "failed":
            status_box.update(label="Indexing failed ❌", state="error", expanded=True)
        else:
            status_box.update(
                label=f"Indexing is taking too long (stuck at stage: {rag.get('stage')})",
                state="error",
                expanded=True,
            )

    # ---- Step 3: field extraction (Groq) ----
    with st.spinner("Running Groq extraction..."):
        extract_resp = api(
            "POST", f"/contracts/{contract_id}/extract", timeout=120, headers=headers
        )

    if extract_resp is None:
        st.stop()
    if not extract_resp.ok:
        st.error(f"Extraction failed: {error_detail(extract_resp)}")
        st.stop()

    data = safe_json(extract_resp).get("extracted") or {}
    st.subheader("Extracted Fields")

    pricing_amount = data.get("pricing_amount")
    pricing_currency = data.get("pricing_currency") or ""
    pricing_text = (
        f"{pricing_amount} {pricing_currency}".strip()
        if pricing_amount not in (None, "")
        else "—"
    )

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
            # Every value is a string, so Arrow never sees mixed types.
            "Value": [
                fmt(data.get("vendor_name")),
                fmt(data.get("renewal_date")),
                fmt(data.get("auto_renew")),
                fmt(data.get("cancellation_window_days")),
                pricing_text,
                fmt(data.get("pricing_frequency")),
            ],
        }
    )

    if data.get("confidence_notes"):
        st.info(f"Model notes: {data['confidence_notes']}")

    # ---- Step 4: prove retrieval works by querying the vector DB ----
    if rag.get("stage") == "done":
        with st.expander(
            "🔎 Retrieval check - passages pulled back from the vector DB", expanded=True
        ):
            q = "When does this contract renew and how much notice is needed to cancel?"
            st.caption(f"Test query: {q}")
            ask = api(
                "GET",
                f"/contracts/{contract_id}/ask",
                params={"question": q},
                headers=headers,
            )
            if ask is not None:
                if ask.ok:
                    for i, m in enumerate(safe_json(ask).get("matches", []), 1):
                        st.markdown(f"**Match {i}** (distance {m.get('distance', 0):.3f})")
                        st.write(m.get("text", ""))
                else:
                    st.warning(f"Retrieval failed: {error_detail(ask)}")