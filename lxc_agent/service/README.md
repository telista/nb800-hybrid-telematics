# LXC Telemetri Ajanı Servis ve Yapılandırma Dosyaları (`service/`)

Bu dizin, Alpine Linux LXC konteyneri içinde çalışan **`lxc_agent`** Python servisinin yapılandırma şablonunu, sistem başlatma betiğini (OpenRC) ve kurulum otomasyonunu içerir.

---

## Dosyalar ve Görevleri

### 1. `config.default.json`
`lxc_agent` servisinin varsayılan yapılandırma şablonudur. Konteyner ilk kez kurulduğunda `/etc/lxc_agent/config.json` konumuna kopyalanır.

* **Değiştirilmesi Gereken Temel Parametreler:**
  * `device.imei`: Cihazınızın modem IMEI numarası. **Önemli:** Eğer bu alan doluysa (`web_server.py` gereği), `:8080` yerel web teşhis paneline HTTP Basic Auth ile girişte kullanıcı adı `admin`, **parola ise buraya girdiğiniz IMEI numarasıdır!**
  * `web.password`: Eğer `device.imei` boş bırakılırsa web arayüzünde geçerli olacak yedek yönetici parolası.
  * `device.fleet_id` & `device.vehicle_id`: Kendi filo veya araç tanımlayıcınızı girin.
  * `remote_mqtt.enabled`: Uzak merkezi broker bağlantısını aktif etmek için `true` yapın.
  * `remote_mqtt.host`: Kendi merkezi MQTT brokerınızın (veya VPN tünel uç noktanızın) IP/Domain adresini girin.

### 2. `install.sh`
Alpine Linux konteyneri **içinde** çalıştırılan kurulum betiğidir:
* `python3`, `py3-paho-mqtt` ve `sqlite` paketlerini yükler.
* `/opt/lxc_agent`, `/etc/lxc_agent` ve `/var/lib/lxc_agent` dizinlerini açar.
* OpenRC servis dosyasını sisteme kaydeder ve açılış seviyesine (`default`) ekler.

### 3. `lxc_agent.initd`
Alpine Linux'un yerel servis yöneticisi olan **OpenRC** için servis tanımlama dosyasıdır (`/etc/init.d/lxc_agent`). 
* Servisin arka planda (`daemon`) çalışmasını, PID dosyasını ve log çıktılarını (`/var/log/lxc_agent.log`, `/var/log/lxc_agent.err`) yönetir.

---

## Servis Yönetimi ve Teşhis Komutları

Konteyner terminali içinde servisi kontrol etmek için:

```bash
# Servisi başlat
rc-service lxc_agent start

# Servisi durdur
rc-service lxc_agent stop

# Servis durumunu sorgula
rc-service lxc_agent status

# Canlı logları izle
tail -f /var/log/lxc_agent.log
```
