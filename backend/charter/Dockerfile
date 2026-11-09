FROM public.ecr.aws/lambda/python:3.13

COPY backend/charter/requirements-lambda.txt /tmp/requirements-lambda.txt
RUN pip install --no-cache-dir -r /tmp/requirements-lambda.txt

COPY backend/charter/agent.py ${LAMBDA_TASK_ROOT}/agent.py
COPY backend/charter/lambda_handler.py ${LAMBDA_TASK_ROOT}/lambda_handler.py
COPY backend/charter/observability.py ${LAMBDA_TASK_ROOT}/observability.py
COPY backend/charter/templates.py ${LAMBDA_TASK_ROOT}/templates.py

CMD ["lambda_handler.lambda_handler"]
