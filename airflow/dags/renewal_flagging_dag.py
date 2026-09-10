"""
airflow/dags/renewal_flagging_dag.py

Nightly job that scans every contract in MongoDB and flags:
  1. Contracts whose renewal_date is within FLAG_THRESHOLD_DAYS of today
  2. Contracts whose cancellation deadline (renewal_date - cancellation_window_days)
     is within FLAG_THRESHOLD_DAYS of today, when auto_renew is True

Writes back: flagged (bool), flag_reason (str | None), flagged_at (datetime | None)

This DAG does NOT upload, extract, or serve anything. It only reads contracts
that were already uploaded via FastAPI, and writes flags for the API/frontend
to surface later.
"""

import os
from datetime import datetime, date, timedelta

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
        from pymongo import MongoClient

        mongo_uri = os.environ["MONGODB_URI"]
        client = MongoClient(mongo_uri)
        db_name = os.environ.get("MONGODB_DB_NAME", "contractguard")
        db = client[db_name]
        contracts = db["contracts"]

        today = date.today()
        threshold_date = today + timedelta(days=FLAG_THRESHOLD_DAYS)

        # Only look at contracts that actually have extracted fields to check
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
            if isinstance(renewal_date_raw, datetime):
                renewal_date = renewal_date_raw.date()
            elif isinstance(renewal_date_raw, date):
                renewal_date = renewal_date_raw
            else:
                # Stored as ISO string, e.g. "2026-10-05"
                renewal_date = date.fromisoformat(str(renewal_date_raw))

            reasons = []

            # --- Check 1: renewal date itself is approaching ---
            if today <= renewal_date <= threshold_date:
                days_out = (renewal_date - today).days
                reasons.append(f"Renews in {days_out} day(s)")

            # --- Check 2: cancellation deadline is approaching ---
            # Only meaningful if the contract auto-renews and we know the window
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
            else:
                # Renewal date exists but is outside the window (either too far
                # in the future, or already in the past) -> make sure it's not
                # left flagged from a previous run.
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