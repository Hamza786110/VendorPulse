import os
from datetime import datetime, date, timedelta
from pymongo import MongoClient
from airflow.decorators import dag, task #type:ignore

FLAG_THRESHOLD_DAYS = 30


@dag(
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["vendorpulse"],
)
def renewal_flagging_dag():

    @task
    def flag_upcoming_renewals():
        # Imported inside the task so DAG parsing (which happens on every
        # scheduler heartbeat) never has to import pymongo unless the task
        # actually runs.
        

        mongo_uri = os.environ["MONGODB_URI"]
        client = MongoClient(mongo_uri)
        db_name = os.environ.get("MONGODB_DB_NAME", "contractguard")
        db = client[db_name]
        contracts = db["contracts"]

        today = date.today()
        threshold_date = today + timedelta(days=FLAG_THRESHOLD_DAYS)
        cursor = contracts.find({"extracted.renewal_date": {"$ne": None}})

        flagged_count = 0
        unflagged_count = 0

        for contract in cursor:
            extracted = contract.get("extracted") or {}

            renewal_date_raw = extracted.get("renewal_date")
            auto_renew = extracted.get("auto_renew")
            cancellation_window_days = extracted.get("cancellation_window_days")

            if renewal_date_raw is None:
                continue
            try:
                if isinstance(renewal_date_raw, datetime):
                    renewal_date = renewal_date_raw.date()
                elif isinstance(renewal_date_raw, date):
                    renewal_date = renewal_date_raw
                else:
                    renewal_date = date.fromisoformat(str(renewal_date_raw))
            except (ValueError, TypeError) as e:
                print(f"Skipping contract {contract['_id']}: unparseable renewal_date "
                    f"{renewal_date_raw!r} ({e})")
                continue
            # MongoDB stores dates as datetime; normalize to date for comparison
            try:
                if isinstance(renewal_date_raw, datetime):
                    renewal_date = renewal_date_raw.date()
                elif isinstance(renewal_date_raw, date):
                    renewal_date = renewal_date_raw
                else:
                    renewal_date = date.fromisoformat(str(renewal_date_raw))
            except (ValueError, TypeError) as e:
                print(f"Skipping contract {contract['_id']}: unparseable renewal_date "
                    f"{renewal_date_raw!r} ({e})")
                continue

            reasons = []

            if today <= renewal_date <= threshold_date:
                days_out = (renewal_date - today).days
                reasons.append(f"Renews in {days_out} day(s)")

            if auto_renew and cancellation_window_days is not None:
                cancellation_deadline = renewal_date - timedelta(days=cancellation_window_days)
                if today <= cancellation_deadline <= threshold_date:
                    days_out = (cancellation_deadline - today).days
                    reasons.append(f"Cancellation window closes in {days_out} day(s)")

            if reasons:
                contracts.update_one(
                    {"_id": contract["_id"]},
                    {
                        "$set": {
                            "flagged": True,
                            "flag_reason": "; ".join(reasons),
                            "flagged_at": datetime.utcnow(),
                        }
                    },
                )
                flagged_count += 1
                if not contract.get("alert_sent"):
                    owner_email = get_owner_email(contract.get("uploaded_by", ""))
                if owner_email:
                    sent = notify_contract_flagged(
                        owner_email, contract.get("filename", "a contract"), flag_reason
                    )
                if sent:
                    contracts.update_one(
                        {"_id": contract["_id"]}, {"$set": {"alert_sent": True}}
                    )
                    alerts_sent += 1
            else:
                if contract.get("flagged"):
                    contracts.update_one(
                        {"_id": contract["_id"]},
                        {
                            "$set": {
                                "flagged": False,
                                "flag_reason": None,
                                "flagged_at": None,
                            }
                        },
                    )
                unflagged_count += 1

        print(f"Flagged: {flagged_count}, Unflagged/unchanged: {unflagged_count}")

    flag_upcoming_renewals()


renewal_flagging_dag()