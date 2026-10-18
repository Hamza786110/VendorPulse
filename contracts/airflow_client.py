import os
import requests # type: ignore

def trigger_renewal_check(contract_id: str) -> None:
    url = os.getenv("AIRFLOW_API_URL", "http://airflow:8080")
    password = os.getenv("AIRFLOW_API_PASSWORD")
    if not password:
        print("[airflow] AIRFLOW_API_PASSWORD is not set in .env; "
              f"cannot trigger renewal check for {contract_id}")
        return
    try:
        resp=requests.post(
            f"{url}/api/v1/dags/renewal_flagging_dag/dagRuns",
            json={"conf": {"contract_id": contract_id}},
            auth=(os.getenv("AIRFLOW_API_USER", "vp_api"), os.environ["AIRFLOW_API_PASSWORD"]),
            timeout=5,
        )
        if resp.status_code>=300:
            print(f"[airflow] trigger for {contract_id} failed: " f"{resp.status_code} {resp.text[:200]}")
        else:
            print(f"[airflow] triggered renewal check for {contract_id}")
    except Exception as e:
        print(f"[airflow] could not trigger check for {contract_id}: {e}")