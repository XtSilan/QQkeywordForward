FROM node:22-alpine AS frontend

WORKDIR /frontend
COPY web/package.json web/package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com
COPY web ./
RUN npm run build

FROM python:3.12-slim

# Build metadata: compose passes APP_VERSION (git short SHA, kept up to date by
# the updater helper in .env.prod) so /api/health and the WebUI sidebar can show
# which build is actually running.
ARG APP_VERSION=dev
ARG APP_BUILD_TIME=
ENV APP_VERSION=${APP_VERSION} APP_BUILD_TIME=${APP_BUILD_TIME}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
# Default to Tsinghua (works off-Tencent-Cloud); compose/build may override
# with PIP_INDEX_URL (e.g. mirrors.tencentyun.com inside Tencent Cloud).
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" -r requirements.txt

COPY app ./app
COPY --from=frontend /frontend/dist ./web/dist
COPY migrations ./migrations

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
