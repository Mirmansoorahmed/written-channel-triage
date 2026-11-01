# API image for written-channel-triage (V29).
# Small, offline-friendly build: installs the package with the `api` and `models`
# extras so the FastAPI service can reach a local Ollama server. The model itself
# is NOT baked in -- it is pulled by the `ollama` service in docker-compose on
# first run.

FROM python:3.11-slim

WORKDIR /app

# Install build-time essentials only if a wheel needs them; keep the image lean.
COPY pyproject.toml ./
COPY src ./src

# Install the package with API + model-client extras.
RUN pip install --no-cache-dir -e ".[api,models]"

# Reach the ollama service by name inside the compose network.
ENV OLLAMA_HOST=http://ollama:11434

EXPOSE 8000

# Start the ASGI app.
CMD ["uvicorn", "triage.api:app", "--host", "0.0.0.0", "--port", "8000"]
