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

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-install-project --extra worker

COPY src/ src/
RUN uv sync --extra worker

EXPOSE 8000

ENTRYPOINT ["sh", "-c", "exec uv run ramune-ida $TRANSPORT --soft-limit $SOFT_LIMIT --hard-limit $HARD_LIMIT"]
