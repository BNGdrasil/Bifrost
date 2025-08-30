FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/

# Create config directory
RUN mkdir -p /app/config

# Create default services configuration
RUN echo '{\n  "qshing-server": {\n    "url": "https://qshing-server.example.com",\n    "health_check": "/health",\n    "timeout": 30,\n    "rate_limit": 100\n  },\n  "hello": {\n    "url": "https://hello-service.example.com",\n    "health_check": "/health",\n    "timeout": 30,\n    "rate_limit": 100\n  }\n}' > /app/config/services.json

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "-m", "src.main"]
