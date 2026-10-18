# Dokümantasyon ve Referans Kılavuzları (`docs/`)

Bu dizin, NetModule NB800 yönlendirici donanımı, NRSW işletim sistemi, Arena programlama dili ve saha kurulumlarına ilişkin teknik kılavuzları içerir.

---

## Dosya Listesi ve İçerik Haritası

### 1. Resmi NetModule Donanım ve SDK Kılavuzları (PDF & TXT)
* `NB800_Manual_5.0.0.104.pdf`: NetModule NB800 donanım özellikleri, pin şemaları, LED göstergeleri, güç gereksinimleri ve ağ arayüzleri.
* `NB_SDK_Arena_Manual_5.0.0.104.pdf` & `.txt`: Arena betik dilinin sözdizimi, veri tipleri, bellek yönetimi ve standart C kütüphane fonksiyonları.
* `NB_SDK_API_Manual_5.0.0.104.pdf`: NRSW Router SDK API referansı (`nb_*` fonksiyonları: `nb_status`, `nb_config_*`, `nb_dio_*`, `nb_mqttlib_*`, `nb_sms_*`).
* `manual_text.txt` & `api_manual_text.txt`: Kılavuzlardan `pdftotext` ile çıkarılmış, VS Code IntelliSense dokümantasyon üreticisinin kullandığı metin çıktıları.

### 2. Mimari ve Geliştirici Kılavuzları
* `arena-developer-reference-tr.pdf` & `arena-developer-reference-en.pdf`: Arena geliştiricileri için Türkçe ve İngilizce hızlı başvuru rehberleri.
* `arena_agent_mqtt.txt`: Host (NRSW) ve Konteyner (LXC) arasındaki yerel MQTT konuları, JSON şemaları ve haberleşme sözleşmesi.
* `deamons_for_nb800.txt`: NB800 üzerinde arka planda sürekli çalışan Arena servislerinin ve olay betiklerinin mimari tasarım dokümanı.
* `arena_kullanırken.txt`: Arena dilinde programlama yaparken dikkat edilmesi gereken bellek ve tip yönetimi kuralları.

### 3. Saha Kurulum ve Prosedür Dokümanları
* `sahaya_cikmadan.txt`: Cihaz sahaya çıkmadan önce yapılması gereken kontroller, varsayılan IP ve kimlik tanımlamaları.
* `talimatlar.md`: VS Code eklentisinin gereksinimleri ve mimari geliştirme hedefleri.
