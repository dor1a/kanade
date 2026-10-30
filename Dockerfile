FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-nodeps.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps -r requirements-nodeps.txt

COPY kanade ./kanade

# /data keeps the artist name cache; a fresh named volume inherits this owner.
RUN useradd --system --uid 10001 kanade && install -d -o kanade -g kanade /data
USER kanade

CMD ["python", "-m", "kanade"]
