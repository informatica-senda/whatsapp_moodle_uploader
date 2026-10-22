FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-api.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements-api.lock \
    && useradd --system --uid 10001 --create-home appuser

COPY api_service.py course_catalog.py multicourse.py ./

EXPOSE 8000

USER 10001:10001

# TLS terminates at the trusted edge proxy. Do not trust forwarded headers in the app.
CMD ["uvicorn", "api_service:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
