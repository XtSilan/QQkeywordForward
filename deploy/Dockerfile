FROM python:3.12-alpine

# docker CLI + compose + buildx plugins: the throwaway helper drives the host
# daemon through /var/run/docker.sock to run `docker compose build && up -d`.
RUN apk add --no-cache git docker-cli docker-cli-compose docker-cli-buildx

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" -r requirements.txt

COPY app.py update_run.py ./
COPY updater ./updater

ENV PYTHONUNBUFFERED=1 \
    PROJECT_DIR=/project \
    UPDATER_PORT=18081

EXPOSE 18081

CMD ["python", "-u", "app.py"]
