# Araç ve Endüstriyel Telematikte Sayısal Giriş/Çıkış (DIO) Kullanım Alanları ve Senaryoları

Bu belge, NetModule NB800 ve benzeri endüstriyel telematik ağ geçitlerinde bulunan Sayısal Giriş/Çıkış (Digital Input / Output - DIO) portlarının araç içi kullanım gereksinimlerini, sektörel çözümlerini ve pratik proje senaryolarını özetler.

---

## 1. DIO Portlarının Mantığı

- **Sayısal Giriş (Digital Input - DI):**
  - Fiziksel durum değişikliklerini (0V/12V, açık/kapalı devre, buton basıldı/bırakıldı, kontak) donanım kesmesi (interrupt) seviyesinde anında algılar.
  - Event'ler: `dio-in1-on`, `dio-in1-off`, `dio-in2-on`, vb.
  - Avantajı: CAN-Bus protokolüne veya araç üreticisinin özel şifreli telemetrisine bağımlı kalmadan evrensel kuru kontak sensörleri ile çalışır.

- **Sayısal Çıkış (Digital Output - DO):**
  - Cihazın harici bir röleyi, lambayı, sireni veya güç devresini uzaktan ya da kural bazlı tetiklemesini sağlar.
  - Event/Komutlar: `dio-out1-on`, `dio-out1-off`, vb.

---

## 2. Sektörel Kullanım Alanları ve Çözülen Problemler

### 1. Toplu Taşıma, Otobüs ve Raylı Sistemler
- **Acil Durum / Panik Butonu (DI):**
  - Şoför veya yolcu panik butonuna bastığında `dio-in1-on` tetiklenir.
  - Cihaz periyodik telemetriyi beklemeden anında "ACİL DURUM" MQTT alarmı fırlatır, GPS koordinatını yüksek öncelikle merkeze bildirir ve kamera kaydını tetikler.
- **Kapı Açık/Kapalı Sensörü (DI):**
  - Kapı açıkken araç hareket ederse (GPS Hız > 5 km/s) sistem anında kural ihlali uyarısı üretir.
- **Engelli Rampası Durumu (DI):**
  - Rampanın durakta açılıp açılmadığı ve engelli yolcu iniş-biniş bekleme süresi ölçülür.
- **Yolcu Bilgilendirme / Dış Anons (DO):**
  - Belirli bir durağa yaklaşıldığında (Geofence tetiklemesi) harici ses devresi veya lamba tetiklenebilir.

### 2. Soğuk Zincir ve Gıda / İlaç Lojistiği
- **Dorse Kapak Manyetik Sensörü (DI):**
  - Sıcaklık sensörleri kapı açıldıktan belirli bir süre sonra yükselir. Kapak açıldığı an `dio-in1-on` tetiklenerek teslimat noktasında mı yoksa otoyol kenarında yetkisiz mi açıldığı anında tespit edilir.
- **Soğutucu Ünite Kontrolü (DO):**
  - Kapı açık unutulduğunda soğutucu kompresörünü otomatik durdurma veya yetkisiz açılmada siren çalma.

### 3. Acil Servis, Ambulans ve İtfaiye Araçları
- **Tepe Lambası / Siren Dedektörü (DI):**
  - Tepe lambası yandığı an `dio-in1-on` üretilir.
  - Hız sınırı muafiyeti ve idari trafik cezası itirazlarında resmi ispat sağlar (vakaya mı gidiyordu, normal seyirde miydi?).
- **Sedye Kilit Mandalı (DI):**
  - Sedye yerine oturmadan aracın hareket etmesini engellemek ya da uyarı üretmek için kullanılır.

### 4. İş Makineleri, İnşaat ve Madencilik
- **PTO (Power Take-Off / Güç Çıkışı) ve Damper Takibi (DI):**
  - Kamyon rölantide çalışırken damper kalktı mı veya mikser kazanı döndü mü?
  - Sadece kontak/motor takibi hakediş hesabı için yetersizdir. Damper kalktığında `dio-in1-on` ile "Hafriyat Dökümü Sayacı" artırılır.
- **Uzaktan Motor Blokajı / Immobilizer (DO):**
  - Mesai dışı kullanım veya çalınma şüphesinde merkezden gelen MQTT komutuyla yakıt pompası rölesi kesilir.

### 5. Belediye ve Hizmet Araçları (Çöp, Kar Küreme, Yol Süpürme)
- **Süpürge / Kar Bıçağı İndirildi Sensörü (DI):**
  - Taşeron temizlik araçlarının sokağı süpürmeden transit mi geçtiği yoksa bıçakları indirip gerçekten iş mi yaptığı doğrulanır.
- **Çöp Haznesi Kaldırma Sayacı (DI):**
  - Kaç adet çöp konteynerinin boşaltıldığını sayar.

### 6. Para Nakil ve Zırhlı Güvenlik Araçları
- **Şoför Ayak Panik Butonu & Kasa Sensörü (DI):**
  - Soygun anında şoförün fark ettirmeden merkeze sessiz alarm göndermesini sağlar.
- **Uzaktan Kasa Kilitleme / Güvenlik (DO):**
  - Geofence dışına çıkıldığında kasayı uzaktan kilitleme veya duman/gaz kapsülü patlatma.

---

## 3. Proje İçin Önerilen Simülasyon Senaryoları

1. **Olay Tetiklemeli Acil Telemetri (Event-Driven Telemetry):**
   - Normalde 30 saniyede bir çalışan telemetri döngüsü, `dio-in1-on` (ör. Panik butonu veya Kapı sensörü) geldiğinde anında kesilerek `telemetry/alarm/dio1` konusuna yüksek öncelikli paket fırlatır.
   - GPS konum gönderim sıklığı 1 saniyeye indirilerek canlı takip moduna geçilir.

2. **Merkezden Röle / Çıkış Tetikleme (Remote Output Control):**
   - Merkezden MQTT ile gelen `{"command": "set_output", "port": 1, "state": "on"}` mesajı ile cihazın DIO çıkışı tetiklenir (motor blokajı veya ikaz simülasyonu).
