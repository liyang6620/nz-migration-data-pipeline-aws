FROM public.ecr.aws/lambda/python:3.12

COPY pyproject.toml README.md ${LAMBDA_TASK_ROOT}/
COPY src ${LAMBDA_TASK_ROOT}/src

RUN python -m pip install --no-cache-dir .

CMD ["nz_migration_pipeline.aws_handler.ingest_handler"]
