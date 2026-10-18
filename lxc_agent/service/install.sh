#!/bin/sh
# ==============================================================================
# install.sh
# Alpine Linux LXC Konteyneri İçinde lxc_agent Servis Kurulum Betiği
# ==============================================================================
#
# NE İŞE YARAR?
# ------------------------------------------------------------------------------
# 1. Alpine Linux için gerekli paket bağımlılıklarını (python3, py3-paho-mqtt, sqlite)
#    'apk add' ile yükler.
# 2. Servis çalışma dizinlerini (/opt/lxc_agent, /etc/lxc_agent, /var/lib/lxc_agent)
#    ve log dizinlerini oluşturur.
# 3. 'lxc_agent' kodlarını ve varsayılan yapılandırma dosyasını yerleştirir.
# 4. OpenRC servis betiğini (/etc/init.d/lxc_agent) kaydeder ve sistem açılışına
#    (default runlevel) ekler.
#
# NE ZAMAN KULLANILIR?
# ------------------------------------------------------------------------------
# - Rootfs imajını 'deploy/' betikleriyle paketlemek yerine, temiz bir standart
#   Alpine konteyneri içinde sıfırdan terminal açarak manuel kurulum yapmak
#   istediğinizde konteynerin İÇİNDE çalıştırılır.
#
# NASIL KULLANILIR?
# ------------------------------------------------------------------------------
# Konteyner terminali içinde root yetkisiyle çalıştırılır:
#
#   sh ./lxc_agent/service/install.sh
#
# Kurulum sonrası servis kontrolleri:
#   rc-service lxc_agent start
#   rc-service lxc_agent status
#   tail -f /var/log/lxc_agent.log
# ==============================================================================
set -e

echo ">>> [1/5] Alpine Linux bağımlılıkları yükleniyor..."
apk add --no-cache python3 py3-paho-mqtt sqlite

echo ">>> [2/5] Servis dizinleri hazırlanıyor..."
mkdir -p /opt/lxc_agent
mkdir -p /etc/lxc_agent
mkdir -p /var/lib/lxc_agent
mkdir -p /var/log

echo ">>> [3/5] lxc_agent dosyaları kopyalanıyor..."
SCRIPT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cp -r "${SCRIPT_DIR}/lxc_agent" /opt/lxc_agent/

if [ ! -f /etc/lxc_agent/config.json ]; then
    cp /opt/lxc_agent/lxc_agent/service/config.default.json /etc/lxc_agent/config.json
    echo ">>> Yeni yapılandırma dosyası oluşturuldu: /etc/lxc_agent/config.json"
fi

echo ">>> [4/5] OpenRC servisi kaydediliyor..."
cp /opt/lxc_agent/lxc_agent/service/lxc_agent.initd /etc/init.d/lxc_agent
chmod +x /etc/init.d/lxc_agent

echo ">>> [5/5] Servis otomatik başlatmaya ekleniyor..."
rc-update add lxc_agent default || true

echo "=================================================================="
echo "lxc_agent kurulumu tamamlandı!"
echo "Servisi başlatmak için:"
echo "  rc-service lxc_agent start"
echo "Servis durumunu görmek için:"
echo "  rc-service lxc_agent status"
echo "Logları izlemek için:"
echo "  tail -f /var/log/lxc_agent.log"
echo "=================================================================="
