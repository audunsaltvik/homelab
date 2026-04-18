FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY monitor.py .

# Create data directory for state file
RUN mkdir -p /data

# Run as non-root user
RUN useradd -m -u 1000 monitor && \
    chown -R monitor:monitor /app /data
USER monitor

CMD ["python", "-u", "monitor.py"]
