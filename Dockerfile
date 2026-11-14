FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable \
    && useradd --create-home --uid 10001 copilot \
    && mkdir /app/runs && chown copilot:copilot /app/runs
COPY data ./data
RUN chmod -R a+rX /app/data
USER copilot
EXPOSE 8000 8501
CMD ["uvicorn", "support_copilot.app:app", "--host", "0.0.0.0", "--port", "8000"]
