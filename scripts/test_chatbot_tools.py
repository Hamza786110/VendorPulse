import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

from contracts.chatbot_memory import ChatMemory
from contracts.chatbot_tools import build_tools


def _iso(days):
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


def _doc(user, vendor, days, **kw):
    return {
        "_id": ObjectId(), "filename": f"{vendor}.pdf", "uploaded_by": user, "status": "extracted",
        "extracted": {"vendor_name": vendor, "renewal_date": _iso(days), "auto_renew": True,
                      "pricing_amount": 100.0, "pricing_currency": "USD", **kw},
    }


@pytest.fixture
def db():
    d = AsyncMongoMockClient()["t"]
    asyncio.get_event_loop_policy()
    return d


async def _seed(db):
    await db.contracts.insert_many([
        _doc("A", "Acme", 3), _doc("A", "Globex", 40, auto_renew=False),
        _doc("B", "SecretCorp", 2),
    ])


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


@pytest.mark.asyncio
async def test_stats_scoped(db):
    await _seed(db)
    out = await _tool(build_tools(db, "A"), "contract_stats").ainvoke({})
    assert out["total"] == 2


@pytest.mark.asyncio
async def test_user_isolation(db):
    await _seed(db)
    tools = build_tools(db, "A")
    out = await _tool(tools, "list_contracts").ainvoke({"vendor": "SecretCorp"})
    assert out["matched"] == 0
    out = await _tool(tools, "get_contract_details").ainvoke({"contract_ref": "SecretCorp"})
    assert out["found"] is False


@pytest.mark.asyncio
async def test_upcoming_and_days_until(db):
    await _seed(db)
    out = await _tool(build_tools(db, "A"), "upcoming_renewals").ainvoke({"days": 5})
    assert out["matched"] == 1 and out["contracts"][0]["vendor_name"] == "Acme"
    assert out["contracts"][0]["days_until_renewal"] == 3


@pytest.mark.asyncio
async def test_missing_field_is_explicit(db):
    await db.contracts.insert_one(_doc("A", "Initech", 10, pricing_amount=None))
    out = await _tool(build_tools(db, "A"), "get_contract_details").ainvoke({"contract_ref": "initech"})
    assert out["contract"]["pricing_amount"] == "not extracted"


@pytest.mark.asyncio
async def test_bad_id_does_not_crash(db):
    out = await _tool(build_tools(db, "A"), "get_contract_details").ainvoke({"contract_ref": "not-an-oid"})
    assert out["found"] is False


@pytest.mark.asyncio
async def test_memory_per_user(db):
    m = ChatMemory(db)
    await m.append("A", "user", "hi")
    await m.append("A", "assistant", "hello")
    await m.append("B", "user", "other")
    assert [x["content"] for x in await m.load("A")] == ["hi", "hello"]
    assert await m.clear("A") == 2
    assert await m.load("A") == [] and len(await m.load("B")) == 1


@pytest.mark.asyncio
async def test_closest_renewal_no_window(db):
    await _seed(db)
    out = await _tool(build_tools(db, "A"), "upcoming_renewals").ainvoke({"limit": 1})
    assert out["matched"] == 2
    assert out["contracts"][0]["vendor_name"] == "Acme"  # 3 days beats 40 days


@pytest.mark.asyncio
async def test_list_uploads_scoped_and_counted(db):
    await _seed(db)
    out = await _tool(build_tools(db, "A"), "list_uploads").ainvoke({})
    assert out["total_uploads"] == 2
    assert all(u["filename"] != "SecretCorp.pdf" for u in out["uploads"])


@pytest.mark.asyncio
async def test_reminder_status(db):
    d1 = _doc("A", "Acme", 3)                       # in window, not reminded
    d2 = _doc("A", "Globex", 30)                    # outside window
    d3 = _doc("A", "Initech", 2)
    d3["renewal_reminder_sent"] = True              # already reminded
    d3["renewal_reminder_sent_at"] = datetime.now(timezone.utc)
    other = _doc("B", "SecretCorp", 1)              # other user, must never show
    await db.contracts.insert_many([d1, d2, d3, other])
    out = await _tool(build_tools(db, "A"), "reminder_status").ainvoke({})
    assert [c["vendor_name"] for c in out["in_window_not_yet_reminded"]] == ["Acme"]
    assert [c["vendor_name"] for c in out["reminders_sent"]] == ["Initech"]