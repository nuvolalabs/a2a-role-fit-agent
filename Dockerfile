FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY client.py ./

# Railway/Cloud Run/Fly inject PORT; bind on all interfaces in a container.
ENV HOST=0.0.0.0 \
    PORT=8080
EXPOSE 8080

CMD ["python", "-m", "rolefit"]
