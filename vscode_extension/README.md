# VS Code Arena Dili Desteği Eklentisi (`vscode_extension/`)

Bu dizin, NetModule yönlendiricilerinde kullanılan **Arena Scripting Language** için geliştirilen özel Visual Studio Code eklentisini içerir.

Eklenti, `.are` uzantılı dosyalar için Sözdizimi Renklendirme (Syntax Highlighting), Hover Açıklamaları, Akıllı Kod Tamamlama (IntelliSense) ve Fonksiyon İmza Yardımı (Signature Help) sağlar.

---

## Yetenekler

* **Sözdizimi Renklendirme (Syntax Highlighting):** Arena dilinin anahtar kelimeleri, veri tipleri, yerleşik sabitleri ve fonksiyon çağrıları için C benzeri sözdizimi renklendirmesi.
* **Akıllı Kod Tamamlama (IntelliSense):** 400'den fazla yerleşik NetModule SDK fonksiyonu (`nb_status`, `nb_gps_*`, `nb_dio_*`, `nb_mqtt_*`, `nb_config_*` vb.) yazılırken otomatik öneri ve tamamlama.
* **Hover Dokümantasyonu:** İmleci herhangi bir Arena fonksiyonunun veya sabitinin üzerine getirdiğinizde imzasını, parametre açıklamalarını ve dönüş tipini gösteren anlık yardım penceresi.
* **İmza Yardımı (Signature Help):** Fonksiyon parametrelerini yazarken parantez derinliğine göre hangi parametrede olduğunuzu vurgulayan kılavuz.

---

## Paket Yapısı

* `package.json`: Eklenti manifest dosyası; dil tanımları ve VS Code katkı noktaları.
* `language-configuration.json`: Yorum satırları, parantez eşleşmeleri ve otomatik kapatma kuralları.
* `extension.js`: Eklentinin ana JavaScript motoru (Hover, Completion ve Signature sağlayıcıları).
* `arena_docs.json`: NetModule SDK kılavuzlarından derlenen yerleşik fonksiyon, sabit ve anahtar kelime veri tabanı.
* `syntaxes/arena.tmLanguage.json`: TextMate tabanlı sözdizimi renklendirme gramer dosyası.

---

## Kurulum ve Kullanım

Eklentiyi kendi VS Code ortamınızda aktif hale getirmek için bu klasörü yerel eklenti dizininize kopyalamanız yeterlidir:

```bash
# Eklenti klasörünü VS Code uzantı dizinine kopyalayın
cp -r vscode_extension ~/.vscode/extensions/local.arena-language-support-1.0.0
```

Kopyalama tamamlandıktan sonra VS Code'u yeniden başlattığınızda (veya açık olan pencereyi `Developer: Reload Window` ile yenilediğinizde), `.are` uzantılı tüm dosyalarda sözdizimi renklendirmesi ve akıllı kod tamamlama otomatik olarak devreye girecektir.
