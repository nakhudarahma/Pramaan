FROM python:3.11-slim

WORKDIR /app

# System dependencies needed by PyMuPDF and psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose Render default port or custom port
EXPOSE 10000

ENV PORT=10000

CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-10000} --workers 2"]
