# Build and run the ASPICE Analyzer API on Kubernetes
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY api/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir psycopg2-binary  # PostgreSQL adapter

# Copy application code
COPY api/ api/
COPY engine/ engine/

# Health check endpoint
HEALTHCHECK --interval=5s --timeout=2s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Expose port
EXPOSE 8000

# Run uvicorn
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
