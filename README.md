# 📊 Akıllı Kripto Trend, Destek/Direnç, Para Akışı & Vadeli İşlemler (Futures) Terminali (v8.0)

Bu proje; kripto para piyasalarında **Trend Yönü**, **Destek/Direnç Kırılımları**, **Gerçek Nakit Para Giriş/Çıkışı (Taker CVD & CMF)**, **Hacim Profili Mıknatıs Fiyatı (POC)**, **Likidasyon Havuzları** ve **⚡ Vadeli İşlemler (Perpetual Futures) Kurulum & Güven Radarı** sunan interaktif bir analiz ve karar-destek sistemidir.

---

## 🚀 Başlıca Özellikler

- **4 Kartlı Sade Analiz Ekranı (`15M`, `1H`, `4H`, `1D`):**
  1. **Mevcut Trend & Kırılımlar:** Yükselen/Düşen/Yatay trend, yukarı/aşağı kırılım eşikleri ve sıkışma durumu.
  2. **Destek, Direnç & Hedefler:** İlk ve ikinci destek/direnç seviyeleri, TP1/TP2 hedefleri ve Stop sınırı.
  3. **Para Giriş / Çıkışı & Balinalar:** Son 20 mum gerçek nakit farkı (USDT), Balina Barometresi (0–100) ve emir defteri duvarları.
  4. **Mıknatıs & Likidasyon Seviyeleri:** Hacim Mıknatısı (POC), Dip Alıcı Maliyeti (AVWAP) ve Short/Long likidasyon havuzları.
- **⚡ Vadeli İşlemler (Perpetual Futures) Kurulum & Güven Radarı:**
  - **7 Katmanlı Vadeli Denetim:** Trend, Üst Zaman Uyumu, Destek/Direnç Mesafesi (Room-to-Run), R:R Oranı, Vadeli OI/Fonlama/Taker CVD, SMC (`BOS`/`CHoCH`/`SWEEP`/Order Block) ve Testere Filtresi (`CHOP`).
  - **Güven Notu (`0–100` | `A+`, `A`, `B`, `C`, `D`):** Sadece güven notu `>= 62` ve `R:R >= 1.35` olan düşük riskli yapılarda **Yön (`LONG`/`SHORT`), Giriş Yeri, TP1/TP2/TP3, İğne Korumalı Stop Yeri ve Maks. İzole Kaldıraç** verir.
  - **Risk Kalkanı:** Teknik yapı uygun değilse veya risk yüksekse işlem önermez (`⛔ İŞLEM TAVSİYE EDİLMEZ`), giriş/hedef/stop gizlenir ve neden girilmemesi gerektiğini açıklar.
- **🤖 7/24 İnteraktif Telegram Botu (`telegram_bot.py`):**
  - Dokunmatik alt menü ve satır içi (inline) butonlar (`15M`, `1H`, `4H`, `1D` anlık geçiş, grafik fotoğrafı gönderimi, Vadeli İşlem Radarı, kasa hesaplayıcı ve fiyat alarmları).

---

## 🛠️ Kurulum ve Çalıştırma

### 1. Yerel Kurulum (Python 3.11+)
```bash
pip install -r requirements.txt

# Web Arayüzünü başlatmak için:
streamlit run app.py

# 7/24 Telegram Botunu başlatmak için:
python telegram_bot.py
```

### 2. Docker ile Tek Komutta Kurulum (Web + 7/24 Telegram Botu)
```bash
export TELEGRAM_BOT_TOKEN="BOT_TOKENINIZ"
export TELEGRAM_CHAT_ID="CHAT_IDNIZ"
docker compose up -d --build
```
- Web arayüzü: `http://localhost:8501`

---

## 📂 Proje Yapısı
- `app.py` — Streamlit Web Arayüzü ve Vadeli İşlemler Radarı
- `telegram_bot.py` — 7/24 İnteraktif Telegram Botu & Proaktif Kırılım/Fiyat Alarm Motoru
- `main.py` — Komut satırı (CLI) analiz aracı
- `src/` — Çekirdek analiz motoru (`data_fetcher.py`, `indicators.py`, `patterns.py`, `smart_money.py`, `signals.py`, `telegram_notifier.py`, `visualizer.py`)
- `tests/` — Birim testleri (`python -m unittest discover -s tests -v`)
