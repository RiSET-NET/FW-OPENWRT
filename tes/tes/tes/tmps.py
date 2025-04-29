import subprocess
import time
import json
import requests
import re
import traceback
from datetime import datetime

# ╔════════════════════════════════════════════════════╗
# ║                    🚨 R4X MONITOR                 ║
# ║     Hotspot Device & ISP Watcher via Termux       ║
# ╚════════════════════════════════════════════════════╝

def log_event(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("r4x.log", "a") as f:
        f.write(f"[{timestamp}] {message}\n")

def get_current_isp():
    try:
        response = requests.get("https://ipinfo.io/json", timeout=5)
        data = response.json()
        ip = data.get("ip", "Unknown IP")
        isp = data.get("org", "Unknown ISP")
        return ip, isp
    except Exception as e:
        log_event(f"[ERROR] Gagal ambil info ISP: {e}")
        return "Unknown IP", "Unknown ISP"

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log_event(f"[ERROR] Gagal kirim ke Telegram: {e}")

def get_connected_devices():
    try:
        result = subprocess.run(["ip", "neigh"], stdout=subprocess.PIPE, text=True)
        lines = result.stdout.strip().split('\n')
        devices = set()
        for line in lines:
            match = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+dev\s+\w+\s+lladdr\s+[\da-f:]+\s+(REACHABLE|STALE|DELAY|PROBE)", line)
            if match:
                devices.add(match.group(1))
        return devices
    except Exception as e:
        log_event(f"[ERROR] Gagal cek perangkat: {e}")
        return set()

# ─── Load konfigurasi ───────────────────────────
with open("auth.json", "r") as f:
    config = json.load(f)

TELEGRAM_TOKEN = config["BOT_TOKEN"]
CHANNEL_ID = config["CHANNEL_ID"]

def run_monitor():
    last_devices = set()
    last_ip, last_isp = get_current_isp()
    isp_change_count = 0
    last_reset_date = datetime.now().date()
    disconnected_at = {}
    disconnected_inet_at = None
    last_alert_time = {}
    DEVICE_ALERT_INTERVAL = 60  # Detik

    print("\n📡 Memulai pemantauan perangkat dan koneksi...\n")
    send_telegram_alert("🚨 *R4X Monitor dimulai!*")

    while True:
        current_devices = get_connected_devices()

        # Perangkat baru
        new_devices = current_devices - last_devices
        for device in new_devices:
            now = datetime.now()
            if device in last_alert_time and (now - last_alert_time[device]).total_seconds() < DEVICE_ALERT_INTERVAL:
                continue

            if device in disconnected_at:
                offline_time = now - disconnected_at[device]
                seconds = int(offline_time.total_seconds())
                minutes, seconds = divmod(seconds, 60)
                durasi = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
                msg = (
                    f"🔄 *Perangkat Kembali Terhubung*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📡 IP Address : `{device}`\n"
                    f"⏱️ Offline Selama : _{durasi}_"
                )
                del disconnected_at[device]
            else:
                msg = (
                    f"📲 *Perangkat Baru Terhubung*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📡 IP Address : `{device}`"
                )
            send_telegram_alert(msg)
            log_event(f"[+] Terhubung: {device}")
            last_alert_time[device] = now

        # Perangkat terputus
        disconnected_devices = last_devices - current_devices
        for device in disconnected_devices:
            now = datetime.now()
            if device in last_alert_time and (now - last_alert_time[device]).total_seconds() < DEVICE_ALERT_INTERVAL:
                continue

            disconnected_at[device] = now
            msg = (
                f"❌ *Perangkat Terputus*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📡 IP Address : `{device}`"
            )
            send_telegram_alert(msg)
            log_event(f"[-] Terputus: {device}")
            last_alert_time[device] = now

        last_devices = current_devices

        # Cek ISP & koneksi internet
        current_ip, current_isp = get_current_isp()

        if "Unknown" in current_ip or "Unknown" in current_isp:
            if not disconnected_inet_at:
                disconnected_inet_at = datetime.now()
                log_event("[✖] Koneksi internet hilang.")
            time.sleep(5)
            continue
        else:
            if disconnected_inet_at:
                offline_time = datetime.now() - disconnected_inet_at
                seconds = int(offline_time.total_seconds())
                minutes, seconds = divmod(seconds, 60)
                durasi = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
                msg = (
                    f"✅ *Koneksi Internet Kembali*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📡 IP Address : `{current_ip}`\n"
                    f"🏢 ISP : *{current_isp}*\n"
                    f"⏱️ Offline Selama : _{durasi}_"
                )
                send_telegram_alert(msg)
                log_event(f"[✓] Internet kembali setelah {durasi}")
                disconnected_inet_at = None

        # Deteksi perubahan ISP / IP
        if current_ip != last_ip or current_isp != last_isp:
            reason = []
            if current_ip != last_ip:
                reason.append("IP")
            if current_isp != last_isp:
                reason.append("ISP")
            reason_str = " dan ".join(reason)

            isp_change_count += 1
            msg = (
                f"🌐 *Perubahan {reason_str.title()} Terdeteksi*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🕒 Waktu : {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}\n"
                f"🔁 Sebelumnya :\n"
                f"  • IP  : `{last_ip}`\n"
                f"  • ISP : *{last_isp}*\n\n"
                f"✅ Sekarang :\n"
                f"  • IP  : `{current_ip}`\n"
                f"  • ISP : *{current_isp}*\n\n"
                f"📊 Total perubahan hari ini: *{isp_change_count}*"
            )
            send_telegram_alert(msg)
            log_event(f"[↻] {reason_str}: {last_isp} → {current_isp} / {last_ip} → {current_ip}")
            last_ip = current_ip
            last_isp = current_isp

        # Reset harian
        if datetime.now().date() != last_reset_date:
            isp_change_count = 0
            last_reset_date = datetime.now().date()
            send_telegram_alert("🕛 *Reset hitungan ISP harian* (00:00)")
            log_event("[✓] Hitungan ISP direset.")

        time.sleep(10)

# ─── Auto-restart saat error ───────────────────────
while True:
    try:
        run_monitor()
    except Exception as e:
        log_event(f"[CRASH] {e}")
        log_event(traceback.format_exc())
        send_telegram_alert("⚠️ *R4X Monitor crash! Restarting...*")
        time.sleep(5)
