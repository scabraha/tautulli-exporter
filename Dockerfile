# syntax=docker/dockerfile:1.24

FROM python:3.13-alpine AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.13-alpine
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN addgroup -S exporter && adduser -S -G exporter exporter
WORKDIR /app
COPY --from=builder /install /usr/local
COPY tautulli_exporter ./tautulli_exporter
USER exporter
EXPOSE 9487
ENTRYPOINT ["python", "-m", "tautulli_exporter"]
