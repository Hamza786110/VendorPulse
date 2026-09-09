FROM apache/airflow:2.10.3-python3.11

USER airflow

ENV AIRFLOW__CORE__EXECUTOR=SequentialExecutor
ENV AIRFLOW__CORE__LOAD_EXAMPLES=false

RUN pip install --no-cache-dir pymongo

CMD ["standalone"]