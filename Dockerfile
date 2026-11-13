# One image for the whole Python side of the project.
# The command after the image name picks the module to run, for example:
#   docker compose run --rm app                              -> extractor.cli (default)
#   docker compose run --rm app generator.cli daily          -> daily activity
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer is cached and only rebuilds when requirements change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY generator/ generator/
COPY extractor/ extractor/

ENTRYPOINT ["python", "-m"]
CMD ["extractor.cli"]
