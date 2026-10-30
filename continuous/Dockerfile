FROM python:3.12-slim
WORKDIR /app
COPY continuous/worker.py /app/worker.py
ENV PYTHONUNBUFFERED=1 PLUTO_DATA_DIR=/data
CMD ["python", "worker.py"]
