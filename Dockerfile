FROM python:3.12-slim

# ffmpeg/ffprobe são exigidos pela montagem do vídeo (pipeline/edicao.py)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# O Cron Job do Render sobrescreve isto pelo comando agendado.
# Padrão = canal português; use "python main.py -usa" para o canal inglês.
CMD ["python", "main.py"]
