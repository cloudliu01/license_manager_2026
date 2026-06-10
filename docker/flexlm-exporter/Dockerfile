FROM golang:1.26 AS builder

WORKDIR /src
COPY third_party/flexlm_exporter/ ./
RUN go build -o /out/flexlm_exporter .

FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /out/flexlm_exporter /usr/local/bin/flexlm_exporter
COPY simulators/pyproject.toml /app/simulators/pyproject.toml
COPY simulators/src /app/simulators/src
COPY simulators/wrappers /app/simulators/wrappers
COPY docker/flexlm-exporter/lmutil /usr/local/bin/lmutil
COPY docker/flexlm-exporter/licenses.yml /etc/flexlm-exporter/licenses.yml

RUN pip install --no-cache-dir -e /app/simulators && chmod +x /usr/local/bin/lmutil

EXPOSE 9319

CMD ["flexlm_exporter", "--web.listen-address=0.0.0.0:9319", "--path.lmutil=/usr/local/bin/lmutil", "--path.config=/etc/flexlm-exporter/licenses.yml"]
