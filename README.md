# NetModule NB800 Hibrit Telemetri & Edge Computing Referans Mimarisi

Bu repo, **NetModule NB800** endüstriyel yönlendiricisi üzerinde çalışan **Arena Dili (NRSW Host)** ve **Python 3 (Alpine Linux LXC Konteyneri)** hibrit telemetri ve uç bilişim (Edge Computing) mimarisini içerir.

Bu projeyi, NetModule cihazları için Arena dilinde uygulama geliştirmek isteyen mühendis ve entegratörlerin işini kolaylaştırmak amacıyla hazırladık. Örnek uygulama olarak bir **Filo Yönetimi / Araç Telemetrisi** senaryosunu ele aldık; geliştiricilerin kolayca temin edip deneyebilmesi için en kompakt ve ekonomik model olan **NB800**'ü seçtik.


> **Donanım ve SDK Uyumluluk Notu:**
> Arena programlama dili sözdizimi ve geliştirdiğimiz VS-Code eklentisi tüm NetModule serileri (NB800, NB1600, NB2800, NB3800 vb.) için ortaktır. Ancak yönlendiricilerin üzerindeki fiziksel donanımlar (modem adedi, sayısal I/O sayısı, Ethernet/PoE desteği vb.) seriden seriye farklılık gösterdiğinden, NetModule SDK API yetenekleri modele bağlı olarak değişebilir.
> Bu repo, serinin en kompakt ve ekonomik üyesi olan **NB800** donanımına (tek modem, 2x DI/DO) göre hazırlanmıştır. Buradaki mimari ve kodlar NB2800 (otobüs) veya NB3800 (raylı sistem) gibi üst serilere doğrudan uyarlanabilir; ancak üst serilerin özel donanımlarına (ikinci modem, PoE yönetimi vb.) yönelik geliştirilen kodlar donanım kısıtları nedeniyle NB800 üzerinde çalışmayacaktır.

---

## Mimari Özeti

Sistem iki temel katmandan ve bu katmanları birbirine bağlayan dahili bir MQTT veri yolundan oluşur:

1. **NRSW Host Katmanı (Arena Betikleri):**
   * NetModule'ün kendi işletim sistemi çekirdeğinde çalışır.
   * Donanıma doğrudan erişir (`nb_*` SDK API'leri).
   * GNSS (GPS) ve WWAN (4G modem) sistem olaylarını mikro saniyeler seviyesinde yakalar.
   * Elde ettiği ham telemetriyi yerel MQTT broker'a (`127.0.0.1:1883`) aktarır.

2. **Alpine Linux LXC Konteyner Katmanı (`lxc_agent`):**
   * NB800 içinde izole bir Linux konteyneri olarak çalışır.
   * Python 3 tabanlı telemetri motorudur (`engine.py`).
   * **Tünel & Kapsama Dışı Güvencesi:** GSM koptuğunda verileri SQLite WAL modunda (`store_and_forward.db`) saklar; hat geldiğinde Circuit Breaker ile merkeze sıralı aktarır.
   * **Yerel Teşhis Web Paneli (:8080):** Saha teknisyeninin internete çıkmadan kabin içinden sistem sağlığını, GPS verilerini ve modem durumunu izlemesini sağlar.
   * **Siber Güvenlik & Güvenli Uplink:** Telemetri akışı, doğrudan genel internete değil; **yalnızca güvenli bir VPN tüneli (OpenVPN/IPsec)** üzerinden merkezi IoT broker'ına aktarılır.

```
+-------------------------------------------------------------------------+
|                       NetModule NB800 Cihazı                            |
|                                                                         |
|   [NRSW Host Katmanı]                                                   |
|   GNSS / LTE / DIO / SMS  ---> Arena Betikleri ---> [Yerel MQTT]        |
|                                                          |              |
|   [Alpine Linux LXC Katmanı]                             | (1883)       |
|   Python lxc_agent <-------------------------------------+              |
|     ├── SQLite Store & Forward (50 MB Tampon)                           |
|     ├── Yerel Web Teşhis Paneli (Port 8080)                             |
|     └── Güvenli Uplink (Sadece VPN Üzerinden) ---> [Merkezi IoT Broker] |
+-------------------------------------------------------------------------+
```

---

## Dizin Yapısı

```
.
├── vscode_extension/   # VS Code Arena Dili Desteği (Syntax Highlighting & IntelliSense)
├── arena_scripts/      # NB800 üzerinde çalışan Arena (.are) olay ve daemon betikleri
├── lxc_agent/          # Alpine LXC konteynerinde çalışan Python telemetri servisi
├── deploy/             # Alpine rootfs paketleme ve router'a HTTP ile sunma araçları
└── docs/               # Mimari notlar, geliştirici referansları ve saha kılavuzları
```

---

## 1. VS Code Arena Eklentisi (`vscode_extension/`)

Arena dilinde kod geliştirmeyi modern bir IDE konforuna taşımak için geliştirdiğimiz VS Code eklentisidir:
* **Sözdizimi Renklendirme:** `.are` dosyaları için C benzeri sözdizimi renklendirmesi.
* **IntelliSense & Dokümantasyon:** 400'den fazla yerleşik NetModule fonksiyonu (`nb_status`, `nb_gps_*`, `nb_mqtt_*`, `nb_sms_*`) için hover açıklamaları, parametre ipuçları ve otomatik tamamlama.

### Kurulum:
`vscode_extension/` klasörünü yerel VS Code eklentileri dizininize kopyalamanız yeterlidir:
```bash
cp -r vscode_extension ~/.vscode/extensions/local.arena-language-support-1.0.0
```
VS Code'u yeniden başlattığınızda `.are` uzantılı dosyalarda tüm yetenekler aktifleşir.

---

## 2. Arena Betikleri (`arena_scripts/`)

NB800 Web GUI üzerinden **Services -> SDK -> Job Management** menülerinden tetiklenen mikro betikler:

| Betik Adı | Tetiklenme Nedeni | Açıklama |
| :--- | :--- | :--- |
| `on_startup.are` | Sistem Başlangıcı | Modemi, GPS'i ve yerel servisleri hazırlar. |
| `telemetry_daemon.are` | Periyodik (Daemon) | GPS, hız, yön ve modem sinyalini okuyup yerel MQTT'ye basar. |
| `on_gps_up.are` | GPS Fix Alındı | İlk geçerli konum fix'ini merkeze bildirir. |
| `on_gps_down.are` | GPS Sinyali Kesildi | Tünel/kapalı alan durumunu yerel sisteme duyurur. |
| `on_wan_up.are` / `down.are` | Hücresel Veri Durumu | 4G bağlantısı koptuğunda/geldiğinde sistemi uyarır. |
| `on_vpn_up.are` / `down.are` | VPN Tüneli Durumu | Güvenli tünel kurulduğunda kuyruk tahliyesini tetikler. |

---

## 3. Python LXC Telemetri Ajanı (`lxc_agent/`)

Alpine Linux konteyneri içinde çalışan servis bileşenleri:
* `engine.py`: Yerel MQTT'yi dinleyip verileri işler ve zenginleştirir.
* `storage.py`: SQLite WAL modunda çalışan dairesel Store-and-Forward kuyruğu.
* `circuit_breaker.py`: Uzak VPN/Broker koptuğunda sistemi koruyan ve gereksiz ağ trafiğini önleyen devre kesici.
* `web_server.py`: Port 8080 üzerinde çalışan hafif web teşhis arayüzü.
* `remote_mqtt.py`: Sadece VPN tüneli üzerinden güvenli merkezi broker iletişimi.

---

## 4. Nasıl Deneyebilirsiniz?

1. Bu repoyu bilgisayarınıza klonlayın.
2. `vscode_extension` klasörünü VS Code'a yükleyerek Arena betiklerini inceleyin veya düzenleyin.
3. **Ağ Ön Hazırlığı:** NB800 fabrika çıkışı `192.168.1.1` IP'si ile gelir. Konteyner mimarimizin çalışabilmesi için router LAN IP'sini `192.168.10.1` olarak güncelleyin (Detaylar: [`deploy/README.md`](deploy/README.md)).
4. Kendi merkezi VPN / MQTT broker adreslerinizi `lxc_agent/service/config.default.json` içine tanımlayın.
5. `deploy/` altındaki araçlarla Alpine rootfs paketini oluşturup NB800 cihazınıza yükleyin (Sıfırdan armhf rootfs indirme, paket kurma ve dağıtım rehberi için: [`deploy/README.md`](deploy/README.md)).

---

## NB800 Temini ve Mühendislik Desteği

NetModule donanımları hakkında detaylı bilgi almak, projenize uygun konfigürasyonu belirlemek ve bir adet test cihazı satın almak için bizimle iletişime geçebilirsiniz:

* **Web:** [https://www.telista.com.tr](https://www.telista.com.tr)
* **İletişim:** info@telista.com.tr
