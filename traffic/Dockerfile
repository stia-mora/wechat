FROM python:3.12-slim AS goaccess
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libncurses-dev zlib1g-dev curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN curl -fsSL https://tar.goaccess.io/goaccess-1.12.tar.gz -o goaccess.tgz && tar -xzf goaccess.tgz && cd goaccess-1.12 && ./configure --enable-utf8 --with-zlib && make -j2 && make install

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libncursesw6 libtinfo6 zlib1g tzdata && rm -rf /var/lib/apt/lists/* && useradd -u 1000 -m monitor
COPY --from=goaccess /usr/local/bin/goaccess /usr/local/bin/goaccess
COPY --from=goaccess /build/goaccess-1.12/COPYING /app/GOACCESS-LICENSE
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER monitor
ENV PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
