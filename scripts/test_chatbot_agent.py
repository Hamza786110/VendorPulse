"""Agent + endpoint tests with a scripted fake LLM (no Groq key, no network)."""
import os

# auth/utils.py reads this at import time; any dummy value is fine for tests.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from mongomock_motor import AsyncMongoMockClient

from contracts import chatbot, chatbot_routes
from contracts.chatbot_memory import ChatMemory
from auth.dependencies import get_current_user, get_db


class FakeLLM(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


def _script(*msgs):
    return FakeLLM(messages=iter(msgs))


def _call(name, args=None, i=1):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": f"c{i}"}])


def _iso(d):
    return (datetime.now(timezone.utc).date() + timedelta(days=d)).isoformat()


@pytest.fixture
def db():
    return AsyncMongoMockClient()["t"]


async def _seed(db):
    await db.contracts.insert_many([
        {"_id": ObjectId(), "filename": "acme.pdf", "uploaded_by": "A", "status": "extracted",
         "extracted": {"vendor_name": "Acme", "renewal_date": _iso(3)}},
        {"_id": ObjectId(), "filename": "secret.pdf", "uploaded_by": "B", "status": "extracted",
         "extracted": {"vendor_name": "Secret", "renewal_date": _iso(1)}},
    ])


@pytest.mark.asyncio
async def test_react_loop_uses_tool_then_answers(db):
    await _seed(db)
    llm = _script(_call("upcoming_renewals", {"limit": 1}), AIMessage(content="Acme renews in 3 days."))
    out = await chatbot.answer_question(db, "A", "what renews next?", llm=llm)
    assert out["completed"] and out["answer"] == "Acme renews in 3 days."
    assert out["steps"] == [{"tool": "upcoming_renewals", "args": {"limit": 1}}]
    assert len(out["sources"]) == 1                       # only A's contract, never B's
    saved = await ChatMemory(db).load("A")
    assert [m["role"] for m in saved] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_loop_is_bounded(db):
    await _seed(db)
    llm = _script(*[_call("contract_stats", i=i) for i in range(30)])
    out = await chatbot.answer_question(db, "A", "loop forever", llm=llm)
    assert out["completed"] is False and out["answer"] == chatbot.FALLBACK
    assert await ChatMemory(db).load("A") == []           # failed turns are not remembered


@pytest.mark.asyncio
async def test_history_is_short(db):
    m = ChatMemory(db)
    for i in range(10):
        await m.append("A", "user" if i % 2 == 0 else "assistant", f"msg{i}")
    assert len(await m.load("A", chatbot.HISTORY_LIMIT)) == 4


def test_endpoints_scoped_to_logged_in_user(db, monkeypatch):
    app = FastAPI()
    app.include_router(chatbot_routes.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {"_id": "A"}
    monkeypatch.setattr(chatbot, "get_llm", lambda: _script(AIMessage(content="hello A")))  # auto-undone after the test
    c = TestClient(app)

    assert c.post("/contracts/chatbot", json={"message": "hi"}).json()["answer"] == "hello A"
    assert [m["content"] for m in c.get("/contracts/chatbot/history").json()["messages"]] == ["hi", "hello A"]

    app.dependency_overrides[get_current_user] = lambda: {"_id": "B"}
    assert c.get("/contracts/chatbot/history").json()["messages"] == []   # B sees nothing of A's chat

    app.dependency_overrides[get_current_user] = lambda: {"_id": "A"}
    assert c.delete("/contracts/chatbot/history").json()["deleted"] == 2
    assert c.post("/contracts/chatbot", json={"message": ""}).status_code == 422


def test_get_llm_needs_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        chatbot.get_llm()
    monkeypatch.setenv("GROQ_API_KEY", "dummy")
    llm = chatbot.get_llm()
    assert llm.model_name == "qwen/qwen3.8-27b"
    assert llm.reasoning_format == "hidden"