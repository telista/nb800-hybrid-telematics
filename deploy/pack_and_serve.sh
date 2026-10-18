#!/bin/bash
# ==============================================================================
# pack_and_serve.sh
# Alpine Rootfs Paketleme ve HTTP Dağıtım Sunucusu Başlatma Betiği
# ==============================================================================
#
# NE İŞE YARAR?
# ------------------------------------------------------------------------------
# 1. Alpine rootfs dizinindeki geçici emülatör dosyalarını ve Python derleme
#    artıklarını temizler.
# 2. Ağ arayüzü (/etc/network/interfaces) ve DNS ayarlarını 192.168.10.x bloğuna
#    göre güvenceye alır.
# 3. Çok çekirdekli XZ algoritmasını kullanarak rootfs'i sıkıştırır ve
#    'rootfs_alpine_armhf.tar.xz' paketini üretir.
# 4. NB800'ün ağ geçidi IP'sini (192.168.10.1) tespit ederek geliştirici makinesinin
#    yerel IP'sini belirler.
# 5. NB800 Web Arayüzünün imajı doğrudan indirebilmesi için Port 8080 üzerinde
#    yerel bir Python HTTP sunucusu başlatır ve arayüze girilecek indirme URL'sini
#    ekrana yazar.
#
# NE ZAMAN KULLANILIR?
# ------------------------------------------------------------------------------
# - 'py_to_alpine.sh' ile kodlar rootfs'e aktarıldıktan sonra,
# - Yeni veya güncellenmiş konteyner paketini oluşturup NB800'e yüklemek
#   istediğiniz her seferde çalıştırılır.
#
# NASIL KULLANILIR?
# ------------------------------------------------------------------------------
# Rootfs izinlerini ve tar işlemlerini korumak için 'sudo' ile çalıştırılmalıdır:
#
#   sudo ./deploy/pack_and_serve.sh
#
# Çalıştıktan sonra ekranda görünen URL (Örn: http://192.168.10.50:8080/rootfs_alpine_armhf.tar.xz)
# kopyalanır ve NB800 Web Arayüzünde 'Services -> LXC Containers' menüsüne yapıştırılır.
# Router indirme ve kurulumu tamamlayınca terminalde 'Ctrl + C' ile çıkılır.
# ==============================================================================
# sudo ile çalıştırıldığında gerçek kullanıcı dizinini belirle
if [ -n "$SUDO_USER" ]; then
  REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
  REAL_HOME="$HOME"
fi

if [ -d "$REAL_HOME/nb800-alpine" ]; then
  WORK_DIR="$REAL_HOME/nb800-alpine"
else
  WORK_DIR="$HOME/nb800-alpine"
fi

ROOTFS="$WORK_DIR/rootfs"
OUT_TAR="$WORK_DIR/rootfs_alpine_armhf.tar.xz"
HTTP_PORT=8080

# 1. Yetki Kontrolü
if [ "$EUID" -ne 0 ]; then
  echo "[-] Bu betik rootfs izinlerini korumak için sudo ile çalıştırılmalıdır."
  echo "    Kullanım: sudo $0"
  exit 1
fi

if [ ! -d "$ROOTFS" ]; then
  echo "[-] Hata: $ROOTFS dizini bulunamadı!"
  exit 1
fi

echo "=========================================================="
echo " [1/4] Temizlik ve İzin Kontrolleri Yapılıyor..."
echo "=========================================================="

# Geçici emülatör dosyasını temizle (varsa)
if [ -f "$ROOTFS/usr/bin/qemu-arm-static" ]; then
  rm -f "$ROOTFS/usr/bin/qemu-arm-static"
  echo " -> qemu-arm-static temizlendi."
fi

# Python önbellek (.pyc, __pycache__) artıklarını temizle
find "$ROOTFS/app" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$ROOTFS/app" -type f -name "*.pyc" -delete 2>/dev/null || true

# Ağ ayarlarını 192.168.10.x bloğuna sabitle
if [ -f "$ROOTFS/etc/network/interfaces" ]; then
  sed -i 's/192.168.1.10/192.168.10.10/g' "$ROOTFS/etc/network/interfaces" 2>/dev/null || true
  sed -i 's/192.168.1.1/192.168.10.1/g' "$ROOTFS/etc/network/interfaces" 2>/dev/null || true
fi
if [ -f "$ROOTFS/etc/resolv.conf" ]; then
  sed -i 's/192.168.1.1/192.168.10.1/g' "$ROOTFS/etc/resolv.conf" 2>/dev/null || true
fi

# Kritik izinleri garantile
chmod 755 "$ROOTFS/etc/inittab" 2>/dev/null || true
chmod 644 "$ROOTFS/etc/network/interfaces" 2>/dev/null || true
chmod -R 755 "$ROOTFS/app" 2>/dev/null || true

echo "=========================================================="
echo " [2/4] Paket Sıkıştırılıyor (Çok Çekirdekli XZ)..."
echo "=========================================================="

cd "$ROOTFS"
# -T0 tüm CPU çekirdeklerini kullanarak sıkıştırmayı çok hızlandırır
tar -cf - . | xz -9 -T0 > "$OUT_TAR"
cd - > /dev/null

FILE_SIZE=$(du -h "$OUT_TAR" | awk '{print $1}')
echo " -> Paket oluşturuldu: $OUT_TAR ($FILE_SIZE)"

echo "=========================================================="
echo " [3/4] Ağ ve URL Bilgisi Belirleniyor..."
echo "=========================================================="

# NB800 yönlendiricisine bakan IP'yi otomatik tespit et (önce 192.168.10.1, sonra 192.168.1.1)
HOST_IP=$(ip route get 192.168.10.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
if [ -z "$HOST_IP" ]; then
  HOST_IP=$(ip route get 192.168.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
fi
if [ -z "$HOST_IP" ]; then
  HOST_IP=$(hostname -I | awk '{print $1}')
fi

DOWNLOAD_URL="http://${HOST_IP}:${HTTP_PORT}/rootfs_alpine_armhf.tar.xz"

echo ""
echo " >>> NB800 WEB PANELİNE GİRİLECEK URL <<<"
echo " --------------------------------------------------------"
echo " URL: $DOWNLOAD_URL"
echo " --------------------------------------------------------"
echo ""

echo "=========================================================="
echo " [4/4] HTTP Sunucusu Başlatılıyor..."
echo "=========================================================="
echo "Router üzerinden 'Install' butonuna basmanız bekleniyor..."
echo "Router indirmeyi tamamladıktan sonra 'Ctrl + C' ile çıkabilirsiniz."
echo ""

cd "$WORK_DIR"
# Orijinal kullanıcı kimliğiyle HTTP sunucusunu ayağa kaldır (root olarak değil)
if [ -n "$SUDO_USER" ]; then
  su - "$SUDO_USER" -c "cd '$WORK_DIR' && python3 -m http.server $HTTP_PORT"
else
  python3 -m http.server $HTTP_PORT
fi
