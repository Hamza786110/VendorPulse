"""
chat_ui.py - Streamlit chat screen for the ContractGuard assistant.

Talks to the backend only through the three chatbot endpoints:
  POST   /contracts/chatbot           ask a question
  GET    /contracts/chatbot/history   load this user's recent messages
  DELETE /contracts/chatbot/history   clear chat

The backend takes the user from the JWT, so each login sees only its own chat.
"""
import streamlit as st  # type: ignore

CHAT_TIMEOUT_SECONDS = 90  # LLM + tool calls can take a while
HISTORY_KEY = "chat_messages"
HISTORY_OWNER_KEY = "chat_history_owner"

SUGGESTIONS = [
    "How many contracts have I uploaded?",
    "Which contract renews first?",
    "Which contracts renew in the next 30 days?",
    "Did all my uploads finish processing?",
]


def _load_history(api, headers, safe_json) -> list[dict]:
    resp = api("GET", "/contracts/chatbot/history", headers=headers, params={"limit": 20})
    if resp is not None and resp.ok:
        return safe_json(resp).get("messages", [])
    return []


def _ask(api, headers, safe_json, error_detail, question: str) -> dict:
    """Returns {"answer": str, "steps": list, "sources": list} - never raises."""
    resp = api(
        "POST",
        "/contracts/chatbot",
        timeout=CHAT_TIMEOUT_SECONDS,
        headers=headers,
        json={"message": question},
    )
    if resp is None:
        return {"answer": "I couldn't reach the backend. Please try again.", "steps": [], "sources": []}
    if not resp.ok:
        return {
            "answer": f"Sorry, the assistant failed: {error_detail(resp)}",
            "steps": [],
            "sources": [],
        }
    data = safe_json(resp)
    return {
        "answer": data.get("answer") or "I couldn't produce an answer.",
        "steps": data.get("steps") or [],
        "sources": data.get("sources") or [],
    }


def _show_trace(msg: dict) -> None:
    steps, sources = msg.get("steps"), msg.get("sources")
    if not steps and not sources:
        return
    with st.expander("How I got this"):
        for s in steps or []:
            args = ", ".join(f"{k}={v!r}" for k, v in (s.get("args") or {}).items())
            st.markdown(f"- 🔧 `{s.get('tool')}({args})`")
        if sources:
            st.caption("Contracts used: " + ", ".join(sources))


def render_chat(api, headers, safe_json, error_detail) -> None:
    st.title("💬 Contract assistant")
    st.caption("Ask about your contracts - counts, renewal dates, reminders, or what a clause says.")

    # Reload history whenever a different user is logged in on this browser session.
    owner = st.session_state.get("user_email")
    if st.session_state.get(HISTORY_OWNER_KEY) != owner or HISTORY_KEY not in st.session_state:
        st.session_state[HISTORY_KEY] = _load_history(api, headers, safe_json)
        st.session_state[HISTORY_OWNER_KEY] = owner

    if st.button("🗑️ Clear chat"):
        resp = api("DELETE", "/contracts/chatbot/history", headers=headers)
        if resp is not None and resp.ok:
            st.session_state[HISTORY_KEY] = []
            st.rerun()
        elif resp is not None:
            st.error(f"Couldn't clear chat: {error_detail(resp)}")

    messages = st.session_state[HISTORY_KEY]

    if not messages:
        st.write("Try one of these:")
        for i, text in enumerate(SUGGESTIONS):
            if st.button(text, key=f"suggest_{i}"):
                st.session_state["pending_question"] = text
                st.rerun()

    for m in messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            _show_trace(m)

    question = st.session_state.pop("pending_question", None) or st.chat_input(
        "Ask about your contracts..."
    )
    if not question:
        return

    messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Checking your contracts..."):
            reply = _ask(api, headers, safe_json, error_detail, question)
        st.markdown(reply["answer"])
        _show_trace(reply)

    messages.append(
        {
            "role": "assistant",
            "content": reply["answer"],
            "steps": reply["steps"],
            "sources": reply["sources"],
        }
    )
    st.rerun()