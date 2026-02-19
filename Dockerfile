FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY aletheia ./aletheia
COPY cli.py demo.py ./
COPY scripts ./scripts
COPY sql ./sql

ARG ALETHEIA_EXTRAS=""
RUN if [ -n "${ALETHEIA_EXTRAS}" ]; then \
      uv sync --frozen --no-dev --extra "${ALETHEIA_EXTRAS}"; \
    else \
      uv sync --frozen --no-dev; \
    fi

ENV PATH="/app/.venv/bin:${PATH}"

CMD ["python", "cli.py", "onboarding", "--plain"]
