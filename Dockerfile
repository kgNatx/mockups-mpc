FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY VERSION .
COPY app/ app/

LABEL io.modelcontextprotocol.server.name="io.github.kgNatx/mockups-gallery"

EXPOSE 8000

# --proxy-headers + --forwarded-allow-ips let uvicorn trust Traefik's X-Forwarded-Proto,
# so redirects (e.g. /mcp -> /mcp/) keep the https scheme instead of downgrading to http.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
