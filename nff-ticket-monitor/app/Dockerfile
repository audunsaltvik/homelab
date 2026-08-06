FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY nffmon/ ./nffmon/

# The state directory is a mount point for the shared PVC; creating it here
# with the right ownership means the container works even before the volume
# is attached (e.g. `podman run` for a local smoke test).
RUN mkdir -p /data && \
    useradd -m -u 1000 monitor && \
    chown -R monitor:monitor /app /data
USER monitor

ENTRYPOINT ["python", "-u", "-m", "nffmon"]
