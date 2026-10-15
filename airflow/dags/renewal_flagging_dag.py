import os
from datetime import datetime, date, timedelta

from bson import ObjectId # type: ignore
from bson.errors import InvalidId # type: ignore
from pymongo import MongoClient # type: ignore
from airflow.decorators import dag, task  # type: ignore

# Flag a contract when its renewal date OR its cancellation deadline is
# within this many days. Override with FLAG_THRESHOLD_DAYS in .env.
FLAG_THRESHOLD_DAYS = int(os.environ.get("FLAG_THRESHOLD_DAYS", 20))


def _to_date(raw):
    """Mongo may hold a datetime, a date, or an ISO string. Returns date or None."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def evaluate_contract(extracted: dict, today: date, threshold_days: int) -> list[str]:
    """Pure function (easy to test): returns the list of reasons to flag, [] if none."""
    renewal_date = _to_date(extracted.get("renewal_date"))
    if renewal_date is None:
        return []

    threshold_date = today + timedelta(days=threshold_days)
    reasons = []

    if today <= renewal_date <= threshold_date:
        reasons.append(f"Renews in {(renewal_date - today).days} day(s) ({renewal_date})")

    window = extracted.get("cancellation_window_days")
    if extracted.get("auto_renew") and window is not None:
        deadline = renewal_date - timedelta(days=window)
        if today <= deadline <= threshold_date:
            reasons.append(
                f"Cancellation window closes in {(deadline - today).days} day(s) ({deadline})"
            )
    return reasons


def _get_owner_email(db, uploaded_by: str):
    try:
        user = db["users"].find_one({"_id": ObjectId(uploaded_by)})
    except (InvalidId, TypeError):
        return None
    return user.get("email") if user else None


@dag(
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["vendorpulse"],
)
def renewal_flagging_dag():

    @task
    def flag_upcoming_renewals():
        # Imported inside the task so DAG parsing stays light. These come from
        # the ./auth and ./contracts folders mounted in docker-compose.yml.
        from contracts.notifications import notify_contract_flagged

        client = MongoClient(os.environ["MONGODB_URI"])
        db = client[os.environ.get("MONGODB_DB_NAME", "contractguard")]
        contracts = db["contracts"]

        today = date.today()
        flagged = unflagged = emails_sent = skipped = 0

        for contract in contracts.find({"extracted.renewal_date": {"$ne": None}}):
            extracted = contract.get("extracted") or {}

            if _to_date(extracted.get("renewal_date")) is None:
                print(f"Skipping {contract['_id']}: bad renewal_date {extracted.get('renewal_date')!r}")
                skipped += 1
                continue

            reasons = evaluate_contract(extracted, today, FLAG_THRESHOLD_DAYS)

            if reasons:
                flag_reason = "; ".join(reasons)
                contracts.update_one(
                    {"_id": contract["_id"]},
                    {"$set": {"flagged": True, "flag_reason": flag_reason,
                              "flagged_at": datetime.utcnow()}},
                )
                flagged += 1

                # ONE email per contract: alert_sent is never reset by this DAG,
                # so daily runs / retries can't send duplicates.
                if not contract.get("alert_sent"):
                    owner_email = _get_owner_email(db, contract.get("uploaded_by", ""))
                    if not owner_email:
                        print(f"No owner email for {contract['_id']}, not sending")
                        continue
                    if notify_contract_flagged(owner_email, contract.get("filename", "a contract"), flag_reason):
                        contracts.update_one(
                            {"_id": contract["_id"]},
                            {"$set": {"alert_sent": True, "alert_sent_at": datetime.utcnow()}},
                        )
                        emails_sent += 1
            else:
                if contract.get("flagged"):
                    contracts.update_one(
                        {"_id": contract["_id"]},
                        {"$set": {"flagged": False, "flag_reason": None, "flagged_at": None}},
                    )
                unflagged += 1

        print(f"Flagged: {flagged}, Not flagged: {unflagged}, Emails sent: {emails_sent}, Skipped: {skipped}")

    flag_upcoming_renewals()


renewal_flagging_dag()