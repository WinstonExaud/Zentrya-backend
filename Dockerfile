FROM python:3.11-slim

WORKDIR /app

# Prevent Python from writing .pyc and buffer logs (better for Docker)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (add ffmpeg + ffprobe)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    gcc \
    postgresql-client \
    chrony \
    curl \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/uploads /app/logs

# Create non-root user for security
RUN useradd -m -u 1000 zentrya && \
    chown -R zentrya:zentrya /app

USER zentrya

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run with gunicorn
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
