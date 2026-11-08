FROM python:3.13-slim

WORKDIR /app

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    PYTHONPATH=/app:/app/src \
    PATH=/app/.venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @playwright/mcp@0.0.75 \
    && npx -y playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --python /usr/local/bin/python3.13 --frozen --no-install-project \
    && uv pip install --python .venv/bin/python awslambdaric

COPY backend/supervisor_agent/*.py ./

ENTRYPOINT ["/app/.venv/bin/python", "-m", "awslambdaric"]
CMD ["lambda_handler.lambda_handler"]
