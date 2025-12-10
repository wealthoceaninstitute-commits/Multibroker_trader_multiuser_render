FROM python:3.11-slim

# Install minimal dependencies for headless Chrome
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libnspr4 \
    libnss3 \
    libxshmfence1 \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create workdir
WORKDIR /app

# Copy project
COPY . .

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt

# Expose port
EXPOSE 8000

# Start FastAPI
CMD ["uvicorn", "CT_FastAPI:app", "--host", "0.0.0.0", "--port", "8000"]
