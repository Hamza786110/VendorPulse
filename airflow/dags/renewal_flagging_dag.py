import os
from datetime import datetime, date, timedelta

from bson import ObjectId # type: ignore
from bson.errors import InvalidId # type: ignore
from pymongo import MongoClient # type: ignore
from airflow.decorators import dag, task  # type: ignore
from contracts.notifications import notify_renewal_reminder
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



def evaluate_contract(extracted: dict,today: date) -> list[str]:

    renewal_date = _to_date(extracted.get("renewal_date"))

    if renewal_date is None:
        return []

    days_left = (renewal_date - today).days

    if days_left == 5:
        return [
            f"Your contract renews in 5 days "
            f"on {renewal_date}. Review it and renew if needed."
        ]
    

    return []



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
    default_args={"retries": 3, "retry_delay": 120},  # retry_delay in seconds; covers DNS/network blips
    tags=["vendorpulse"],
)
def renewal_flagging_dag():

    @task
    def flag_upcoming_renewals():
        # Imported inside the task so DAG parsing stays light. These come from
        # the ./auth and ./contracts folders mounted in docker-compose.yml.

        client = MongoClient(os.environ["MONGODB_URI"])
        db = client[os.environ.get("MONGODB_DB_NAME", "contractguard")]
        contracts = db["contracts"]

        today = date.today()
        flagged = unflagged = emails_sent = skipped = 0

        for contract in contracts.find({"extracted.renewal_date": {"$ne": None}}):
            extracted = contract.get("extracted") or {}
            message = evaluate_contract(extracted, today)

            if message and not contract.get("renewal_reminder_sent", False):
                owner_email = _get_owner_email(
                    db, contract.get("uploaded_by", "")
                )

                if not owner_email:
                    print(f"No owner email for {contract['_id']}")
                    continue

                sent = notify_renewal_reminder(
                    owner_email,
                    contract.get("filename", "a contract"),
                    message[0],
                )

                if sent:
                    contracts.update_one(
                        {"_id": contract["_id"]},
                        {
                            "$set": {
                                "renewal_reminder_sent": True,
                                "renewal_reminder_sent_at": datetime.utcnow(),
                            }
                        },
                    )


        print(f"Flagged: {flagged}, Not flagged: {unflagged}, Emails sent: {emails_sent}, Skipped: {skipped}")

    flag_upcoming_renewals()


renewal_flagging_dag()