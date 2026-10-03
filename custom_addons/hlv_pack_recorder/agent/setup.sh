#!/usr/bin/env bash
# Cai dat agent ghi hinh dong goi - chay tren may dong goi Linux (Ubuntu/Debian)
#
# Chay (lay lenh o form Ban dong goi trong Odoo):
#   cd ~ && (curl -fsSL https://<odoo>/pack_agent/download/setup_sh -o hlv_setup.sh \
#            || wget -qO hlv_setup.sh https://<odoo>/pack_agent/download/setup_sh) \
#     && sudo bash hlv_setup.sh https://<odoo>
#
# CO Y khong dung "curl ... | bash": script co hoi ma cai dat va URL camera, ma
# duong ong da chiem mat stdin nen moi cau hoi se nhan chuoi rong roi chay tiep.
#
# CO Y tai ve THU MUC NHA chu khong phai /tmp: ban curl cai qua snap chay trong
# sandbox co /tmp rieng, file ghi ra khong nam o /tmp that nen bash sau do bao
# "khong co tap tin". Da gap that tren may Ubuntu o kho.

set -uo pipefail

AGENT_DIR=/opt/hlv_agent
SERVICE=hlv-pack-agent
PY=$AGENT_DIR/venv/bin/python

step() { printf '\n\033[36m>> %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32m[OK]\033[0m %s\n' "$1"; }
warn() { printf '   \033[33m[!]\033[0m %s\n' "$1"; }
bad()  { printf '   \033[31m[X]\033[0m %s\n' "$1"; }

echo "=================================================================="
echo " Cai dat agent ghi hinh dong goi (Linux)"
echo "=================================================================="

# --- 0. Quyen -------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    bad "Can chay bang sudo (de cai goi va dang ky service systemd)."
    echo "   sudo bash $0 ${1:-https://<odoo>}"
    exit 1
fi
# Service chay duoi tai khoan nguoi dung that, khong phai root: agent chi can doc
# camera va goi ra Odoo, khong viec gi phai chay quyen cao nhat.
RUN_USER="${SUDO_USER:-root}"

# --- 1. Dia chi Odoo ------------------------------------------------------
ODOO_URL="${1:-${HLV_ODOO_URL:-}}"
if [ -z "$ODOO_URL" ]; then
    read -r -p "Dia chi Odoo (vi du https://hoanglongvu.odoo.com): " ODOO_URL
fi
ODOO_URL="${ODOO_URL%/}"

# --- 2. Goi he thong ------------------------------------------------------
step "Cai goi he thong (python3, venv, ffmpeg, curl)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# python3-venv la BAT BUOC: tu Ubuntu 23.04 pip bi chan cai thang vao he thong
# (PEP 668 "externally-managed-environment"), phai qua moi truong ao.
apt-get install -y -qq python3 python3-venv ffmpeg curl >/dev/null
ok "python3 $(python3 -V 2>&1 | awk '{print $2}'), ffmpeg $(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')"

# --- 3. Thu muc + moi truong ao -------------------------------------------
step "Chuan bi $AGENT_DIR"
mkdir -p "$AGENT_DIR/rec"
if [ ! -x "$PY" ]; then
    python3 -m venv "$AGENT_DIR/venv"
fi
"$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1
"$PY" -m pip install --quiet requests pyyaml
ok "moi truong ao + requests, pyyaml"

step "Tai agent tu Odoo"
# Dung "> file" chu KHONG dung "curl -o file": ban curl cai qua snap chay trong
# sandbox, khong ghi duoc vao /opt. Chuyen huong bang shell thi chinh bash (dang
# chay quyen root) tao file, curl chi viec in ra stdout - sandbox het lien quan.
if ! curl -fsSL "$ODOO_URL/pack_agent/download/agent" > "$AGENT_DIR/hlv_pack_agent.py"; then
    bad "Khong tai duoc agent tu $ODOO_URL"
    exit 1
fi
# Tai hut giua chung hoac nhan ve trang loi HTML thi file van ton tai nhung vo
# dung - kiem noi dung truoc khi di tiep, dung de phat hien luc service chet.
if ! head -3 "$AGENT_DIR/hlv_pack_agent.py" | grep -q 'hlv_pack_agent\|python'; then
    bad "File tai ve khong phai agent Python. Kiem lai dia chi Odoo: $ODOO_URL"
    head -3 "$AGENT_DIR/hlv_pack_agent.py"
    exit 1
fi
ok "hlv_pack_agent.py ($(wc -l < "$AGENT_DIR/hlv_pack_agent.py") dong)"

# --- 4. Ma cai dat --------------------------------------------------------
# Doc JSON bang python co san, khong bat cai them jq.
json_get() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print(d.get('result',{}).get('$1',''))" 2>/dev/null; }

ENROLL_JSON=""
YAML=$AGENT_DIR/agent.yaml

if [ -f "$YAML" ]; then
    OLD_KEY=$(grep -oP 'station_key:\s*"\K[^"]+' "$YAML" || true)
    OLD_TOKEN=$(grep -oP 'token:\s*"\K[^"]+' "$YAML" || true)
    if [ -n "$OLD_KEY" ] && [ -n "$OLD_TOKEN" ]; then
        step "Da co cau hinh cu cho ban ma $OLD_KEY"
        read -r -p "   Dung lai station_key/token cu va chi khai lai camera? (y/n) " REUSE
        if [ "$REUSE" = "y" ]; then
            CHK=$(curl -fsS -X POST "$ODOO_URL/pack_agent/poll" -H 'Content-Type: application/json' \
                -d "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"station_key\":\"$OLD_KEY\",\"token\":\"$OLD_TOKEN\",\"active_ids\":[],\"agent_version\":\"setup\"}}")
            if [ "$(echo "$CHK" | json_get ok)" = "True" ]; then
                ok "Cau hinh cu con dung"
                STATION_KEY=$OLD_KEY; TOKEN=$OLD_TOKEN; CAMERAS_JSON='[]'
                ENROLL_JSON=reuse
            else
                warn "Cau hinh cu khong con dung, phai xin ma cai dat moi."
            fi
        fi
    fi
fi

if [ -z "$ENROLL_JSON" ]; then
    step "Lay cau hinh ban dong goi tu Odoo"
    echo "   Odoo: Ton kho > Cau hinh > Video dong goi > Ban dong goi"
    echo "   Chon dung ban may nay dang dat, bam 'Tao ma cai dat'."
    for i in 1 2 3; do
        read -r -p "
   Ma cai dat (dang XXXX-XXXX): " CODE
        RESP=$(curl -fsS -X POST "$ODOO_URL/pack_agent/enroll" -H 'Content-Type: application/json' \
            -d "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"code\":\"$CODE\"}}")
        if [ "$(echo "$RESP" | json_get ok)" = "True" ]; then
            STATION_KEY=$(echo "$RESP" | json_get station_key)
            TOKEN=$(echo "$RESP" | json_get token)
            STATION_NAME=$(echo "$RESP" | json_get station_name)
            CAMERAS_JSON=$(echo "$RESP" | "$PY" -c "import json,sys; print(json.dumps(json.load(sys.stdin)['result']['cameras']))")
            ok "Ban: $STATION_NAME"
            ENROLL_JSON=new
            break
        fi
        warn "$(echo "$RESP" | json_get error)"
    done
    if [ -z "$ENROLL_JSON" ]; then
        bad "Het luot thu. Tao ma moi trong Odoo roi chay lai."
        exit 1
    fi
fi

# --- 5. Khai va KIEM camera ----------------------------------------------
# Kiem ngay tai cho: go nham rstp://, sai mat khau, sai IP - phai biet BAY GIO
# chu khong phai luc khach khieu nai moi phat hien khong co video.
check_rtsp() {
    local url=$1
    case "$url" in
        rtsp://*) ;;
        *) echo "URL phai bat dau bang rtsp:// (ban go '${url%%://*}')"; return 1 ;;
    esac
    local out
    out=$(ffprobe -v error -rtsp_transport tcp -timeout 8000000 -select_streams v:0 \
          -show_entries stream=codec_name,width,height \
          -of default=noprint_wrappers=1:nokey=0 -i "$url" 2>&1)
    if ! echo "$out" | grep -q 'width='; then
        echo "khong ket noi duoc: $(echo "$out" | head -1)"
        return 1
    fi
    echo "$(echo "$out" | grep codec_name | cut -d= -f2) $(echo "$out" | grep width | cut -d= -f2)x$(echo "$out" | grep height | cut -d= -f2)"
    return 0
}

step "Khai camera"
CAM_LINES=""
HAS_USB=0
CAM_COUNT=$(echo "$CAMERAS_JSON" | "$PY" -c "import json,sys; print(len(json.load(sys.stdin)))")

for idx in $(seq 0 $((CAM_COUNT - 1))); do
    [ "$CAM_COUNT" -eq 0 ] && break
    CODE_I=$(echo "$CAMERAS_JSON" | "$PY" -c "import json,sys; print(json.load(sys.stdin)[$idx]['code'])")
    NAME_I=$(echo "$CAMERAS_JSON" | "$PY" -c "import json,sys; print(json.load(sys.stdin)[$idx]['name'])")
    echo ""
    echo "   Camera '$NAME_I' (ma $CODE_I)"
    echo "   - Camera IP : dan URL RTSP"
    echo "   - Webcam USB: go chu  usb  roi Enter"
    while true; do
        read -r -p "   URL RTSP hoac 'usb': " ANS
        if [ "$ANS" = "usb" ]; then
            echo "   Webcam may nay thay:"
            for d in /dev/video*; do
                [ -e "$d" ] || continue
                n=$(cat "/sys/class/video4linux/$(basename "$d")/name" 2>/dev/null || echo '')
                echo "     $d  $n"
            done
            read -r -p "   Duong dan thiet bi (vi du /dev/video0): " DEV
            read -r -p "   Do phan giai (Enter = 1280x720): " SIZE; SIZE=${SIZE:-1280x720}
            read -r -p "   FPS (Enter = 15): " FPS; FPS=${FPS:-15}
            CAM_LINES="$CAM_LINES
  \"$CODE_I\":
    type: usb
    device: \"$DEV\"
    size: \"$SIZE\"
    fps: $FPS
    bitrate: \"3M\"
    overlay_time: true"
            HAS_USB=1
            break
        fi
        if MSG=$(check_rtsp "$ANS"); then
            ok "Camera tra loi: $MSG"
            case "$ANS" in *subtype=1*) warn "URL dang dung subtype=1 (luong phu, mo). Nen doi thanh subtype=0." ;; esac
            CAM_LINES="$CAM_LINES
  \"$CODE_I\": \"$ANS\""
            break
        fi
        bad "$MSG"
        read -r -p "   Thu lai? (y = nhap lai / n = bo qua camera nay) " AGAIN
        [ "$AGAIN" = "y" ] || { warn "Bo qua '$NAME_I' - camera nay se khong co video."; break; }
    done
done

# --- 6. Ghi agent.yaml ----------------------------------------------------
step "Ghi cau hinh"
if [ -z "$CAM_LINES" ] && [ -f "$YAML" ]; then
    warn "Khong khai camera nao moi - giu nguyen $YAML"
else
    cat > "$YAML" <<YAMLEOF
# Sinh tu dong boi setup.sh - $(date '+%Y-%m-%d %H:%M')
# File nay chua mat khau camera va token Odoo.

odoo_url: "$ODOO_URL"
station_key: "$STATION_KEY"
token: "$TOKEN"

ffmpeg_path: "ffmpeg"
work_dir: "$AGENT_DIR/rec"

cameras:$CAM_LINES
YAMLEOF
    ok "agent.yaml"
fi
# Chua mat khau camera -> chi chu so huu doc duoc.
chown -R "$RUN_USER":"$RUN_USER" "$AGENT_DIR"
chmod 600 "$YAML"

# Doc /dev/video* can thuoc nhom video. Chi them khi that su co webcam.
if [ "$HAS_USB" = "1" ] && [ "$RUN_USER" != "root" ]; then
    usermod -aG video "$RUN_USER" && ok "Da them $RUN_USER vao nhom video (can dang xuat/vao lai)"
fi

# --- 7. systemd -----------------------------------------------------------
step "Dang ky service systemd"
cat > "/etc/systemd/system/$SERVICE.service" <<UNITEOF
[Unit]
Description=HLV Pack Recorder Agent
# Doi co IP that roi moi chay: khoi dong som hon mang thi lan poll dau that bai.
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$AGENT_DIR
ExecStart=$PY $AGENT_DIR/hlv_pack_agent.py --config $AGENT_DIR/agent.yaml
# Chet vi bat ky ly do gi cung bat lai sau 10 giay - day la phan watchdog.
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"
sleep 4

if systemctl is-active --quiet "$SERVICE"; then
    ok "Service dang chay, tu bat lai khi chet, tu chay khi khoi dong may"
else
    bad "Service khong chay duoc:"
    systemctl status "$SERVICE" --no-pager -l | tail -15
fi

# --- 8. Xong --------------------------------------------------------------
cat <<DONEEOF

==================================================================
 XONG
==================================================================

Con MOT buoc cuoi, lam tren trinh duyet cua may nay:

    $ODOO_URL/pack_recorder/set_station

  Bam chon dung ban dong goi. Chi lam mot lan cho moi may.

Kiem tra:
  - Odoo > Ban dong goi > cot "Tinh trang agent" phai la "Dang chay"
  - Log:        journalctl -u $SERVICE -f
  - Trang thai: systemctl status $SERVICE
  - Dung han:   sudo systemctl disable --now $SERVICE

DONEEOF
