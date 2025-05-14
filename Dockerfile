FROM mcr.microsoft.com/playwright/python:v1.51.0-noble

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Make sure Playwright browsers are installed (redundant but safe)
RUN playwright install --with-deps

# Set default envs
ENV PORT=5002
ENV HOST=0.0.0.0

# Expose port
EXPOSE 5002

# Run scraper
CMD ["python", "google_maps_scraper_sse.py"]
