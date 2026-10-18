# Arena Betikleri (NRSW Host Katmanı)

Bu dizin, NetModule NB800 yönlendiricinin yerleşik **NRSW (NetModule Router Software)** işletim sistemi üzerinde çalışan Arena (`.are`) betiklerini içerir.

Bu betikler router donanımına (GNSS, WWAN modem, sistem sıcaklığı/voltajı, SMS) doğrudan erişir ve elde ettikleri verileri yerel Mosquitto brokerına (`127.0.0.1:1883`) MQTT JSON mesajları olarak iletir.

---

## Betik Listesi ve NRSW SDK Jobs Yapılandırması

NRSW Web Arayüzünde **System -> SDK -> Scripts** menüsünden yüklenir ve **System -> SDK -> Jobs** menüsünden tetikleyicilere bağlanır.

| Betik Adı | Tetikleme Türü / Olay Kodu | Hedef MQTT Konusu | Açıklama |
| :--- | :--- | :--- | :--- |
| `telemetry_daemon.are` | **Continuous Daemon / Autostart** | `local/telemetry/gnss`<br>`local/telemetry/system`<br>`local/event/wan` | Sürekli çalışan ana arka plan servisi. Hareket halindeyken 2 sn, rölantide 30 sn periyotla konum ve sistem sağlığını okur. Ayrıca proaktif RSSI takibi yapar. |
| `on_startup.are` | **Event Trigger 505** (`system-startup`) | `local/event/system` | Router açılış sürecini tamamladığında bir kez çalışır, sistemin hazır olduğunu LXC katmanına bildirir. |
| `on_time_sync.are` | **Event Trigger 508** (`system-time-updated`) | `local/event/time` | NTP veya GPS saati doğrulandığında çalışır. LXC tarafında bekleyen 1970 etiketli verilerin geriye dönük yamalanmasını tetikler. |
| `on_wan_up.are` | **Event Trigger 101** (`wan-up`) | `local/event/wan` | Hücresel internet bağlantısı kurulduğunda çalışır (`state: up`). |
| `on_wan_down.are` | **Event Trigger 102** (`wan-down`) | `local/event/wan` | Hücresel internet koptuğunda anında çalışır (`state: down`), çevrimdışı Store-and-Forward'a geçişi tetikler. |
| `on_vpn_up.are` | **Event Trigger 401** (`openvpn-up`) | `local/event/vpn` | OpenVPN tüneli kurulup IP alındığında çalışır (`state: up`). LXC telemetri ajanının uzak broker'a (10.8.0.1) anında bağlanmasını ve kuyruğu boşaltmasını (drain) tetikler. |
| `on_vpn_down.are` | **Event Trigger 402** (`openvpn-down`) | `local/event/vpn` | OpenVPN tüneli koptuğunda çalışır (`state: down`). LXC telemetri ajanının uzak aktarımı dondurarak sıfır gecikmeyle SQLite Store-and-Forward'a geçmesini sağlar. |
| `on_gps_up.are` | **Event Trigger 301** (`gps-up`) | `local/event/gps` | GPS uydularına kilitlenildiğinde (`fix: true`) çalışır. |
| `on_gps_down.are` | **Event Trigger 302** (`gps-down`) | `local/event/gps` | Uydu kilitlenmesi kaybolduğunda (`fix: false`) çalışır. |

---

## Dinlenen Yönetim ve Komut Konuları

`telemetry_daemon.are`, LXC katmanından gelen downlink emirlerini dinler:
* `local/arena/params/set`: Seyir/rölanti okuma frekanslarını ve hız eşiğini yeniden başlatmadan çalışma anında (Hot-Reload) dinamik olarak günceller.
