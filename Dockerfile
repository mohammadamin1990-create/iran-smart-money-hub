FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLOUD_MODE=1 \
    TZ=Asia/Tehran \
    PORT=7860

RUN useradd -m -u 1000 appuser
WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=appuser:appuser . /app
RUN mkdir -p /app/state && chown -R appuser:appuser /app/state

USER appuser
EXPOSE 7860

CMD ["python", "cloud_hub/server.py"]
