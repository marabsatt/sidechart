FROM public.ecr.aws/lambda/python:3.13

COPY backend/planner/requirements-lambda.txt /tmp/requirements-lambda.txt
RUN pip install --no-cache-dir -r /tmp/requirements-lambda.txt

COPY backend/planner/agent.py ${LAMBDA_TASK_ROOT}/agent.py
COPY backend/planner/lambda_handler.py ${LAMBDA_TASK_ROOT}/lambda_handler.py
COPY backend/planner/market.py ${LAMBDA_TASK_ROOT}/market.py
COPY backend/planner/observability.py ${LAMBDA_TASK_ROOT}/observability.py
COPY backend/planner/prices.py ${LAMBDA_TASK_ROOT}/prices.py
COPY backend/planner/templates.py ${LAMBDA_TASK_ROOT}/templates.py

CMD ["lambda_handler.lambda_handler"]
