FROM nginx:stable-alpine
RUN apk add --no-cache tzdata && addgroup -g 1000 monitorlog && addgroup nginx monitorlog
RUN sed -i 's/worker_processes[[:space:]]*auto;/worker_processes 1;/' /etc/nginx/nginx.conf
COPY default.conf /etc/nginx/conf.d/default.conf
ENV TZ=Asia/Shanghai
