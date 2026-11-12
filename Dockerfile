FROM python:3.12-slim

WORKDIR /app

# Sistem bağımlılıkları
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Varsayılan olarak hem Telegram Botunu arka planda hem de Streamlit Web Arayüzünü başlatır
CMD ["sh", "-c", "python telegram_bot.py & streamlit run app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true"]
