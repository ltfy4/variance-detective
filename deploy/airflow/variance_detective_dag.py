"""Airflow DAG: run the monthly investigation on working day 3 after close and publish the report.

Assumes the image from the repo Dockerfile is available and the workspace is a mounted volume
or synced to object storage afterwards.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator

KPIS = ["gross_margin", "net_sales", "cogs"]

with DAG(
    dag_id="variance_detective_monthly",
    start_date=datetime(2026, 1, 1),
    schedule="0 6 3-5 * 1-5",  # 06:00 on the 3rd–5th, weekdays; guard WD3 logic in a sensor if needed
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=10)},
    tags=["fp&a", "agents"],
) as dag:
    for kpi in KPIS:
        DockerOperator(
            task_id=f"investigate_{kpi}",
            image="variance-detective:latest",
            command=f"vd investigate --kpi {kpi} --period {{{{ macros.ds_format(ds, '%Y-%m-%d', '%Y-%m') }}}} --source sac",
            environment={"VD_LLM__PROVIDER": "bedrock", "VD_LLM__MODEL": "anthropic.claude-sonnet-4-5-20250929-v1:0", "AWS_REGION": "eu-west-2"},
            mounts=[],  # add a Mount for /app/workspace
            auto_remove="success",
        )
