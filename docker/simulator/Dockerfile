FROM python:3.11-slim

WORKDIR /app

COPY simulators/pyproject.toml /app/simulators/pyproject.toml
COPY simulators/src /app/simulators/src
COPY simulators/wrappers /app/simulators/wrappers
COPY docker/simulator/license.dat /demo/license.dat
COPY docker/simulator/start-with-seed-checkout.sh /usr/local/bin/start-with-seed-checkout

RUN pip install --no-cache-dir -e /app/simulators && chmod +x /usr/local/bin/start-with-seed-checkout

EXPOSE 27000

CMD ["/usr/local/bin/start-with-seed-checkout"]
