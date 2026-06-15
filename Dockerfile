# Reproducible FSMRepairBench analysis environment (Python 3.12).
#
# Build:
#   docker build -t fsmrepairbench:ci -f fsmrepairbench/Dockerfile fsmrepairbench
#
# Run smoke tests:
#   docker run --rm -v "$(pwd)/paper1:/paper1" fsmrepairbench:ci \
#     bash /paper1/scripts/smoke_environment.sh

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/fsmrepairbench

COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests
COPY data ./data
COPY tools ./tools
COPY requirements-lock.txt ./

RUN pip install --upgrade pip \
    && pip install -r requirements-lock.txt \
    && pip install -e ".[dev,analytics]"

# Paper scripts are mounted at runtime; default command runs unit tests.
CMD ["pytest", "tests/", "-m", "not golden and not integration", "-q", "--tb=short"]
