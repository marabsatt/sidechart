FROM public.ecr.aws/lambda/python:3.13

COPY backend/reporter/requirements-lambda.txt /tmp/requirements-lambda.txt
RUN pip install --no-cache-dir -r /tmp/requirements-lambda.txt

COPY backend/reporter/agent.py ${LAMBDA_TASK_ROOT}/agent.py
COPY backend/reporter/judge.py ${LAMBDA_TASK_ROOT}/judge.py
COPY backend/reporter/lambda_handler.py ${LAMBDA_TASK_ROOT}/lambda_handler.py
COPY backend/reporter/observability.py ${LAMBDA_TASK_ROOT}/observability.py
COPY backend/reporter/templates.py ${LAMBDA_TASK_ROOT}/templates.py

CMD ["lambda_handler.lambda_handler"]
