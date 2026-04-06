# Stage 1: Build frontend
FROM node:20-slim AS frontend
WORKDIR /app
COPY web-ui/ web-ui/
COPY src/ramune_ida/web/frontend/ src/ramune_ida/web/frontend/
RUN cd web-ui && npm ci && npx vite build

# Stage 2: Python package + IDA
FROM ida-pro:latest

ENV TRANSPORT="http://0.0.0.0:8000"
ENV SOFT_LIMIT=4
ENV HARD_LIMIT=8
ENV RAMUNE_DATA_DIR="/data/ramune-ida"
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y git curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /opt/ramune-ida

COPY pyproject.toml uv.lock README.md hatch_build.py ./
RUN uv sync --no-install-project

COPY src/ src/
COPY --from=frontend /app/src/ramune_ida/web/frontend/ src/ramune_ida/web/frontend/
RUN uv sync

EXPOSE 8000

ENTRYPOINT ["sh", "-c", "exec uv run ramune-ida $TRANSPORT --web --soft-limit $SOFT_LIMIT --hard-limit $HARD_LIMIT"]
