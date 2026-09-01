# Dockerfile
FROM python:3.11-slim AS rtkbuild
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch demo5 https://github.com/rtklibexplorer/RTKLIB.git /rtklib \
    && make -C /rtklib/app/consapp/rtkrcv/gcc -j"$(nproc)"

FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY web ./web
COPY config.yaml.example ./config.yaml.example
COPY --from=rtkbuild /rtklib/app/consapp/rtkrcv/gcc/rtkrcv /usr/local/bin/rtkrcv
CMD ["python", "-m", "rtk_monitor.main", "/data/config.yaml"]
