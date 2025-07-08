# Use Python 3.11 slim as base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libc6-dev \
    libjpeg-dev \
    libpng-dev \
    libwebp-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install uv (fast Python package installer)
RUN pip install uv

# Install Python dependencies
RUN uv sync --frozen

# Copy application code
COPY main.py ./
COPY .env.example ./

# Create backgrounds directory
RUN mkdir -p backgrounds

# Set the command to run the application
CMD ["uv", "run", "python", "main.py"]