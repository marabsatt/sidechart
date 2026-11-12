FROM public.ecr.aws/lambda/python:3.13

COPY backend/ibkr_event_processor/lambda_handler.py ${LAMBDA_TASK_ROOT}/lambda_handler.py

CMD ["lambda_handler.lambda_handler"]
