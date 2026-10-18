#!/bin/bash
# ==============================================================================
# fix_and_pack.sh
# Alpine Rootfs Ağ, DNS, Başlatma Ayarlarını Onarma ve Hızlı Paketleme Betiği
# ==============================================================================
#
# NE İŞE YARAR?
# ------------------------------------------------------------------------------
# 1. Rootfs içindeki '/etc/network/interfaces' dosyasını doğrudan NB800 192.168.10.x
#    mimarisinde statik IP (192.168.10.10) ve gateway (192.168.10.1) ile sıfırdan yazar.
# 2. '/etc/resolv.conf' DNS dosyasını router ve genel DNS adreslerine göre onarır.
# 3. BusyBox açılış kurallarını ('/etc/inittab') ve servis yöneticisini
#    ('/etc/supervisord.conf') doğrular; /app/main.py eksikse otomatik üretir.
# 4. Geçici qemu emülatör dosyalarını temizleyip rootfs'i hızla .tar.xz olarak paketler.
#
# NE ZAMAN KULLANILIR?
# ------------------------------------------------------------------------------
# - Rootfs ağ/DNS ayarlarında bozulma olduğunda,
# - Konteyner boot sırasında ağa bağlanamadığında veya supervisord başlamadığında,
# - Manuel olarak temiz ve fabrika standartlarında bir paket üretmek istediğinizde
#   onarıcı ve hızlı paketleyici olarak çalıştırılır.
#
# NASIL KULLANILIR?
# ------------------------------------------------------------------------------
# Rootfs izinlerini düzenleyebilmek için 'sudo' ile çalıştırılmalıdır:
#
#   sudo ./deploy/fix_and_pack.sh
# ==============================================================================
set -e

if [ -n "$SUDO_USER" ]; then
  REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
  REAL_HOME="$HOME"
fi

WORK_DIR="$REAL_HOME/nb800-alpine"
ROOTFS="$WORK_DIR/rootfs"
OUT_TAR="$WORK_DIR/rootfs_alpine_armhf.tar.xz"

if [ "$EUID" -ne 0 ]; then
  echo "Lütfen bu betiği sudo ile çalıştırın: sudo $0"
  exit 1
fi

if [ ! -d "$ROOTFS" ]; then
  echo "Hata: $ROOTFS bulunamadı!"
  echo "Lütfen rootfs dizininizi $WORK_DIR/rootfs konumuna hazırlayın."
  exit 1
fi

echo "==> 1. Ağ yapılandırması (etc/network/interfaces) yazılıyor..."
cat << 'NET' > "$ROOTFS/etc/network/interfaces"
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    address 192.168.10.10
    netmask 255.255.255.0
    gateway 192.168.10.1
NET

echo "==> 2. DNS yapılandırması (etc/resolv.conf) yazılıyor..."
cat << 'DNS' > "$ROOTFS/etc/resolv.conf"
nameserver 192.168.10.1
nameserver 8.8.8.8
DNS

echo "==> 3. LXC / BusyBox açılış kuralları (etc/inittab) güncelleniyor..."
cat << 'INIT' > "$ROOTFS/etc/inittab"
# BusyBox init config for NB800 LXC container
::sysinit:/sbin/ifup -a
::respawn:/usr/bin/supervisord -n -c /etc/supervisord.conf
tty1::respawn:/bin/sh
::ctrlaltdel:/sbin/reboot
::shutdown:/sbin/ifdown -a
INIT

echo "==> 4. /app/main.py kontrol ediliyor..."
mkdir -p "$ROOTFS/app" "$ROOTFS/data" "$ROOTFS/var/log/supervisor"
if [ ! -f "$ROOTFS/app/main.py" ]; then
  cat << 'PY' > "$ROOTFS/app/main.py"
import time
print("Alpine LXC Agent container is alive and running.")
while True:
    time.sleep(30)
PY
  echo "  [+] Geçici test main.py oluşturuldu."
else
  echo "  [*] Mevcut /app/main.py korundu."
fi

echo "==> 5. Supervisor konfigürasyonu doğrulanıyor..."
cat << 'SUP' > "$ROOTFS/etc/supervisord.conf"
[unix_http_server]
file=/var/run/supervisor.sock

[supervisorctl]
serverurl=unix:///var/run/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisord]
nodaemon=true
user=root
logfile=/var/log/supervisor/supervisord.log
pidfile=/var/run/supervisord.pid

[program:lxc_agent]
command=python3 -u /app/main.py
directory=/app
autostart=true
autorestart=true
stderr_logfile=/var/log/supervisor/lxc_agent.err.log
stdout_logfile=/var/log/supervisor/lxc_agent.out.log
SUP

echo "==> 6. Varsa geçici qemu dosyası temizleniyor..."
rm -f "$ROOTFS/usr/bin/qemu-arm-static"

echo "==> 7. Paket sıkıştırılıyor: $OUT_TAR..."
cd "$ROOTFS"
tar -cJf "$OUT_TAR" *
cd - > /dev/null

echo "==> BAŞARILI! Yeni paket oluşturuldu."
ls -lh "$OUT_TAR"
