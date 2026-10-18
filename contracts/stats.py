"""
contracts/stats.py

Numbers for the dashboard (and later the chatbot's contract_stats tool).
All counts are for ONE user's contracts only.
"""
from datetime import datetime, timedelta, timezone

from contracts.models import ContractStatus

_ALL_STATUSES = [
    ContractStatus.UPLOADED,
    ContractStatus.EXTRACTING,
    ContractStatus.EXTRACTED,
    ContractStatus.EXTRACTION_FAILED,
]


async def get_contract_stats(db, user_id: str, upcoming_days: int = 30) -> dict:
    mine = {"uploaded_by": user_id}

    # contracts per processing status (every status is present, even at 0)
    by_status = {s: 0 for s in _ALL_STATUSES}
    async for row in db.contracts.aggregate(
        [{"$match": mine}, {"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    ):
        by_status[row["_id"]] = row["count"]

    total = sum(by_status.values())

    # renewal_date is stored as an ISO "YYYY-MM-DD" string, so string
    # comparison works for date ranges.
    today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=upcoming_days)
    upcoming = await db.contracts.count_documents(
        {
            **mine,
            "extracted.renewal_date": {"$gte": today.isoformat(), "$lte": cutoff.isoformat()},
        }
    )
    reminders_sent = await db.contracts.count_documents(
        {**mine, "renewal_reminder_sent": True}
    )

    return {
        "total": total,
        "by_status": by_status,
        f"renewing_in_next_{upcoming_days}_days": upcoming,
        "reminders_sent": reminders_sent,
    }