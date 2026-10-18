"""
lxc_agent - Dahili Teşhis ve Dosya İndirme Web Sunucusu (Built-in Diagnostics Web Server)
Sıfır harici bağımlılık (Python standart http.server).
Canlı telemetri dashboard'u, durum API'si ve tek tıkla SQLite WAL veritabanı / log indirme desteği.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from .engine import TelemetryEngine

logger = logging.getLogger("lxc_agent.web_server")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NetModule NB800 - lxc_agent Teşhis Paneli</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-color: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #38bdf8;
            --success: #22c55e;
            --warning: #f59e0b;
            --danger: #ef4444;
            --border: #334155;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background-color: var(--bg-color); color: var(--text-color); padding: 20px; line-height: 1.5; }
        .container { max-width: 1100px; margin: 0 auto; }
        header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 15px; margin-bottom: 25px; }
        .logo-area h1 { font-size: 1.5rem; color: var(--primary); }
        .logo-area span { font-size: 0.85rem; color: var(--text-muted); }
        .badge { padding: 4px 10px; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
        .badge-success { background-color: rgba(34, 197, 94, 0.2); color: var(--success); border: 1px solid var(--success); }
        .badge-danger { background-color: rgba(239, 68, 68, 0.2); color: var(--danger); border: 1px solid var(--danger); }
        .badge-warning { background-color: rgba(245, 158, 11, 0.2); color: var(--warning); border: 1px solid var(--warning); }
        .badge-info { background-color: rgba(56, 189, 248, 0.2); color: var(--primary); border: 1px solid var(--primary); }
        .form-input:disabled { background: #1e293b; color: #94a3b8; cursor: not-allowed; border-color: rgba(255,255,255,0.1); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; margin-bottom: 25px; }
        .card { background-color: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; padding: 20px; }
        .card-title { font-size: 1.1rem; margin-bottom: 15px; color: var(--primary); display: flex; justify-content: space-between; align-items: center; }
        .stat-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
        .stat-label { color: var(--text-muted); font-size: 0.9rem; }
        .stat-value { font-weight: 600; font-size: 0.95rem; }
        
        .actions-card { background: linear-gradient(135deg, #1e293b, #0f172a); border: 1px solid var(--primary); border-radius: 10px; padding: 20px; margin-bottom: 25px; }
        .btn-group { display: flex; gap: 15px; flex-wrap: wrap; margin-top: 15px; }
        .btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px; border-radius: 6px; font-weight: 600; text-decoration: none; cursor: pointer; transition: all 0.2s; font-size: 0.9rem; border: none; }
        .btn-primary { background-color: #0284c7; color: white; }
        .btn-primary:hover { background-color: #0369a1; }
        .btn-secondary { background-color: #475569; color: white; }
        .btn-secondary:hover { background-color: #334155; }
        .btn-danger { background-color: #ef4444; color: white; }
        .btn-danger:hover { background-color: #dc2626; }

        .mgmt-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; margin-bottom: 25px; }
        .card-danger { border: 1px solid rgba(239, 68, 68, 0.4); background: linear-gradient(180deg, #1e293b, rgba(239,68,68,0.05)); }
        .form-row { margin-bottom: 12px; }
        .form-label { display: block; font-size: 0.85rem; color: var(--text-muted); margin-bottom: 5px; }
        .form-input { width: 100%; background: #0f172a; border: 1px solid var(--border); color: #fff; padding: 8px 12px; border-radius: 6px; font-size: 0.95rem; }
        .form-input:focus { outline: none; border-color: var(--primary); }
        .feedback { font-size: 0.85rem; margin-top: 8px; display: block; min-height: 1.2rem; }
        .feedback-success { color: var(--success); }
        .feedback-error { color: var(--danger); }

        /* Toggle Switch */
        .switch-container { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border); border-radius: 8px; margin: 12px 0; }
        .switch-label-area { display: flex; flex-direction: column; }
        .switch-title { font-weight: 600; font-size: 0.95rem; color: #f8fafc; }
        .switch-desc { font-size: 0.8rem; color: var(--text-muted); margin-top: 3px; }
        .switch { position: relative; display: inline-block; width: 50px; height: 26px; flex-shrink: 0; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #475569; transition: .3s; border-radius: 26px; }
        .slider:before { position: absolute; content: ""; height: 20px; width: 20px; left: 3px; bottom: 3px; background-color: white; transition: .3s; border-radius: 50%; }
        input:checked + .slider { background-color: #22c55e; }
        input:checked + .slider:before { transform: translateX(24px); }
        
        .footer { text-align: center; color: var(--text-muted); font-size: 0.8rem; margin-top: 30px; }
        .refresh-indicator { font-size: 0.8rem; color: var(--text-muted); display: inline-flex; align-items: center; gap: 6px; }
        .dot { width: 8px; height: 8px; border-radius: 50%; background-color: var(--success); display: inline-block; animation: pulse 2s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-area">
                <h1>NetModule NB800</h1>
                <span>Alpine LXC lxc_agent Canlı Teşhis Paneli</span>
            </div>
            <div class="refresh-indicator">
                <span class="dot"></span> Canlı Otomatik Güncelleme (5s)
            </div>
        </header>

        <div class="actions-card">
            <h2 style="font-size: 1.2rem; color: var(--primary);">📥 Depolama & Dosya İndirme Merkezi</h2>
            <p style="color: var(--text-muted); font-size: 0.9rem; margin-top: 5px;">
                Store-and-Forward kuyruğundaki veriler SQLite WAL formatında tutulur. İndir butonuna tıkladığınızda güncel kayıtlar birleştirilerek (.db) dosyanız indirilir.
            </p>
            <div class="btn-group">
                <a href="/download/db" class="btn btn-primary">
                    💾 store_and_forward.db İndir
                </a>
                <a href="/download/log" class="btn btn-secondary">
                    📄 lxc_agent.log İndir
                </a>
                <a href="/api/status" target="_blank" class="btn btn-secondary">
                    🔍 Ham JSON API
                </a>
            </div>
        </div>

        <div class="grid">
            <!-- Sistem & Donanım Sağlığı -->
            <div class="card">
                <div class="card-title">
                    <span>⚡ Router Sağlık Durumu</span>
                    <span id="badge-health" class="badge badge-success">AKTİF</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Araç Kimliği:</span>
                    <span class="stat-value" id="val-vehicle-id">-</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Filo ID:</span>
                    <span class="stat-value" id="val-fleet-id">-</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Modem IMEI:</span>
                    <span class="stat-value" id="val-imei" style="font-family: monospace; letter-spacing: 0.5px;">-</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Hücresel Sinyal (WWAN RSSI):</span>
                    <span class="stat-value" id="val-rssi">- dBm</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Besleme Voltajı:</span>
                    <span class="stat-value" id="val-voltage">- V</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">RAM Kullanımı (Konteyner):</span>
                    <span class="stat-value" id="val-memory">-</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Çalışma Süresi (Uptime):</span>
                    <span class="stat-value" id="val-uptime">-</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">İşlemci Sıcaklığı:</span>
                    <span class="stat-value" id="val-temp">- °C</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Donanım Gözetmeni (HYDRA):</span>
                    <span class="stat-value" id="val-hydra" style="color: var(--success); font-weight: bold; text-transform: uppercase;">-</span>
                </div>
            </div>

            <!-- GNSS & Konum -->
            <div class="card">
                <div class="card-title">
                    <span>🛰️ GNSS / Konum Durumu</span>
                    <span id="badge-gps" class="badge badge-warning">BEKLENİYOR</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Kilitlenme (Fix):</span>
                    <span class="stat-value" id="val-gps-fix">Yok</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Enlem (Latitude):</span>
                    <span class="stat-value" id="val-lat">0.000000</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Boylam (Longitude):</span>
                    <span class="stat-value" id="val-lon">0.000000</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Yer Hızı:</span>
                    <span class="stat-value" id="val-speed">0.0 km/h</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Aktif Uydular:</span>
                    <span class="stat-value" id="val-satellites">0</span>
                </div>
            </div>

            <!-- Ağ & MQTT Durumu -->
            <div class="card">
                <div class="card-title">
                    <span>🌐 Ağ ve MQTT Veri Yolu</span>
                    <span id="badge-wan" class="badge badge-success">WAN UP</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Hücresel WAN:</span>
                    <span class="stat-value" id="val-wan-state">up</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">OpenVPN Tüneli:</span>
                    <span class="stat-value" id="val-vpn-state">bilinmiyor</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Dahili Broker (Mosquitto):</span>
                    <span class="stat-value" id="val-local-broker" style="color: var(--success);">Bağlı</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Uzak Broker:</span>
                    <span class="stat-value" id="val-remote-broker">-</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Zaman Senkronu (NTP/GNSS):</span>
                    <span class="stat-value" id="val-time-synced">Evet</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Bekleyen SQLite Kuyruğu:</span>
                    <span class="stat-value" id="val-queue-count" style="color: var(--warning);">0 paket</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Veritabanı Boyutu:</span>
                    <span class="stat-value" id="val-db-size">0 KB</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Arena Frekansı (Seyir/Rölanti):</span>
                    <span class="stat-value" id="val-arena-cadence" style="color: var(--primary);">2s / 30s</span>
                </div>
            </div>
        </div>

        <!-- Saha Yönetim & Güvenlik Paneli -->
        <div class="mgmt-grid">
            <!-- Cihaz & Filo Kimliği Güncelleme -->
            <div class="card">
                <div class="card-title">
                    <span>🏷️ Saha Kimlik Tanımlama</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 12px;">
                    Cihazın takıldığı araca göre Plaka ve Filo bilgisini güncelleyin. Değişiklik kalıcı olarak kaydedilir ve çalışma anında uygulanır.
                </p>
                <div class="form-row">
                    <label class="form-label" for="input-vehicle-id">Araç Kimliği / Plaka:</label>
                    <input type="text" id="input-vehicle-id" class="form-input" placeholder="Örn: NB800-34-ABC-123">
                </div>
                <div class="form-row">
                    <label class="form-label" for="input-fleet-id">Filo ID:</label>
                    <input type="text" id="input-fleet-id" class="form-input" placeholder="Örn: filo-ist-01">
                </div>
                <button type="button" onclick="saveDeviceConfig()" class="btn btn-primary" style="width: 100%; justify-content: center; margin-top: 5px;">
                    💾 Kimliği Kaydet
                </button>
                <span id="feedback-config" class="feedback"></span>
            </div>

            <!-- Arena Telemetri Frekans Ayarları -->
            <div class="card" id="card-arena-params">
                <div class="card-title">
                    <span>⏱️ Arena Telemetri Frekansları</span>
                    <span id="badge-arena-status" class="badge badge-success">OTOMATİK</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 12px;">
                    NRSW üzerindeki <code>telemetry_daemon.are</code> betiğinin okuma sıklığını yeniden başlatmadan (Hot-Reload) değiştirin.
                </p>
                <div id="alert-arena-locked" style="display: none; background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.3); border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; font-size: 0.82rem; color: #86efac;">
                    🔒 <strong>Tasarruf Modu Etkin:</strong> Frekanslar hücresel veri tasarrufuna göre otomatik optimize edilmiştir (5s / 60s). Özel frekans girmek için Tasarruf Modunu kapatabilirsiniz.
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <div class="form-row">
                        <label class="form-label" for="input-interval-moving">Seyir Aralığı (sn):</label>
                        <input type="number" id="input-interval-moving" min="1" max="3600" class="form-input" placeholder="5">
                    </div>
                    <div class="form-row">
                        <label class="form-label" for="input-interval-idle">Rölanti Aralığı (sn):</label>
                        <input type="number" id="input-interval-idle" min="1" max="86400" class="form-input" placeholder="60">
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <div class="form-row">
                        <label class="form-label" for="input-speed-threshold">Hız Eşiği (km/h):</label>
                        <input type="number" step="0.1" id="input-speed-threshold" min="0" max="250" class="form-input" placeholder="5.0">
                    </div>
                    <div class="form-row">
                        <label class="form-label" for="input-max-storage">Depo Kotası (MB):</label>
                        <input type="number" id="input-max-storage" min="1" max="500" class="form-input" placeholder="50">
                    </div>
                </div>
                <button type="button" id="btn-save-arena" onclick="saveArenaParams()" class="btn btn-primary" style="width: 100%; justify-content: center; margin-top: 5px;">
                    💾 Frekans Ayarlarını Uygula
                </button>
                <span id="feedback-arena" class="feedback"></span>
            </div>

            <!-- Hücresel Veri & Maliyet Optimizasyonu -->
            <div class="card">
                <div class="card-title">
                    <span>📶 Hücresel Veri & Maliyet Optimizasyonu</span>
                    <span id="badge-opt-status" class="badge badge-success">AKTİF</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 8px;">
                    Hücresel kota ve hat maliyeti yönetimi. Tasarruf modu devredeyken telemetri frekansları dinamik olarak optimize edilerek (seyir 5s, rölanti 60s) hücresel veri tüketiminde yüksek oranda tasarruf sağlanır. Bütçe kısıtlaması olmayan durumlarda anahtar kapatılarak standart frekansta (seyir 2s, rölanti 30s) akış sağlanabilir.
                </p>
                <div class="switch-container">
                    <div class="switch-label-area">
                        <span class="switch-title" id="opt-mode-title">Tasarruf Modu (Optimizasyon Açık)</span>
                        <span class="switch-desc" id="opt-mode-desc">Seyir 5s, Rölanti 60s &bull; Dinamik Frekans Optimizasyonu</span>
                    </div>
                    <label class="switch">
                        <input type="checkbox" id="toggle-optimization" onchange="toggleOptimization(this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>
                <div class="stat-row" style="border-top: 1px solid rgba(255,255,255,0.05); margin-top: 6px;">
                    <span class="stat-label">Tahmini Hücresel Tasarruf:</span>
                    <span class="stat-value" id="val-opt-savings" style="color: var(--success);">~%60 Tasarruf</span>
                </div>
                <span id="feedback-optimization" class="feedback"></span>
            </div>

            <!-- Tehlikeli Bölge / Kuyruk Temizleme -->
            <div class="card card-danger">
                <div class="card-title">
                    <span style="color: var(--danger);">⚠️ Depo Sıfırlama (Danger Zone)</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 12px;">
                    Sahaya çıkış öncesi test kayıtlarını veya kuyrukta birikmiş çevrimdışı telemetri verilerini kalıcı olarak siler ve disk alanını geri kazanır.
                </p>
                <div style="background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.2); border-radius: 6px; padding: 10px; margin-bottom: 15px; font-size: 0.85rem; color: #fca5a5;">
                    Dikkat: Henüz merkeze aktarılmamış tüm kuyruk silinir. Bu işlem geri alınamaz!
                </div>
                <button type="button" onclick="purgeQueue()" class="btn btn-danger" style="width: 100%; justify-content: center;">
                    🗑️ Kuyruktaki Verileri Sil (Purge)
                </button>
                <span id="feedback-purge" class="feedback"></span>
            </div>
        </div>

        <div class="footer">
            NetModule NB800 Hybrid Architecture &bull; NRSW Arena Host &bull; Alpine Linux LXC Agent
        </div>
    </div>

    <script>
        let initialPopulated = false;

        async function updateDashboard() {
            try {
                const res = await fetch('/api/status');
                if (!res.ok) return;
                const data = await res.json();

                // Cihaz
                const vId = data.device.vehicle_id || '-';
                const fId = data.device.fleet_id || '-';
                const imei = data.device.imei || '-';
                document.getElementById('val-vehicle-id').innerText = vId;
                document.getElementById('val-fleet-id').innerText = fId;
                const elImei = document.getElementById('val-imei');
                if (elImei) elImei.innerText = imei;

                // Form girişlerini ilk açılışta doldur
                if (!initialPopulated) {
                    const inputV = document.getElementById('input-vehicle-id');
                    const inputF = document.getElementById('input-fleet-id');
                    if (inputV && !inputV.value && vId !== '-') inputV.value = vId;
                    if (inputF && !inputF.value && fId !== '-') inputF.value = fId;
                    initialPopulated = true;
                }

                // Sistem
                if (data.system) {
                    const rssi = data.system.wwan_signal_rssi;
                    document.getElementById('val-rssi').innerText = rssi ? `${rssi} dBm` : '0 dBm';
                    const volt = data.system.voltage_mv ? (data.system.voltage_mv / 1000).toFixed(1) : '12.0';
                    document.getElementById('val-voltage').innerText = `${volt} V`;
                    const elMem = document.getElementById('val-memory');
                    if (elMem) {
                        const ramText = data.system.ram_text;
                        const memPct = data.system.memory_usage_pct;
                        if (ramText && ramText !== '-') {
                            elMem.innerText = ramText;
                        } else if (memPct !== undefined && memPct !== null && memPct > 0) {
                            elMem.innerText = `${memPct}%`;
                        } else {
                            elMem.innerText = '-';
                        }

                        if (memPct >= 80) {
                            elMem.style.color = 'var(--danger)';
                        } else if (memPct >= 65) {
                            elMem.style.color = 'var(--warning)';
                        } else {
                            elMem.style.color = 'var(--text-color)';
                        }
                    }
                    
                    const upSec = data.system.uptime_sec || 0;
                    const hours = Math.floor(upSec / 3600);
                    const mins = Math.floor((upSec % 3600) / 60);
                    document.getElementById('val-uptime').innerText = `${hours} sa ${mins} dk (${upSec}s)`;

                    const temp = data.system.cpu_temperature;
                    const elTemp = document.getElementById('val-temp');
                    if (elTemp) {
                        elTemp.innerText = (temp !== undefined && temp !== null) ? `${temp} °C` : '-';
                    }

                    const hydra = data.system.hydra || '-';
                    const elHydra = document.getElementById('val-hydra');
                    if (elHydra) {
                        elHydra.innerText = hydra.toUpperCase();
                        if (hydra.toLowerCase() === 'happy') {
                            elHydra.style.color = 'var(--success)';
                        } else if (hydra !== '-') {
                            elHydra.style.color = 'var(--warning)';
                        }
                    }
                }

                // GNSS
                if (data.gnss) {
                    const fix = data.gnss.fix;
                    document.getElementById('val-gps-fix').innerText = fix ? 'Var (2D/3D)' : 'Yok (Arama)';
                    const badgeGps = document.getElementById('badge-gps');
                    if (fix) {
                        badgeGps.className = 'badge badge-success';
                        badgeGps.innerText = 'KİLİTLENDİ';
                    } else {
                        badgeGps.className = 'badge badge-warning';
                        badgeGps.innerText = 'BEKLENİYOR';
                    }
                    document.getElementById('val-lat').innerText = data.gnss.latitude ? data.gnss.latitude.toFixed(6) : '0.000000';
                    document.getElementById('val-lon').innerText = data.gnss.longitude ? data.gnss.longitude.toFixed(6) : '0.000000';
                    document.getElementById('val-speed').innerText = `${data.gnss.speed_kmh || 0.0} km/h`;
                    document.getElementById('val-satellites').innerText = data.gnss.satellites || 0;
                }

                // Ağ & Depolama
                document.getElementById('val-wan-state').innerText = data.network.wan_state.toUpperCase();
                const badgeWan = document.getElementById('badge-wan');
                if (data.network.wan_state === 'up') {
                    badgeWan.className = 'badge badge-success';
                    badgeWan.innerText = 'WAN UP';
                } else {
                    badgeWan.className = 'badge badge-danger';
                    badgeWan.innerText = 'WAN DOWN';
                }

                const vpnState = (data.network.vpn_state || 'unknown').toLowerCase();
                const elVpn = document.getElementById('val-vpn-state');
                if (elVpn) {
                    elVpn.innerText = vpnState.toUpperCase();
                    if (vpnState === 'up') {
                        elVpn.style.color = 'var(--success)';
                    } else if (vpnState === 'down') {
                        elVpn.style.color = 'var(--danger)';
                    } else {
                        elVpn.style.color = 'var(--text-muted)';
                    }
                }

                document.getElementById('val-local-broker').innerText = data.network.local_mqtt_connected ? 'Bağlı (1883)' : 'Kopuk';
                const elRemote = document.getElementById('val-remote-broker');
                if (elRemote) {
                    if (data.network.remote_mqtt_connected) {
                        elRemote.innerText = 'Bağlı (Uplink Aktif)';
                        elRemote.style.color = 'var(--success)';
                    } else {
                        elRemote.innerText = 'Kopuk / Devre Dışı';
                        elRemote.style.color = 'var(--danger)';
                    }
                }
                document.getElementById('val-time-synced').innerText = data.time_synced ? 'Senkronize' : 'Doğrulama Bekleniyor';

                // Depo
                document.getElementById('val-queue-count').innerText = `${data.storage.queue_count} kayıt`;
                const sizeKb = Math.round(data.storage.storage_bytes / 1024);
                document.getElementById('val-db-size').innerText = sizeKb > 1024 ? `${(sizeKb/1024).toFixed(2)} MB` : `${sizeKb} KB`;

                // Arena Parametreleri
                if (data.arena_params) {
                    const mSec = data.arena_params.publish_interval_moving_sec || 2;
                    const iSec = data.arena_params.publish_interval_idle_sec || 30;
                    const spd = data.arena_params.speed_threshold_kmh || 5.0;
                    const stMb = data.arena_params.max_storage_mb || 50;

                    const cadenceElem = document.getElementById('val-arena-cadence');
                    if (cadenceElem) cadenceElem.innerText = `${mSec}s / ${iSec}s`;

                    const inputM = document.getElementById('input-interval-moving');
                    const inputI = document.getElementById('input-interval-idle');
                    const inputS = document.getElementById('input-speed-threshold');
                    const inputSt = document.getElementById('input-max-storage');
                    if (inputM && document.activeElement !== inputM) inputM.value = mSec;
                    if (inputI && document.activeElement !== inputI) inputI.value = iSec;
                    if (inputS && document.activeElement !== inputS && !window.arenaPopulated) inputS.value = spd;
                    if (inputSt && document.activeElement !== inputSt && !window.arenaPopulated) inputSt.value = stMb;
                    window.arenaPopulated = true;
                }

                // Hücresel Optimizasyon
                if (data.optimization) {
                    const optEnabled = data.optimization.enabled;
                    const optToggle = document.getElementById('toggle-optimization');
                    if (optToggle && document.activeElement !== optToggle) {
                        optToggle.checked = optEnabled;
                    }
                    const badgeOpt = document.getElementById('badge-opt-status');
                    const titleOpt = document.getElementById('opt-mode-title');
                    const descOpt = document.getElementById('opt-mode-desc');
                    const valSavings = document.getElementById('val-opt-savings');
                    const mSec = (data.arena_params && data.arena_params.publish_interval_moving_sec) || (optEnabled ? 5 : 2);
                    const iSec = (data.arena_params && data.arena_params.publish_interval_idle_sec) || (optEnabled ? 60 : 30);

                    if (badgeOpt) {
                        if (optEnabled) {
                            badgeOpt.className = 'badge badge-success';
                            badgeOpt.innerText = 'AKTİF';
                            const savPct = data.optimization.savings_pct !== undefined ? data.optimization.savings_pct : 60;
                            if (titleOpt) titleOpt.innerText = `Tasarruf Modu (~%${savPct} Tasarruf)`;
                            if (descOpt) descOpt.innerText = `Seyir ${mSec}s, Rölanti ${iSec}s • Dinamik Frekans Optimizasyonu`;
                            if (valSavings) {
                                valSavings.innerText = `~%${savPct} Tasarruf`;
                                valSavings.style.color = 'var(--success)';
                            }
                        } else {
                            const savPct = data.optimization.savings_pct !== undefined ? data.optimization.savings_pct : 0;
                            badgeOpt.className = 'badge badge-warning';
                            badgeOpt.innerText = 'DEVRE DIŞI';
                            if (titleOpt) titleOpt.innerText = savPct > 0 ? `Manuel Yönetim (~%${savPct} Tasarruf)` : 'Sınırsız Bütçe (Maksimum Akış)';
                            if (descOpt) descOpt.innerText = `Seyir ${mSec}s, Rölanti ${iSec}s • Standart Akış Modu`;
                            if (valSavings) {
                                if (savPct > 0) {
                                    valSavings.innerText = `~%${savPct} Tasarruf (Özel Frekans)`;
                                    valSavings.style.color = 'var(--primary)';
                                } else {
                                    valSavings.innerText = '%0 (Maksimum Veri & Maliyet)';
                                    valSavings.style.color = 'var(--warning)';
                                }
                            }
                        }
                    }

                    // Arena Frekans Kartı Kilit / Dinamik Durum Yönetimi
                    const badgeArena = document.getElementById('badge-arena-status');
                    const alertLocked = document.getElementById('alert-arena-locked');
                    const inputM = document.getElementById('input-interval-moving');
                    const inputI = document.getElementById('input-interval-idle');
                    const btnSaveArena = document.getElementById('btn-save-arena');

                    if (optEnabled) {
                        if (badgeArena) {
                            badgeArena.className = 'badge badge-success';
                            badgeArena.innerText = 'OTOMATİK (TASARRUF)';
                        }
                        if (alertLocked) alertLocked.style.display = 'block';
                        if (inputM) inputM.disabled = true;
                        if (inputI) inputI.disabled = true;
                        if (btnSaveArena) {
                            btnSaveArena.disabled = true;
                            btnSaveArena.innerText = '🔒 Tasarruf Modunda Kilitli (5s / 60s)';
                        }
                    } else {
                        if (badgeArena) {
                            badgeArena.className = 'badge badge-info';
                            badgeArena.innerText = 'MANUEL YÖNETİM';
                        }
                        if (alertLocked) alertLocked.style.display = 'none';
                        if (inputM) inputM.disabled = false;
                        if (inputI) inputI.disabled = false;
                        if (btnSaveArena) {
                            btnSaveArena.disabled = false;
                            btnSaveArena.innerText = '💾 Frekans Ayarlarını Uygula';
                        }
                    }
                }

            } catch (err) {
                console.error('Veri güncelleme hatası:', err);
            }
        }

        async function toggleOptimization(enabled) {
            const feedback = document.getElementById('feedback-optimization');
            feedback.className = 'feedback';
            feedback.style.color = '#38bdf8';
            feedback.innerText = enabled ? 'Tasarruf Modu etkinleştiriliyor...' : 'Sınırsız Bütçe Moduna geçiliyor...';

            try {
                const res = await fetch('/api/config/optimization', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: enabled })
                });
                const result = await res.json();
                if (res.ok && result.success) {
                    feedback.className = 'feedback feedback-success';
                    feedback.innerText = enabled
                        ? '✓ Tasarruf Modu uygulandı (%65 kota tasarrufu devrede).'
                        : '✓ Sınırsız Bütçe Modu uygulandı (Maksimum veri akışı devrede).';
                    updateDashboard();
                } else {
                    feedback.className = 'feedback feedback-error';
                    feedback.innerText = `Hata: ${result.error || 'Uygulanamadı'}`;
                }
            } catch (err) {
                feedback.className = 'feedback feedback-error';
                feedback.innerText = `Bağlantı hatası: ${err.message}`;
            }
            setTimeout(() => { feedback.innerText = ''; }, 4000);
        }

        async function saveDeviceConfig() {
            const vehicleId = document.getElementById('input-vehicle-id').value.trim();
            const fleetId = document.getElementById('input-fleet-id').value.trim();
            const feedback = document.getElementById('feedback-config');

            if (!vehicleId || !fleetId) {
                feedback.className = 'feedback feedback-error';
                feedback.innerText = 'Lütfen Araç Kimliği ve Filo ID alanlarını doldurun.';
                return;
            }

            feedback.className = 'feedback';
            feedback.style.color = '#38bdf8';
            feedback.innerText = 'Kaydediliyor...';

            try {
                const res = await fetch('/api/config/device', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vehicle_id: vehicleId, fleet_id: fleetId })
                });
                const result = await res.json();
                if (res.ok && result.success) {
                    feedback.className = 'feedback feedback-success';
                    feedback.innerText = '✓ Başarıyla kaydedildi ve uygulandı.';
                    updateDashboard();
                } else {
                    feedback.className = 'feedback feedback-error';
                    feedback.innerText = `Hata: ${result.error || 'Kaydedilemedi'}`;
                }
            } catch (err) {
                feedback.className = 'feedback feedback-error';
                feedback.innerText = `Bağlantı hatası: ${err.message}`;
            }
            setTimeout(() => { feedback.innerText = ''; }, 4000);
        }

        async function saveArenaParams() {
            const moving = document.getElementById('input-interval-moving').value.trim();
            const idle = document.getElementById('input-interval-idle').value.trim();
            const speed = document.getElementById('input-speed-threshold').value.trim();
            const storage = document.getElementById('input-max-storage').value.trim();
            const feedback = document.getElementById('feedback-arena');

            const optToggle = document.getElementById('toggle-optimization');
            if (optToggle && optToggle.checked) {
                feedback.className = 'feedback feedback-error';
                feedback.innerText = 'Tasarruf Modu etkinken frekanslar kilitlidir. Değiştirmek için Tasarruf Modunu kapatın.';
                setTimeout(() => { feedback.innerText = ''; }, 4000);
                return;
            }

            if (!moving || !idle) {
                feedback.className = 'feedback feedback-error';
                feedback.innerText = 'Lütfen seyir ve rölanti aralıklarını belirtin.';
                return;
            }

            feedback.className = 'feedback';
            feedback.style.color = '#38bdf8';
            feedback.innerText = 'Arena parametreleri iletiliyor...';

            try {
                const res = await fetch('/api/config/arena_params', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        publish_interval_moving_sec: parseInt(moving),
                        publish_interval_idle_sec: parseInt(idle),
                        speed_threshold_kmh: parseFloat(speed || 5.0),
                        max_storage_mb: parseInt(storage || 50)
                    })
                });
                const result = await res.json();
                if (res.ok && result.success) {
                    feedback.className = 'feedback feedback-success';
                    feedback.innerText = '✓ Arena parametreleri uygulandı (Hot-Reload).';
                    updateDashboard();
                } else {
                    feedback.className = 'feedback feedback-error';
                    feedback.innerText = `Hata: ${result.error || 'Uygulanamadı'}`;
                }
            } catch (err) {
                feedback.className = 'feedback feedback-error';
                feedback.innerText = `Bağlantı hatası: ${err.message}`;
            }
            setTimeout(() => { feedback.innerText = ''; }, 4000);
        }

        async function purgeQueue() {
            const countText = document.getElementById('val-queue-count').innerText;
            const feedback = document.getElementById('feedback-purge');

            const confirmed = confirm(
                `⚠️ DİKKAT!\\n\\nStore-and-Forward kuyruğundaki tüm kayıtlar (${countText}) kalıcı olarak silinecektir.\\n\\nDevam etmek istediğinize emin misiniz?`
            );
            if (!confirmed) return;

            feedback.className = 'feedback';
            feedback.style.color = '#38bdf8';
            feedback.innerText = 'Kuyruk temizleniyor...';

            try {
                const res = await fetch('/api/queue/clear', { method: 'POST' });
                const result = await res.json();
                if (res.ok && result.success) {
                    feedback.className = 'feedback feedback-success';
                    feedback.innerText = `✓ Tamamlandı: ${result.deleted_count} kayıt silindi.`;
                    updateDashboard();
                } else {
                    feedback.className = 'feedback feedback-error';
                    feedback.innerText = `Hata: ${result.error || 'Temizlenemedi'}`;
                }
            } catch (err) {
                feedback.className = 'feedback feedback-error';
                feedback.innerText = `Bağlantı hatası: ${err.message}`;
            }
            setTimeout(() => { feedback.innerText = ''; }, 4000);
        }

        updateDashboard();
        setInterval(updateDashboard, 5000);
    </script>
</body>
</html>
"""


class DiagnosticsHandler(BaseHTTPRequestHandler):
    """Teşhis HTTP isteklerini karşılayan işleyici."""

    # Sunucu motor referansı sınıf seviyesinde atanır
    engine: Optional[TelemetryEngine] = None

    def log_message(self, format: str, *args: Any) -> None:
        """Terminal çıktısını sessiz tutmak için debug seviyesine çekilir."""
        logger.debug("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)

    def check_auth(self) -> bool:
        """HTTP Basic Authentication kontrolü."""
        if not self.engine:
            return True

        config = self.engine.config
        auth_enabled = (
            getattr(config.web, "auth_enabled", True)
            if hasattr(config, "web")
            else getattr(config, "web_auth_enabled", True)
        )
        if not auth_enabled:
            return True

        auth_header = self.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Basic "):
            self._send_auth_required()
            return False

        try:
            encoded = auth_header.split(" ", 1)[1].strip()
            decoded = base64.b64decode(encoded).decode("utf-8")
            if ":" not in decoded:
                self._send_auth_required()
                return False
            user, pwd = decoded.split(":", 1)

            expected_user = (
                getattr(config.web, "username", "admin")
                if hasattr(config, "web")
                else getattr(config, "web_username", "admin")
            )
            configured_pwd = (
                getattr(config.web, "password", "")
                if hasattr(config, "web")
                else getattr(config, "web_password", "")
            )
            device_imei = (
                getattr(config.device, "imei", "").strip()
                if hasattr(config, "device")
                else ""
            )

            # Giriş şifresi KESİNLİKLE cihazın GSM Modem IMEI numarasıdır.
            # IMEI henüz tanımlı değilse config.web.password veya "admin" fallback uygulanır.
            if device_imei:
                expected_pwd = device_imei
            else:
                expected_pwd = (
                    getattr(config.web, "password", "admin")
                    if hasattr(config, "web")
                    else getattr(config, "web_password", "admin")
                )

            if hmac.compare_digest(user, expected_user) and hmac.compare_digest(pwd, expected_pwd):
                return True
        except Exception as e:
            logger.debug("Kimlik doğrulama çözme hatası: %s", e)

        self._send_auth_required()
        return False

    def _send_auth_required(self) -> None:
        """401 Unauthorized yanıtı döner ve tarayıcı giriş kutusunu tetikler."""
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="NetModule NB800 (Password is IMEI)"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        body = json.dumps(
            {
                "error": "Unauthorized",
                "message": "Yetkilendirme gerekli. Lütfen kullanıcı adı 'admin' ve şifre olarak cihaz IMEI numarasını girin.",
            }
        ).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self.check_auth():
            return

        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self._serve_dashboard()
        elif path == "/api/status":
            self._serve_status_api()
        elif path == "/download/db":
            self._serve_database_download()
        elif path == "/download/log":
            self._serve_log_download()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Sayfa bulunamadi")

    def do_POST(self) -> None:
        if not self.check_auth():
            return

        path = self.path.split("?")[0]

        if path == "/api/config/device":
            self._handle_config_device()
        elif path == "/api/config/arena_params":
            self._handle_config_arena_params()
        elif path == "/api/config/optimization":
            self._handle_config_optimization()
        elif path == "/api/queue/clear":
            self._handle_queue_clear()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "API ucu bulunamadi")

    def _serve_dashboard(self) -> None:
        content = HTML_TEMPLATE.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_status_api(self) -> None:
        if not self.engine:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Motor hazir degil")
            return

        eng = self.engine
        storage = eng.storage

        # Hücresel Tasarruf Oranı Dinamik Hesabı:
        # Baz referans (Fabrika/Maksimum Akış): Seyir 2s, Rölanti 30s ve her döngüde çift paket (Telemetri + Health)
        # 1 saatlik baz maliyet referansı (Standart akış: Seyir 2s, Rölanti 30s):
        # Seyir (%70 kabulü): 2520 sn / 2s = 1260 paket
        # Rölanti (%30 kabulü): 1080 sn / 30s = 36 paket
        # Toplam standart akış: 1296 paket/saat
        curr_moving = eng.arena_params.get("publish_interval_moving_sec", 5 if getattr(eng, "data_optimization_enabled", True) else 2)
        curr_idle = eng.arena_params.get("publish_interval_idle_sec", 60 if getattr(eng, "data_optimization_enabled", True) else 30)
        curr_moving = max(1, curr_moving)
        curr_idle = max(1, curr_idle)
        
        opt_enabled = getattr(eng, "data_optimization_enabled", True)
        curr_total = (2520 / curr_moving) + (1080 / curr_idle)
        if getattr(eng, "publish_health", False):
            curr_total += 3600 / getattr(eng, "health_interval_sec", 60)

        base_total = 1296.0
        calculated_savings = int(round(max(0.0, min(95.0, (1.0 - (curr_total / base_total)) * 100.0))))

        if opt_enabled:
            mode_text = f"Tasarruf Modu (~%{calculated_savings} Tasarruf)"
        else:
            mode_text = f"Manuel Yönetim (~%{calculated_savings} Tasarruf)" if calculated_savings > 0 else "Manuel Yönetim (Standart Akış)"

        status_data = {
            "device": {
                "vehicle_id": eng.config.device.vehicle_id,
                "fleet_id": eng.config.device.fleet_id,
                "imei": eng.config.device.imei,
            },
            "network": {
                "wan_state": eng.wan_state,
                "vpn_state": getattr(eng, "vpn_state", "unknown"),
                "gps_state": eng.gps_state,
                "local_mqtt_connected": eng.local_mqtt.is_connected,
                "remote_mqtt_connected": eng.remote_mqtt.is_connected if eng.remote_mqtt else False,
            },
            "time_synced": eng.time_synced,
            "gnss": eng._last_gnss_data,
            "system": eng._last_system_data,
            "arena_params": getattr(eng, "arena_params", {}),
            "optimization": {
                "enabled": opt_enabled,
                "health_interval_sec": getattr(eng, "health_interval_sec", 60),
                "publish_health": getattr(eng, "publish_health", False),
                "savings_pct": calculated_savings,
                "mode_text": mode_text,
            },
            "storage": {
                "queue_count": storage.count(),
                "storage_bytes": storage.get_total_storage_bytes(),
                "db_path": str(storage.db_path),
            },
            "timestamp": int(time.time()),
        }

        content = json.dumps(status_data, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_database_download(self) -> None:
        if not self.engine:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Motor hazir degil")
            return

        storage = self.engine.storage
        # İndirme öncesi WAL günlüğündeki verileri .db dosyasına checkpoint yap
        storage.checkpoint()

        db_file = Path(storage.db_path)
        if not db_file.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Veritabani dosyasi henuz olusmadi")
            return

        try:
            file_size = db_file.stat().st_size
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-sqlite3")
            self.send_header("Content-Disposition", 'attachment; filename="store_and_forward.db"')
            self.send_header("Content-Length", str(file_size))
            self.end_headers()

            with open(db_file, "rb") as f:
                while chunk := f.read(65536):
                    self.wfile.write(chunk)
            logger.info("store_and_forward.db basariyla indirildi (%d bayt).", file_size)
        except Exception as e:
            logger.error("Veritabani indirme hatasi: %s", e)

    def _serve_log_download(self) -> None:
        log_candidates = [
            "/var/log/supervisor/lxc_agent.err.log",
            "/var/log/supervisor/lxc_agent.out.log",
            "/var/log/lxc_agent.log",
        ]
        target_log = None
        for p in log_candidates:
            if os.path.isfile(p):
                target_log = p
                break

        if not target_log:
            self.send_error(HTTPStatus.NOT_FOUND, "Log dosyasi bulunamadi")
            return

        try:
            size = os.path.getsize(target_log)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="lxc_agent.log"')
            self.send_header("Content-Length", str(size))
            self.end_headers()

            with open(target_log, "rb") as f:
                while chunk := f.read(65536):
                    self.wfile.write(chunk)
        except Exception as e:
            logger.error("Log indirme hatasi: %s", e)

    def _handle_config_device(self) -> None:
        if not self.engine:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Motor hazir degil")
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))

            vehicle_id = str(data.get("vehicle_id", "")).strip()
            fleet_id = str(data.get("fleet_id", "")).strip()

            if not vehicle_id or not fleet_id:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                resp = json.dumps({"success": False, "error": "Araç Kimliği ve Filo ID boş olamaz."}).encode("utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return

            updated = self.engine.update_device_identity(vehicle_id, fleet_id)
            if updated:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                resp = json.dumps({"success": True, "vehicle_id": vehicle_id, "fleet_id": fleet_id}).encode("utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            else:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Kimlik guncelleme basarisiz")
        except Exception as e:
            logger.error("Cihaz kimligi guncelleme hatasi: %s", e)
            self.send_error(HTTPStatus.BAD_REQUEST, f"Gecersiz istek: {e}")

    def _handle_config_arena_params(self) -> None:
        if not self.engine:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Motor hazir degil")
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))

            moving = data.get("publish_interval_moving_sec")
            idle = data.get("publish_interval_idle_sec")
            speed = data.get("speed_threshold_kmh")
            storage_mb = data.get("max_storage_mb")

            if moving is not None:
                moving = int(moving)
                if moving < 1:
                    raise ValueError("Seyir aralığı en az 1 saniye olmalıdır.")
            if idle is not None:
                idle = int(idle)
                if idle < 1:
                    raise ValueError("Rölanti aralığı en az 1 saniye olmalıdır.")
            if speed is not None:
                speed = float(speed)
                if speed < 0:
                    raise ValueError("Hız eşiği negatif olamaz.")
            if storage_mb is not None:
                storage_mb = int(storage_mb)
                if storage_mb < 1:
                    raise ValueError("Depo kotası en az 1 MB olmalıdır.")

            if getattr(self.engine, "data_optimization_enabled", False) and (moving is not None or idle is not None):
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                resp = json.dumps({
                    "success": False,
                    "error": "Tasarruf Modu etkinken frekanslar kilitlidir. Özel frekans girmek için Tasarruf Modunu kapatın."
                }).encode("utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return

            success = self.engine.update_arena_params(
                publish_interval_moving_sec=moving,
                publish_interval_idle_sec=idle,
                speed_threshold_kmh=speed,
                max_storage_mb=storage_mb,
            )

            if success:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                resp = json.dumps({"success": True, "params": self.engine.arena_params}).encode("utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            else:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Yerel Mosquitto brokerına gönderilemedi")
        except Exception as e:
            logger.error("Arena parametre güncelleme hatası: %s", e)
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "application/json")
            resp = json.dumps({"success": False, "error": str(e)}).encode("utf-8")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    def _handle_config_optimization(self) -> None:
        if not self.engine:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Motor hazir degil")
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8")) if body else {}

            enabled = bool(data.get("enabled", True))
            h_int = data.get("health_interval_sec")
            health_interval = int(h_int) if h_int is not None else None
            pub_health = data.get("publish_health")

            success = self.engine.set_data_optimization(
                enabled=enabled,
                health_interval_sec=health_interval,
                publish_health=bool(pub_health) if pub_health is not None else None,
            )
            if success:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                resp = json.dumps({
                    "success": True,
                    "enabled": self.engine.data_optimization_enabled,
                    "health_interval_sec": self.engine.health_interval_sec,
                    "publish_health": self.engine.publish_health,
                    "mode_text": "Tasarruf Modu (%65 Tasarruf)" if self.engine.data_optimization_enabled else "Sınırsız Bütçe (Maksimum Akış)",
                }).encode("utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            else:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Optimizasyon ayarlari kaydedilemedi")
        except Exception as e:
            logger.error("Optimizasyon ayari guncelleme hatasi: %s", e)
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "application/json")
            resp = json.dumps({"success": False, "error": str(e)}).encode("utf-8")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    def _handle_queue_clear(self) -> None:
        if not self.engine:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Motor hazir degil")
            return

        try:
            deleted = self.engine.storage.purge()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            resp = json.dumps({"success": True, "deleted_count": deleted}).encode("utf-8")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        except Exception as e:
            logger.error("Kuyruk temizleme hatasi: %s", e)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Temizleme hatasi: {e}")


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class WebDiagnosticsServer:
    """Arka planda çalışan teşhis HTTP sunucusu."""

    def __init__(self, engine: TelemetryEngine, port: Optional[int] = None) -> None:
        self.engine = engine
        if port is not None:
            self.port = port
        elif hasattr(engine.config, "web"):
            self.port = engine.config.web.port
        else:
            self.port = getattr(engine.config, "web_port", 8080)

        self._server: Optional[ReusableThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Sunucuyu arka planda başlatır."""
        DiagnosticsHandler.engine = self.engine
        try:
            self._server = ReusableThreadingHTTPServer(("0.0.0.0", self.port), DiagnosticsHandler)
            # Eğer port 0 ise OS tarafından atanan gerçek portu al
            self.port = self._server.server_address[1]
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="WebDiagnostics")
            self._thread.start()
            logger.info("Web Teşhis ve İndirme Sunucusu aktif: http://0.0.0.0:%d", self.port)
        except Exception as e:
            logger.error("Web Teşhis Sunucusu başlatılamadı (Port: %d): %s", self.port, e)

    def stop(self) -> None:
        """Sunucuyu durdurur."""
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception as e:
                logger.debug("Web sunucusu durdurma hatası: %s", e)
            self._server = None
            logger.info("Web Teşhis Sunucusu kapatıldı.")
