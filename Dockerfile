FROM node:22-alpine AS frontend

WORKDIR /frontend
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --from=frontend /frontend/dist ./web/dist
COPY migrations ./migrations

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
