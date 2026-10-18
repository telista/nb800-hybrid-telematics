# Dağıtım ve Alpine LXC İmaj Paketleme Araçları (`deploy/`)

Bu dizin, NetModule NB800 üzerinde çalışan **Alpine Linux LXC konteynerini** derleme, paketleme, test etme ve yerel HTTP sunucusu üzerinden yönlendiriciye aktarma betiklerini içerir.

---

## ⚠️ Önemli Ön Hazırlık: NB800 Ağ Yapılandırması (Default IP Değişimi)

NetModule NB800 yönlendiricisi fabrika çıkışında varsayılan olarak **`192.168.1.1`** IP adresine sahiptir. 

Ancak geliştirme ortamlarında ve ofis ağlarında yaygın olarak `192.168.1.0/24` alt ağı kullanıldığından (ev/ofis modemleri ile IP çakışması yaşanmaması ve LXC konteynerine temiz bir alt ağ ayrılması için), sistemimiz **`192.168.10.0/24`** bloğuna göre yapılandırılmıştır.

### Adım 1: NB800 LAN IP Adresini Güncelleyin
1. Bilgisayarınızı Ethernet kablosu ile NB800'e bağlayın.
2. Tarayıcınızdan fabrika varsayılanı olan `http://192.168.1.1` adresine gidin. *(Sıfır veya fabrika ayarlarına döndürülmüş bir cihazda ilk erişimde güvenlik standardı gereği sizden yeni bir kullanıcı adı ve güçlü bir yönetici parolası belirlemeniz istenecektir. Belirlediğiniz bu kimlik bilgileriyle giriş yapın).*
3. Sol menüden **INTERFACES -> Ethernet** (veya **Bridges**) sekmesine gidin.
4. İlgili LAN arayüzünün IP ayarlarını şu şekilde güncelleyin:
   * **IP Address:** `192.168.10.1`
   * **Netmask:** `255.255.255.0`
5. **Apply** butonuna basarak ayarları kaydedin.
6. Bilgisayarınızın Ethernet arayüzüne `192.168.10.x` bloğundan bir IP verin (Örn: `192.168.10.50`, Ağ maskesi: `255.255.255.0`, Ağ geçidi: `192.168.10.1`).
7. Artık router web arayüzüne **`http://192.168.10.1`** adresinden erişebilirsiniz.

---

## Konteyner Ağ Mimarisi

Konteyner ve router arasındaki IP haritası şu şekildedir:

* **NB800 Router (Host / Ağ Geçidi):** `192.168.10.1`
* **Dahili Mosquitto MQTT Broker:** `192.168.10.1:1883`
* **Alpine LXC Konteyneri (Statik IP):** `192.168.10.10`
* **LXC Web Teşhis Paneli:** `http://192.168.10.10:8080`

---

## Betikler ve Görevleri

### 1. `py_to_alpine.sh`
* **Görevi:** Geliştirme makinenizdeki güncel `lxc_agent` Python kaynak kodlarını, yapılandırma dosyalarını ve servis scriptlerini yerel Alpine rootfs dizininize (`$HOME/nb800-alpine/rootfs`) kopyalar. Gerekli dosya izinlerini ayarlar.
* **Kullanım:**
  ```bash
  sudo ./deploy/py_to_alpine.sh
  ```

### 2. `pack_and_serve.sh`
* **Görevi:** Hazırlanan Alpine rootfs'ini temizler (`.pyc` ve önbellek artıklarını siler), çok çekirdekli XZ algoritması (`tar -cJf ... -T0`) ile `rootfs_alpine_armhf.tar.xz` olarak sıkıştırır ve router'ın indirebilmesi için anında bir Python HTTP sunucusu (Port 8080) başlatır.
* **Kullanım:**
  ```bash
  sudo ./deploy/pack_and_serve.sh
  ```
  *Betik çalıştığında ekrana router'ın indireceği URL'yi (Örn: `http://192.168.10.50:8080/rootfs_alpine_armhf.tar.xz`) basar.*

### 3. `fix_and_pack.sh`
* **Görevi:** Rootfs içerisindeki ağ yapılandırmasını (`/etc/network/interfaces`), DNS ayarlarını (`/etc/resolv.conf`) ve açılış yöneticisini (`/etc/inittab`, `supervisord.conf`) doğrudan `192.168.10.x` bloğuna göre onarıp hızlı paketleme yapan yardımcı araçtır.
* **Kullanım:**
  ```bash
  sudo ./deploy/fix_and_pack.sh
  ```

---

## NB800 Üzerine Konteyner Kurulum Adımları

1. Geliştirici bilgisayarınızda rootfs paketini oluşturup yayına alın:
   ```bash
   sudo ./deploy/pack_and_serve.sh
   ```
2. Tarayıcıdan NB800 Web Arayüzüne girin (`http://192.168.10.1`):
   * Menüden **SERVICES -> LXC Containers** sayfasına gidin.
3. Yeni bir konteyner tanımlayın:
   * **Name:** `telemetry-agent`
   * **URL:** `pack_and_serve.sh` betiğinin ekrana bastığı URL (Örn: `http://192.168.10.50:8080/rootfs_alpine_armhf.tar.xz`)
   * **Storage:** Flash veya USB disk seçin.
4. **Install** butonuna basarak imajın router'a indirilip açılmasını sağlayın.
6. Tarayıcınızdan **`http://192.168.10.10:8080`** adresine giderek yerel Web Teşhis Paneline bağlanabilirsiniz:
   * **Kullanıcı Adı:** `admin`
   * **Şifre:** Sistemin güvenlik mantığı gereği web arayüzü şifresi `config.json` içinde tanımlı olan **`device.imei` (Modem IMEI)** numarasıdır (Varsayılan şablonda: `352255000000000`). Yalnızca IMEI alanı boş tanımlanmışsa `web.password` alanındaki şifre kullanılır.
