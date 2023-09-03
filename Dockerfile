FROM python:3.10-slim

# Install gcc for poetry
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV POETRY_VERSION = 1.6.1
RUN pip install "poetry==$POETRY_VERSION"

WORKDIR /app
COPY ./pyproject.toml /app/pyproject.toml
COPY ./poetry.lock /app/poetry.lock
COPY ./README.md /app/README.md
COPY ./shared_cache/Auto-GPT/*.json /app/shared_cache/Auto-GPT/
COPY ./shared_cache/Auto-GPT/*.csv /app/shared_cache/Auto-GPT/
COPY ./codebase_analyzer /app/codebase_analyzer

RUN poetry install

ENTRYPOINT [ \
    "poetry", "run", "codebase_analyzer", \
    "--repo-root", "./Auto-GPT/", \
    "--entry-point", "./Auto-GPT/autogpt/app/cli.py", \
    "--cache-root", "./shared_cache/Auto-GPT/", \
    "--config-path", "./config.yaml" \
]
