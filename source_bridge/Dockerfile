FROM python:3.11-slim

ARG UPSTREAM_REF=043c2f9828401220a00b7b125686b334581745e0

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/tmwgsicp/wechat-download-api.git /app/ref/wechat-download-api \
    && git -C /app/ref/wechat-download-api checkout "$UPSTREAM_REF"

RUN printf 'cffi==2.1.1\ncurl_cffi==0.16.3\n' > /tmp/constraints.txt \
    && pip install --no-cache-dir -c /tmp/constraints.txt -r /app/ref/wechat-download-api/requirements.txt \
    && rm /tmp/constraints.txt

COPY source_bridge /app/source_bridge

WORKDIR /app/ref/wechat-download-api

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 5500

CMD ["uvicorn", "service:app", "--app-dir", "/app/source_bridge", "--host", "0.0.0.0", "--port", "5500"]
