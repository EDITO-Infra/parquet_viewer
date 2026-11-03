FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY parquet_viewer ./parquet_viewer
COPY main.py ./
COPY --from=frontend-builder /frontend/dist ./frontend_dist

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "parquet_viewer.api:app", "--host", "0.0.0.0", "--port", "8000"]
