# Alpine Linux LXC Telemetri Ajanı (`lxc_agent/`)

Bu dizin, NetModule NB800 içindeki **Alpine Linux LXC konteynerinde** çalışan Python 3 tabanlı telemetri motorunu barındırır.

Ajan; donanımdan (Arena betiklerinden) gelen ham verileri yerel MQTT üzerinden toplar, SQLite veritabanında tamponlar, yerel bir web teşhis paneli sunar ve güvenli VPN tüneli üzerinden merkezi IoT brokerına aktarır.

---

## Modüller ve Mimari

* **`engine.py` (Telemetri Motoru):** 
  Yerel MQTT konularına (`local/telemetry/#`, `local/event/#`) abone olur. GPS koordinatlarını, hız, yön, modem sinyal kalitesi (RSSI) ve sistem durumunu ayrıştırır, zenginleştirir ve veri akışını koordine eder.
* **`storage.py` (Store & Forward Kuyruğu):** 
  Araç tünele veya kapsama dışına çıktığında telemetri paketlerini yerel SQLite veritabanında (`store_and_forward.db`) saklar. Write-Ahead Logging (WAL) modunda çalışır ve 50 MB dairesel boyut sınırına sahiptir.
* **`circuit_breaker.py` (Devre Kesici):** 
  Uzak sunucu veya VPN bağlantısı koptuğunda sürekli başarısız bağlantı istekleriyle sistemi yormamak için geçici olarak aktarımı durdurur; bağlantı geri geldiğinde kontrollü şekilde açılır.
* **`web_server.py` (Yerel Web Teşhis Paneli):** 
  Port 8080 üzerinde çalışan hafif HTTP paneli. Saha teknisyeninin internete ihtiyaç duymadan kabin içinden sistem sağlığını, GPS verilerini ve modem durumunu izlemesini sağlar.
* **`local_mqtt.py` & `remote_mqtt.py`:** 
  Yerel Mosquitto brokerı (`192.168.10.1:1883`) ve merkezi bulut brokerı ile haberleşen MQTT istemcileri.
* **`config.py`:** 
  JSON yapılandırma dosyasını (`/etc/lxc_agent/config.json`) ve ortam değişkenlerini (Environment Variables) yöneten modül.
* **`main.py`:** 
  Tüm servis bileşenlerini asenkron ve güvenli şekilde başlatan giriş noktası.
* **`service/`:** 
  Varsayılan konfigürasyon şablonu (`config.default.json`) ve başlatma betikleri (`install.sh`, `lxc_agent.initd`).
