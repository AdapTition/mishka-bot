FROM python:3.12-slim

# Tesseract з українською мовою — для сканів усередині PDF
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ukr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY data ./data

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "bot.main"]
