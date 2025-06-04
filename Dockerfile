# Izmanto Python 3.10 Ubuntu base image
FROM python:3.10-slim

# Uzstāda sistēmas dependencies (ieskaitot FFmpeg)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Izveido darba direktoriju
WORKDIR /app

# Kopē requirements failu
COPY requirements.txt .

# Instalē Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Kopē aplikācijas kodu
COPY . .

# Palaiž botu
CMD ["python", "main.py"]