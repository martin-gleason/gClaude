# Dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install fastapi uvicorn
COPY src/ ./src/
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]