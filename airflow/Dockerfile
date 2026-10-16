FROM apache/airflow:2.10.3-python3.11

USER airflow

ENV AIRFLOW__CORE__EXECUTOR=SequentialExecutor
ENV AIRFLOW__CORE__LOAD_EXAMPLES=false
ENV AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=false
ENV AIRFLOW__API__AUTH_BACKENDS=airflow.api.auth.backend.basic_auth,airflow.api.auth.backend.session

RUN pip install --no-cache-dir pymongo python-dotenv

# CMD ["airflow","standalone"]x
CMD ["bash", "-c", "airflow db migrate && (airflow users create --username vp_api --password \"$AIRFLOW_API_PASSWORD\" --firstname v --lastname p --role Admin --email a@a.com || true) && exec airflow standalone"]
