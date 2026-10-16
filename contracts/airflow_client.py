import os
import requests # type: ignore

def trigger_renewal_check(contract_id: str) -> None:
    url = os.getenv("AIRFLOW_API_URL", "http://airflow:8080")
    try:
        requests.post(
            f"{url}/api/v1/dags/renewal_flagging_dag/dagRuns",
            json={"conf": {"contract_id": contract_id}},
            auth=(os.getenv("AIRFLOW_API_USER", "vp_api"), os.environ["AIRFLOW_API_PASSWORD"]),
            timeout=5,
        )
    except Exception as e:
        print(f"[airflow] could not trigger check for {contract_id}: {e}")