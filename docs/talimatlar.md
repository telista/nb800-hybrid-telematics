```
# GÖREV: NetModule Router Arena Betik Dili İçin VS Code Eklentisinin (IntelliSense, Hover ve Autocomplete) Geliştirilmesini Devralma

Sen gömülü sistemler, derleyiciler ve VS Code eklenti mimarisi konularında uzman bir yazılım geliştiricisin. Bu görevde, NetModule yönlendiricilerinde (NRSW) kullanılan özel **Arena Scripting Language** için yerel ortamda (Linux Mint üzerinde çalışan native VS Code) başlattığımız özel eklenti altyapısını devralacak ve eksik kısımları tamamlayacaksın.

---

### 1. DİLİN TEKNİK YAPISI VE ÖZELLİKLERİ (NB_SDK_Arena_Manual)
* **Temel Yapı:** Arena, ANSI C sözdizimini (syntax) temel alan, dinamik tipli (dynamically typed) ve otomatik bellek yönetimine (otomatik çöp toplayıcı / referans sayımı) sahip hafif (lightweight) bir betik dilidir.
* **Veri Tipleri:** `void`, `bool`, `int`, `float`, `string`, `array`, `struct`, `fn`, `resource`, `mixed`.
* **Özel Anahtar Kelimeler ve Sözdizimi:**
  - `template` ve `extends`: Yapı şablonları (C++ benzeri class/struct OOP yapısı).
  - `forced`: Fonksiyon parametrelerinde ve dönüş tiplerinde otomatik tip dönüşümünü (type coercion/casting) zorunlu kılan Arena'ya özgü niteleyici.
  - `include`: Harici betik dosyalarını dahil etme.
  - `try`, `catch`, `throw`: İstisna (exception) yönetimi.
* **Standart Kütüphane:** ISO C kütüphanesi model alınmıştır:
  - Giriş/Çıkış ve Dosya: `fopen`, `fclose`, `fread`, `fwrite`, `fseek`, `printf`, `sprintf`.
  - Bellek ve İkili Veri Paketleme: `malloc`, `memset`, `mstring`, `cstring`, `cnull`, `mputint`, `mputshort`, `mputstring`.
  - Tip ve Durum Kontrolleri: `is_void`, `is_int`, `is_string`, `is_array`, `is_struct`, `strlen`.
  - Sistem: `system`, `exit`.
* **NetModule Router API (`nb_*`):** Yönlendirici donanımına ve işletim sistemine erişen özel API kütüphanesi (örn. `nb_status`, `nb_config_get`, `nb_config_set`, `nb_dio_set`, `nb_dio_get`, `nb_tcp_*`, `nb_webpage_*`).

---

### 2. ŞU ANA KADAR YAPILANLAR VE MEVCUT DOSYA YAPISI
Linux Mint ortamında, resmi `.deb` VS Code sürümünün tanıdığı eklenti dizininde tam çalışan bir eklenti paketi oluşturulmuştur.

**Eklenti Konumu:**
`~/.vscode/extensions/local.arena-language-support-1.0.0/`

Bu dizin altındaki mevcut 4 dosya ve üstlendikleri roller şunlardır:

1. **`package.json`**:
   - Eklentinin manifest dosyasıdır.
   - `publisher: "local"`, `engines: { "vscode": "^1.60.0" }` ve `main: "./extension.js"` tanımlarına sahiptir.
   - `.are` uzantılı dosyaları `arena` dil ID'si ile eşleştirir (`contributes.languages`).
   - TextMate gramer dosyasını `source.arena` kapsamına bağlar.
   - `activationEvents: ["onLanguage:arena"]` ile `.are` dosyası açıldığında eklentiyi dinamik olarak tetikler.

2. **`language-configuration.json`**:
   - Yorum satırlarını (`//` ve `/* */`), parantez eşleşmelerini (`{}`, `[]`, `()`) ve otomatik tırnak/parantez tamamlama kurallarını tanımlar.

3. **`syntaxes/arena.tmLanguage.json`**:
   - TextMate tabanlı Sözdizimi Vurgulama (Syntax Highlighting) grameridir.
   - Anahtar kelimeleri (`keyword.control.arena`), temel tipleri (`storage.type.arena`), fonksiyon çağrılarını (`support.function.arena`), kaçış karakterlerini ve sayısal ifadeleri doğru regex kalıplarıyla renklendirir.

4. **`extension.js`**:
   - `vscode.languages.registerHoverProvider('arena', ...)` kullanarak fareyle komutların üzerine gelindiğinde (Hover Tooltip) açıklama ve kullanım örneği gösteren aktif JavaScript motorudur.
   - Şu an içinde sadece 10-15 adet temel komutun dokümantasyonunu içeren sabit bir JavaScript nesnesi (`arenaDocs`) bulunmaktadır.

---

### 3. SENİN YAPMAN GEREKENLER (BEKLENEN GELİŞTİRMELER)

1. **Dokümantasyonun Modülerleştirilmesi (`arena_docs.json`):**
   - Dokümantasyon sözlüğünü `extension.js` dosyasından ayırıp harici bir `arena_docs.json` dosyasına dönüştür.
   - `extension.js` dosyasını bu JSON dosyasını dinamik olarak okuyacak şekilde refactor et.
   - Eğer fareyle üzerine gelinen bir fonksiyon sözlükte henüz yoksa, `nb_` ile başlıyorsa genel bir "NetModule Router API Fonksiyonu" şablonu, standart C/Arena fonksiyonu ise genel bir bilgi kutucuğu dönecek bir akıllı düşme (fallback) mekanizması ekle.

2. **Kapsamlı Fonksiyon ve API Veri Tabanı Oluşturma:**
   - Arena kılavuzundaki (Math, String, I/O, Memory, Type check vb.) ve NetModule SDK API'sindeki (nb_status, nb_dio_*, nb_config_*, nb_event_*, nb_cellular_*, nb_wan_*, nb_tcp_*) yüzlerce komutu kapsayacak şekilde `arena_docs.json` veri tabanını genişlet. İster hazır bir JSON listesi sağla, ister bu dokümanlardan otomatik JSON üreten bir Python ayrıştırıcı (parser) betiği ver.

3. **Otomatik Tamamlama (IntelliSense Autocomplete) Eklenmesi:**
   - `extension.js` içine `vscode.languages.registerCompletionItemProvider('arena', ...)` ekleyerek kullanıcının kod yazarken fonksiyon adlarını, anahtar kelimeleri ve hazır yapı kalıplarını (snippets) otomatik tamamlayabilmesini sağla.

4. **Parametre İpuçları (Signature Help Provider):**
   - Kullanıcı `printf(` veya `nb_status(` yazdığında hangi parametrelerin beklendiğini gösteren `registerSignatureHelpProvider` desteğini yapılandır.

Lütfen mevcut dosya yollarını (`~/.vscode/extensions/local.arena-language-support-1.0.0/`) ve çalışan yapıyı bozmadan, doğrudan uygulanabilir kod blokları ve net adımlarla geliştirmeyi devam ettir.

```