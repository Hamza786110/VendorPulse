"""
End-to-end check: signup/signin -> upload -> RAG indexing -> extract
-> Airflow run appears -> ask a question -> stats.

Run from your PC (not inside Docker) while `docker compose up` is running:

    python scripts/smoke_test.py path\\to\\contract.pdf

Optional env vars:
    API_URL                 default http://localhost:8001
    AIRFLOW_URL             default http://localhost:8080
    AIRFLOW_API_USER        default vp_api
    AIRFLOW_API_PASSWORD    needed for the Airflow check (same value as .env)
    TEST_EMAIL              REQUIRED - use your own inbox; the app emails this address
    TEST_PASSWORD           default SmokeTest#12345
"""
import os
import sys
import time

import requests # type: ignore

API = os.getenv("API_URL", "http://localhost:8001")
AIRFLOW = os.getenv("AIRFLOW_URL", "http://localhost:8080")
EMAIL = os.getenv("TEST_EMAIL")
PASSWORD = os.getenv("TEST_PASSWORD", "SmokeTest#12345")

failures = []


def step(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


def main(path):
    # 1. auth (signup, or signin if the user already exists)
    creds = {"email": EMAIL, "password": PASSWORD}
    r = requests.post(f"{API}/auth/signup", json=creds, timeout=20)
    if r.status_code not in (200, 201):
        r = requests.post(f"{API}/auth/signin", json=creds, timeout=20)
    if not step("auth", r.ok, f"{r.status_code} {r.text[:120]}"):
        return
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # 2. upload
    with open(path, "rb") as f:
        r = requests.post(f"{API}/contracts/upload", headers=headers,
                          files={"file": (os.path.basename(path), f)}, timeout=60)
    if not step("upload", r.ok, f"{r.status_code} {r.text[:120]}"):
        return
    contract_id = r.json()["contract_id"]

    # 3. RAG indexing progress
    stage, seen, deadline = None, [], time.time() + 300
    while time.time() < deadline:
        r = requests.get(f"{API}/contracts/{contract_id}/rag-status", headers=headers, timeout=20)
        if r.status_code != 200:
            step("rag-status endpoint", False, f"{r.status_code} {r.text[:120]}")
            return
        info = r.json()
        stage = info["stage"]
        if not seen or seen[-1] != stage:
            seen.append(stage)
            print(f"        stage: {stage}  chunks={info.get('chunks')} dim={info.get('dim')}")
        if stage in ("done", "failed"):
            break
        time.sleep(2)
    step("indexing finished", stage == "done", f"stages seen: {' -> '.join(seen)}" +
         (f" | error: {info.get('error')}" if stage == "failed" else ""))

    # 4. extraction
    r = requests.post(f"{API}/contracts/{contract_id}/extract", headers=headers, timeout=180)
    if not step("extract", r.ok, f"{r.status_code} {r.text[:200]}"):
        return
    body = r.json()
    contract_id = body["contract_id"]  # may be the older record if it was merged as a duplicate
    if body.get("merged_into_existing"):
        print("        (merged into an existing contract for the same vendor)")
    print(f"        renewal_date = {(body.get('extracted') or {}).get('renewal_date')}")

    # 5. Airflow run for this contract appeared on its own
    pw = os.getenv("AIRFLOW_API_PASSWORD")
    if not pw:
        step("airflow run", False, "set AIRFLOW_API_PASSWORD to check this")
    else:
        auth = (os.getenv("AIRFLOW_API_USER", "vp_api"), pw)
        found, deadline = None, time.time() + 90
        while time.time() < deadline and not found:
            try:
                r = requests.get(
                    f"{AIRFLOW}/api/v1/dags/renewal_flagging_dag/dagRuns",
                    params={"order_by": "-execution_date", "limit": 10},
                    auth=auth, timeout=15)
                runs = r.json().get("dag_runs", []) if r.ok else []
            except requests.RequestException:
                runs = []
            for run in runs:
                if (run.get("conf") or {}).get("contract_id") == contract_id and \
                        run["state"] in ("success", "failed"):
                    found = run
                    break
            if not found:
                time.sleep(3)
        step("airflow run for this contract", bool(found) and found["state"] == "success",
             f"state={found['state']}" if found else "no finished run found within 90s")

    # 6. ask a question
    r = requests.get(f"{API}/contracts/{contract_id}/ask", headers=headers,
                     params={"question": "When does this contract renew?"}, timeout=60)
    step("ask", r.ok and bool(r.json().get("matches")), f"{r.status_code}")

    # 7. stats
    r = requests.get(f"{API}/contracts/stats", headers=headers, timeout=20)
    step("stats", r.ok, r.text[:200])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/smoke_test.py path/to/contract.pdf")
    if not EMAIL:
        sys.exit("Set TEST_EMAIL to your own email (the app sends notifications to it).")
    main(sys.argv[1])
    print("\nALL PASSED" if not failures else f"\nFAILED: {', '.join(failures)}")
    sys.exit(1 if failures else 0)