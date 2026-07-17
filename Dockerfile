FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so Docker can cache this layer across builds
# that only change application code.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY policies ./policies
COPY prompts ./prompts
COPY templates ./templates
COPY static ./static

RUN useradd --create-home --shell /bin/false appuser \
    && chown -R appuser:appuser /app
USER appuser

# Cloud Run injects $PORT at runtime; default to 8080 for local `docker run`.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
