FROM python:3.12-slim

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask yt-dlp requests

WORKDIR /app
COPY . .

EXPOSE 8195

CMD ["python", "app.py"]