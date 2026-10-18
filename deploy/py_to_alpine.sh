#!/bin/bash
# ==============================================================================
# py_to_alpine.sh
# NetModule NB800 lxc_agent Python Dosyalarını Alpine Rootfs'ine Aktarma Betiği
# ==============================================================================
#
# NE İŞE YARAR?
# ------------------------------------------------------------------------------
# Geliştirici makinenizdeki güncel 'lxc_agent' Python kaynak kodlarını, servis
# yapılandırmalarını ve başlatma betiklerini yerel Alpine Linux rootfs dizinine
# ($HOME/nb800-alpine/rootfs veya ./rootfs) kopyalar.
# Ayrıca dosya sahipliğini ve çalıştırma izinlerini (chmod 755/644) ayarlar,
# Supervisor giriş noktasını (/app/main.py) otomatik oluşturur ve gereksiz
# Python önbellek (.pyc, __pycache__) artıklarını temizler.
#
# NE ZAMAN KULLANILIR?
# ------------------------------------------------------------------------------
# - 'lxc_agent/' klasöründeki Python kodlarında (engine, storage, web_server vb.)
#   herhangi bir değişiklik veya geliştirme yaptığınızda,
# - Yeni imajı paketlemeden (pack_and_serve.sh çalıştırmadan) HEMEN ÖNCE,
#   kodların rootfs içine eksiksiz ve güncel olarak aktarılması için çalıştırılır.
#
# NASIL KULLANILIR?
# ------------------------------------------------------------------------------
# Rootfs izinlerini korumak için 'sudo' ile çalıştırılmalıdır:
#
#   sudo ./deploy/py_to_alpine.sh
#
# Çalıştıktan sonraki adım:
#   sudo ./deploy/pack_and_serve.sh
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Kaynak lxc_agent dizinini otomatik tespit et
if [ -d "${SCRIPT_DIR}/../lxc_agent" ]; then
  SRC_DIR="$(cd "${SCRIPT_DIR}/../lxc_agent" && pwd)"
elif [ -d "${SCRIPT_DIR}/lxc_agent" ]; then
  SRC_DIR="${SCRIPT_DIR}/lxc_agent"
else
  echo "[-] Hata: lxc_agent kaynak dizini bulunamadı!"
  exit 1
fi

# Hedef Alpine dizinini otomatik tespit et
if [ -d "${SCRIPT_DIR}/rootfs" ]; then
  ALPINE_DIR="${SCRIPT_DIR}"
elif [ -d "${HOME}/nb800-alpine/rootfs" ]; then
  ALPINE_DIR="${HOME}/nb800-alpine"
else
  echo "[-] Hata: nb800-alpine/rootfs dizini bulunamadı!"
  echo "    Lütfen rootfs dizininizi ${HOME}/nb800-alpine/rootfs konumuna yerleştirin."
  exit 1
fi

ROOTFS="${ALPINE_DIR}/rootfs"
APP_DIR="${ROOTFS}/app"
ETC_DIR="${ROOTFS}/etc/lxc_agent"
DATA_DIR="${ROOTFS}/var/lib/lxc_agent"

# 1. Yetki Kontrolü (Rootfs 'nobody' / root yetkileriyle korunduğu için sudo zorunludur)
if [ "$EUID" -ne 0 ]; then
  echo "[-] Hata: Rootfs dosya izinlerini yazabilmek ve korumak için lütfen sudo ile çalıştırın."
  echo "    Kullanım: sudo $0"
  exit 1
fi

# 2. Dizin Doğrulamaları
if [ ! -d "$SRC_DIR" ]; then
  echo "[-] Hata: Kaynak lxc_agent dizini bulunamadı: $SRC_DIR"
  exit 1
fi

if [ ! -d "$ROOTFS" ]; then
  echo "[-] Hata: Alpine rootfs dizini bulunamadı: $ROOTFS"
  exit 1
fi

echo "=========================================================="
echo " [1/5] Hedef Dizinler Hazırlanıyor..."
echo "=========================================================="
mkdir -p "$APP_DIR/lxc_agent"
mkdir -p "$ETC_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "${ROOTFS}/var/log/supervisor"

echo " -> $APP_DIR"
echo " -> $ETC_DIR"
echo " -> $DATA_DIR"

echo "=========================================================="
echo " [2/5] lxc_agent Modülü Kopyalanıyor..."
echo "=========================================================="
# Sadece gerekli Python modüllerini kopyala (testler ve önbellekler hariç)
MODULE_FILES=(
  "__init__.py"
  "circuit_breaker.py"
  "config.py"
  "engine.py"
  "local_mqtt.py"
  "main.py"
  "remote_mqtt.py"
  "storage.py"
  "web_server.py"
)

for file in "${MODULE_FILES[@]}"; do
  if [ -f "$SRC_DIR/$file" ]; then
    cp "$SRC_DIR/$file" "$APP_DIR/lxc_agent/$file"
    echo "  [+] Kopyalandı: lxc_agent/$file"
  else
    echo "  [!] Uyarı: $file kaynakta bulunamadı!"
  fi
done

echo "=========================================================="
echo " [3/5] Supervisor Giriş Noktası (/app/main.py) Oluşturuluyor..."
echo "=========================================================="
# /app/main.py Supervisor'ın (command=python3 -u /app/main.py) doğrudan çağırdığı launcher'dır
cat << 'EOF' > "$APP_DIR/main.py"
#!/usr/bin/env python3
"""
NetModule NB800 LXC Alpine - lxc_agent Supervisor Giriş Noktası
"""
import sys
from lxc_agent.main import main

if __name__ == "__main__":
    main()
EOF

chmod +x "$APP_DIR/main.py"
echo "  [+] $APP_DIR/main.py hazırlandı."

echo "=========================================================="
echo " [4/5] Yapılandırma Dosyası Eşleniyor..."
echo "=========================================================="
# Eğer /etc/lxc_agent/config.json yoksa varsayılanı kopyala
if [ ! -f "$ETC_DIR/config.json" ]; then
  if [ -f "$SRC_DIR/service/config.default.json" ]; then
    cp "$SRC_DIR/service/config.default.json" "$ETC_DIR/config.json"
    echo "  [+] Varsayılan yapılandırma oluşturuldu: $ETC_DIR/config.json"
  fi
else
  # Eski sablonlardan kalan broker ayarlarini gerekirse guncelle
  sed -i 's/192.168.100.1/auto/g' "$ETC_DIR/config.json" 2>/dev/null || true
  echo "  [*] Mevcut $ETC_DIR/config.json korundu."
fi

# Kolay erişim için /app/config.json sembolik bağı veya kopyası
cp -f "$SRC_DIR/service/config.default.json" "$APP_DIR/config.default.json"

echo "=========================================================="
echo " [5/5] Temizlik ve İzinler Yapılandırılıyor..."
echo "=========================================================="
# Python derleme kalıntılarını temizle
find "$APP_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$APP_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

# İzinleri ayarla
chmod -R 755 "$APP_DIR"
chmod -R 755 "$DATA_DIR"
chmod 644 "$ETC_DIR/config.json" 2>/dev/null || true

echo ""
echo "=========================================================="
echo " [BAŞARILI] lxc_agent dosyaları Alpine rootfs'ine aktarıldı!"
echo "=========================================================="
echo "Konumlar:"
echo " - Uygulama Kodu   : $APP_DIR"
echo " - Giriş Noktası   : $APP_DIR/main.py"
echo " - Yapılandırma    : $ETC_DIR/config.json"
echo " - SQLite Veri Yolu: $DATA_DIR"
echo ""
echo "Sonraki Adım: Yeni rootfs paketini oluşturup NB800'e sunmak için:"
echo "  sudo ./deploy/pack_and_serve.sh"
echo "=========================================================="
