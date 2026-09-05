FROM python:3.12-slim

# ffmpeg (conversão pra ogg/opus) + curl (baixar piper)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Piper (fallback offline) — binário standalone + voz pt-BR faber
RUN mkdir -p /opt && cd /opt \
    && curl -fsSL -o piper.tar.gz https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz \
    && tar -xzf piper.tar.gz && rm piper.tar.gz \
    && mkdir -p /voices \
    && curl -fsSL -o /voices/pt_BR-faber-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx \
    && curl -fsSL -o /voices/pt_BR-faber-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/

ENV PIPER_BIN=/opt/piper/piper PIPER_MODEL=/voices/pt_BR-faber-medium.onnx
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
