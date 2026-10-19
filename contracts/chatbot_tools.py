"""
contracts/chatbot_tools.py

The ONLY way the chatbot can read data. Every tool is:
  * read-only
  * scoped to one user (user_id is closed over in build_tools, the LLM never passes it)
  * deterministic for structured facts (counts/dates/prices are computed here, not by the LLM)
  * explicit about missing data ("not extracted") so the model can't fill the gap itself
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId  # type: ignore
from bson.errors import InvalidId  # type: ignore
from langchain_core.tools import tool  # type: ignore

from contracts.stats import get_contract_stats

NOT_EXTRACTED = "not extracted"

MAX_DISTANCE: float | None = None

# The nightly Airflow DAG emails the owner this many days before renewal.
REMINDER_DAYS = 5


def _today():
    return datetime.now(timezone.utc).date()


def _fmt_contract(doc: dict) -> dict:
    """Compact, LLM-friendly view of one contract. None -> 'not extracted'."""
    ex = doc.get("extracted") or {}

    def g(key):
        v = ex.get(key)
        return NOT_EXTRACTED if v is None else v

    out = {
        "contract_id": str(doc["_id"]),
        "filename": doc.get("filename"),
        "status": doc.get("status"),
        "vendor_name": g("vendor_name"),
        "renewal_date": g("renewal_date"),
        "auto_renew": g("auto_renew"),
        "cancellation_window_days": g("cancellation_window_days"),
        "pricing_amount": g("pricing_amount"),
        "pricing_currency": g("pricing_currency"),
        "pricing_frequency": g("pricing_frequency"),
        "confidence_notes": ex.get("confidence_notes") or "none",
        "uploaded_at": str(doc.get("uploaded_at")) if doc.get("uploaded_at") else NOT_EXTRACTED,
        "renewal_reminder_sent": bool(doc.get("renewal_reminder_sent", False)),
    }
    rd = ex.get("renewal_date")
    if rd:
        try:
            out["days_until_renewal"] = (datetime.fromisoformat(str(rd)).date() - _today()).days
        except ValueError:
            pass
    return out


async def _resolve(db, user_id: str, ref: str) -> tuple[dict | None, list[dict]]:
    """
    Turn a contract id / vendor name / filename into one of THIS user's contracts.
    Returns (match, candidates). match is None if nothing or if ambiguous.
    """
    mine = {"uploaded_by": user_id}
    ref = (ref or "").strip()
    if not ref:
        return None, []

    try:
        doc = await db.contracts.find_one({**mine, "_id": ObjectId(ref)})
        if doc:
            return doc, [doc]
    except (InvalidId, TypeError):
        pass

    rx = {"$regex": re.escape(ref), "$options": "i"}
    cands = await db.contracts.find(
        {**mine, "$or": [{"extracted.vendor_name": rx}, {"filename": rx}]}
    ).limit(5).to_list(length=5)
    return (cands[0] if len(cands) == 1 else None), cands


def build_tools(db, user_id: str):
    """Create the tool set for ONE logged-in user."""

    @tool
    async def contract_stats() -> dict:
        """Counts for the user's contracts: total, per processing status, how many renew
        in the next 30 days, and reminders sent. Use for any 'how many' question."""
        return {"today": _today().isoformat(), **await get_contract_stats(db, user_id)}

    @tool
    async def list_contracts(
        vendor: str | None = None,
        auto_renew: bool | None = None,
        renewing_within_days: int | None = None,
        limit: int = 20,
    ) -> dict:
        """List the user's contracts, optionally filtered by vendor name (partial match),
        auto_renew (true/false) or renewing within N days from today."""
        q: dict = {"uploaded_by": user_id}
        if vendor:
            q["extracted.vendor_name"] = {"$regex": re.escape(vendor), "$options": "i"}
        if auto_renew is not None:
            q["extracted.auto_renew"] = auto_renew
        if renewing_within_days is not None:
            t = _today()
            q["extracted.renewal_date"] = {
                "$gte": t.isoformat(),
                "$lte": (t + timedelta(days=renewing_within_days)).isoformat(),
            }
        limit = max(1, min(limit, 50))
        total = await db.contracts.count_documents(q)
        rows = await db.contracts.find(q).sort("extracted.renewal_date", 1).limit(limit).to_list(length=limit)
        return {
            "today": _today().isoformat(),
            "matched": total,
            "shown": len(rows),
            "contracts": [_fmt_contract(r) for r in rows],
        }

    @tool
    async def get_contract_details(contract_ref: str) -> dict:
        """Full extracted fields of ONE contract. contract_ref = contract id, vendor name
        or filename. If several contracts match, candidates are returned to choose from."""
        match, cands = await _resolve(db, user_id, contract_ref)
        if match:
            return {"today": _today().isoformat(), "contract": _fmt_contract(match)}
        if cands:
            return {"ambiguous": True, "candidates": [_fmt_contract(c) for c in cands]}
        return {"found": False, "message": f"No contract of yours matches '{contract_ref}'."}

    @tool
    async def upcoming_renewals(days: int | None = None, limit: int = 5) -> dict:
        """Contracts with a renewal date today or later, SOONEST FIRST.
        days=None -> no time window (use for 'which contract is closest to renewal?').
        days=N -> only renewals within N days from today. limit = how many to return."""
        t = _today()
        rd: dict = {"$gte": t.isoformat()}
        if days is not None:
            rd["$lte"] = (t + timedelta(days=days)).isoformat()
        q = {"uploaded_by": user_id, "extracted.renewal_date": rd}
        limit = max(1, min(limit, 50))
        total = await db.contracts.count_documents(q)
        rows = await db.contracts.find(q).sort("extracted.renewal_date", 1).limit(limit).to_list(length=limit)
        passed = await db.contracts.count_documents(
            {"uploaded_by": user_id, "extracted.renewal_date": {"$lt": t.isoformat()}}
        )
        return {"today": t.isoformat(), "window_days": days, "matched": total,
                "already_passed_renewal_dates": passed,
                "contracts": [_fmt_contract(r) for r in rows]}

    @tool
    async def list_uploads(limit: int = 20) -> dict:
        """The user's uploaded documents, newest first: filename, upload time, processing
        status (uploaded/extracting/extracted/extraction_failed) and search-indexing stage.
        Use for 'what have I uploaded?' / 'did my last upload finish processing?'."""
        limit = max(1, min(limit, 50))
        total = await db.contracts.count_documents({"uploaded_by": user_id})
        rows = await db.contracts.find({"uploaded_by": user_id}).sort("uploaded_at", -1).limit(limit).to_list(length=limit)
        return {
            "total_uploads": total,
            "shown": len(rows),
            "uploads": [
                {
                    "contract_id": str(r["_id"]),
                    "filename": r.get("filename"),
                    "uploaded_at": str(r.get("uploaded_at")) if r.get("uploaded_at") else NOT_EXTRACTED,
                    "status": r.get("status"),
                    "indexing_stage": (r.get("rag") or {}).get("stage", NOT_EXTRACTED),
                    "vendor_name": (r.get("extracted") or {}).get("vendor_name") or NOT_EXTRACTED,
                }
                for r in rows
            ],
        }

    @tool
    async def reminder_status() -> dict:
        """Status of the automatic renewal-reminder emails. A nightly Airflow job emails the
        owner REMINDER_DAYS days before a contract's renewal date and records it on the
        contract. Returns reminders already sent, and contracts that are inside the reminder
        window but have not been reminded yet."""
        t = _today()
        mine = {"uploaded_by": user_id}
        sent = await db.contracts.find({**mine, "renewal_reminder_sent": True}).limit(50).to_list(length=50)
        pending = await db.contracts.find({
            **mine,
            "renewal_reminder_sent": {"$ne": True},
            "extracted.renewal_date": {
                "$gte": t.isoformat(),
                "$lte": (t + timedelta(days=REMINDER_DAYS)).isoformat(),
            },
        }).sort("extracted.renewal_date", 1).limit(50).to_list(length=50)
        return {
            "today": t.isoformat(),
            "rule": f"Airflow emails the owner {REMINDER_DAYS} days before the renewal date, once per contract.",
            "reminders_sent": [
                {**_fmt_contract(r), "reminder_sent_at": str(r.get("renewal_reminder_sent_at") or NOT_EXTRACTED)}
                for r in sent
            ],
            "in_window_not_yet_reminded": [_fmt_contract(r) for r in pending],
        }

    @tool
    async def search_contract_content(question: str, contract_ref: str | None = None) -> dict:
        """Semantic search over the TEXT of the user's contracts (clauses, termination,
        liability, obligations...). Optionally restrict to one contract (id/vendor/filename).
        Not for counts, dates or prices - use the other tools for those."""
        if contract_ref:
            match, cands = await _resolve(db, user_id, contract_ref)
            if not match:
                return {"found": False,
                        "message": f"No single contract of yours matches '{contract_ref}'.",
                        "candidates": [_fmt_contract(c) for c in cands]}
            ids = [str(match["_id"])]
        else:
            rows = await db.contracts.find({"uploaded_by": user_id}, {"_id": 1}).limit(100).to_list(length=100)
            ids = [str(r["_id"]) for r in rows]
        if not ids:
            return {"found": False, "message": "The user has no contracts yet."}

        # Chroma chunks only carry contract_id (no user_id), so ownership is enforced
        # HERE: we only ever query ids that Mongo says belong to this user.
        from retrieval.embeddings import embed_query
        from retrieval.vectorstore import get_collection

        def _search():
            vec = embed_query(question)
            return get_collection().query(
                query_embeddings=[vec], n_results=4,
                where={"contract_id": ids[0]} if len(ids) == 1 else {"contract_id": {"$in": ids}},
            )

        res = await asyncio.to_thread(_search)
        docs = res.get("documents", [[]])[0]
        dists = res.get("distances", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        hits = [
            {"contract_id": m.get("contract_id"), "distance": d, "text": t}
            for t, d, m in zip(docs, dists, metas)
            if MAX_DISTANCE is None or d <= MAX_DISTANCE
        ]
        if not hits:
            return {"found": False, "message": "No relevant passage found in the contract text."}
        return {"found": True, "passages": hits}

    return [contract_stats, list_uploads, list_contracts, get_contract_details,
            upcoming_renewals, reminder_status, search_contract_content]