#!/usr/bin/env bash
# Cai dat agent tro ly tao ma hang - chay tren MAC co Claude Code
#
# Chay trong Terminal (lay lenh o form "May chay Claude" trong Odoo), KHONG dung sudo:
#   cd ~ && curl -fsSL https://<odoo>/product_agent/download/setup_mac -o hlv_setup_mac.sh \
#     && bash hlv_setup_mac.sh https://<odoo>
#
# Script tu lam: kiem Claude Code (cai + dang nhap), tao moi truong Python rieng, tai
# agent tu Odoo, hoi ma cai dat, ghi agent.yaml, dang ky chay ngam bang launchd, khoi
# dong agent. Chay lai dung lenh nay = cap nhat agent. Prompt sua tren Odoo, agent tu tai.
#
# CO Y tai ve roi moi chay, khong "curl | bash": script hoi ma cai dat, ma duong ong
# chiem mat stdin nen cau hoi se nhan chuoi rong.
# CO Y khong dung tinh nang bash 4 (mang ket hop, ${x,,}...): macOS chi co bash 3.2.

set -uo pipefail
# Python in tieng Viet (thong bao loi tu Odoo, ten may) ra terminal. Terminal khong dat
# LANG (vd chay qua SSH) thi Python dung ASCII va chet ngay o cau in -> buoc doi ma cai
# dat im lang tra ve rong. Ep UTF-8 cho moi lenh Python script nay goi.
export PYTHONIOENCODING=utf-8

BASE_DIR="$HOME/hlv_product_agent"
AGENT_DIR="$BASE_DIR/agent"
VENV="$BASE_DIR/venv"
PY="$VENV/bin/python"
YAML="$BASE_DIR/agent.yaml"
LOG="$BASE_DIR/agent.log"
LABEL="com.hoanglongvu.product-agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
GUI_DOMAIN="gui/$(id -u)"
CLAUDE_INSTALLER="https://claude.ai/install.sh"

step() { printf '\n\033[36m>> %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32m[OK]\033[0m %s\n' "$1"; }
warn() { printf '   \033[33m[!]\033[0m %s\n' "$1"; }
bad()  { printf '   \033[31m[X]\033[0m %s\n' "$1"; }

echo "=================================================================="
echo " Cai dat agent tro ly tao ma hang (Claude) - macOS"
echo "=================================================================="

# --- 0. Kiem moi truong ----------------------------------------------------
# Dang nhap Claude tren Mac nam trong Keychain cua CHINH tai khoan nguoi dung; chay
# bang sudo thi agent la root, khong doc duoc Keychain do -> moi luot chat deu loi.
if [ "$(id -u)" -eq 0 ]; then
    bad "Dung chay bang sudo. Mo Terminal thuong roi chay lai: bash $0 ${1:-https://<odoo>}"
    exit 1
fi
if [ "$(uname -s)" != "Darwin" ]; then
    bad "Script nay danh cho macOS. Windows dung lenh PowerShell tren form Odoo."
    exit 1
fi

# --- 1. Dia chi Odoo -------------------------------------------------------
ODOO_URL="${1:-${HLV_ODOO_URL:-}}"
if [ -z "$ODOO_URL" ]; then
    read -r -p "Dia chi Odoo (vi du https://hoanglongvu.odoo.com): " ODOO_URL
fi
ODOO_URL="${ODOO_URL%/}"

# --- 2. Claude Code --------------------------------------------------------
# Cung thu tu voi find_claude() trong agent. Ghi duong dan tim duoc vao agent.yaml:
# agent chay duoi launchd gan nhu khong co PATH.
find_claude() {
    for c in "$(command -v claude 2>/dev/null)" "$HOME/.local/bin/claude" \
             "$HOME/.claude/local/claude" /opt/homebrew/bin/claude /usr/local/bin/claude; do
        if [ -n "$c" ] && [ -x "$c" ]; then echo "$c"; return 0; fi
    done
    ls -t "$HOME"/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude 2>/dev/null | head -1
}

install_claude() {
    step "Cai Claude Code ban rieng (trinh cai chinh thuc cua Anthropic)"
    if ! curl -fsSL "$CLAUDE_INSTALLER" | bash; then
        bad "Cai Claude Code loi."
    fi
}

step "Kiem tra Claude Code"
CLAUDE="$(find_claude)"
if [ -z "$CLAUDE" ]; then
    warn "May chua co Claude Code."
    read -r -p "   Cai Claude Code ngay bay gio? (y/n) " ans
    [ "$ans" = "y" ] || { bad "Can Claude Code de chay agent."; exit 1; }
    install_claude
    CLAUDE="$(find_claude)"
    [ -n "$CLAUDE" ] || { bad "Van khong thay claude sau khi cai."; exit 1; }
fi
case "$CLAUDE" in
    *"/.vscode/extensions/"*)
        warn "Chi co Claude di kem extension VS Code: $CLAUDE"
        warn "Extension cap nhat la doi thu muc, go VS Code la agent mat Claude."
        read -r -p "   Cai them Claude Code ban rieng cho chac? (y/n, Enter = n) " ans
        if [ "$ans" = "y" ]; then install_claude; CLAUDE="$(find_claude)"; fi
        ;;
esac
ok "$CLAUDE"

claude_logged_in() { "$CLAUDE" auth status 2>/dev/null | grep -q '"loggedIn": *true'; }
if ! claude_logged_in; then
    warn "Claude Code chua dang nhap tren tai khoan Mac nay ($USER)."
    echo "   Trinh duyet se mo trang dang nhap Anthropic. Dang nhap bang tai khoan cong ty -"
    echo "   luot dung cua tro ly tinh vao tai khoan nay."
    read -r -p "   Enter de mo trang dang nhap " _
    "$CLAUDE" auth login
    claude_logged_in || { bad "Chua dang nhap duoc Claude. Chay lai script sau khi dang nhap."; exit 1; }
fi
WHO="$("$CLAUDE" auth status 2>/dev/null | sed -n 's/.*"email": *"\([^"]*\)".*/\1/p' | head -1)"
ok "Da dang nhap: ${WHO:-?}"

# --- 3. Python -------------------------------------------------------------
# Moi truong ao rieng: Python cua Homebrew chan "pip install" thang vao he thong
# (PEP 668), va khong dung chung thu vien voi ai khac tren may.
pick_python() {
    for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null)"; do
        [ -n "$c" ] && [ -x "$c" ] || continue
        if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
            echo "$c"; return 0
        fi
    done
}

step "Kiem tra Python"
if [ ! -x "$PY" ]; then
    SYS_PY="$(pick_python)"
    if [ -z "$SYS_PY" ]; then
        bad "Khong co Python 3.9+. Cai mot trong hai roi chay lai:"
        echo "     xcode-select --install        (Python di kem bo cong cu cua Apple)"
        echo "     brew install python           (neu may co Homebrew)"
        exit 1
    fi
    mkdir -p "$BASE_DIR"
    "$SYS_PY" -m venv "$VENV" || { bad "Khong tao duoc moi truong ao bang $SYS_PY"; exit 1; }
fi
"$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1
"$PY" -m pip install --quiet requests pyyaml || { bad "Khong cai duoc requests, pyyaml"; exit 1; }
ok "$("$PY" -V 2>&1) (moi truong ao $VENV)"

# --- 4. Tai agent tu Odoo --------------------------------------------------
# Dung agent cu truoc khi thay file: tien trinh dang chay van giu code cu trong bo nho.
if launchctl print "$GUI_DOMAIN/$LABEL" >/dev/null 2>&1; then
    step "Dung agent dang chay de cap nhat"
    warn "Luot chat dang xu ly (neu co) se bi ngat; Odoo tu bao sale gui lai."
    launchctl bootout "$GUI_DOMAIN/$LABEL" 2>/dev/null || true
fi

step "Tai agent tu Odoo"
mkdir -p "$AGENT_DIR" "$BASE_DIR/sessions"
MANIFEST="$(curl -fsSL "$ODOO_URL/product_agent/download/manifest")" || {
    bad "Khong tai duoc danh sach file tu $ODOO_URL - kiem lai dia chi Odoo / module da nang cap chua."
    exit 1
}
# here-doc chu khong phai "| while": vong lap chay trong shell nay nen "exit" dung la thoat script.
while read -r key target; do
    [ -n "$key" ] || continue
    dest="$AGENT_DIR/$target"
    mkdir -p "$(dirname "$dest")"
    # Tai qua file tam roi moi thay: tai hong giua chung khong de lai file cut.
    if ! curl -fsSL "$ODOO_URL/product_agent/download/$key" -o "$dest.part"; then
        bad "Khong tai duoc $target"; exit 1
    fi
    mv -f "$dest.part" "$dest"
    ok "$target"
done <<EOF
$MANIFEST
EOF
if ! head -5 "$AGENT_DIR/hlv_product_agent.py" | grep -q python; then
    bad "File tai ve khong phai agent Python (co the la trang loi). Kiem lai: $ODOO_URL"
    exit 1
fi

# --- 5. Token: dung lai cai cu, hoac doi ma cai dat ------------------------
# Goi Odoo bang chinh Python cua agent: ma nguoi dung go vao di qua json.dumps, khong
# ghep tay vao chuoi JSON (go nham dau nhay la hong lenh).
odoo_call() {  # odoo_call <duong dan> <khoa> <gia tri>  -> in "OK<TAB>token<TAB>ten" hoac "ERR<TAB>loi"
    "$PY" - "$ODOO_URL$1" "$2" "$3" <<'PYEOF'
import json, sys, requests
url, key, value = sys.argv[1:4]
params = {key: value, 'agent_version': 'setup', 'max_jobs': 0}
try:
    result = requests.post(url, json={'jsonrpc': '2.0', 'method': 'call', 'params': params},
                           timeout=30).json().get('result') or {}
except Exception as error:
    print('ERR\t%s' % error); sys.exit(0)
if result.get('ok'):
    print('OK\t%s\t%s' % (result.get('token') or value, result.get('agent_name') or ''))
else:
    print('ERR\t%s' % (result.get('error') or 'bi tu choi'))
PYEOF
}

TOKEN=""
OLD_MODEL=""
if [ -f "$YAML" ]; then
    OLD_TOKEN="$("$PY" -c 'import sys, yaml; print((yaml.safe_load(open(sys.argv[1])) or {}).get("token") or "")' "$YAML" 2>/dev/null)"
    OLD_MODEL="$("$PY" -c 'import sys, yaml; print((yaml.safe_load(open(sys.argv[1])) or {}).get("model") or "")' "$YAML" 2>/dev/null)"
    if [ -n "$OLD_TOKEN" ]; then
        if odoo_call /product_agent/agent/poll token "$OLD_TOKEN" | grep -q '^OK'; then
            TOKEN="$OLD_TOKEN"
            step "Dung lai token cu (van con hieu luc)"
        else
            warn "Token trong agent.yaml cu khong con dung, phai xin ma cai dat moi."
        fi
    fi
fi

if [ -z "$TOKEN" ]; then
    step "Lay token tu Odoo"
    echo "   Odoo: Ton kho > Cau hinh > Tro ly tao ma hang > May chay Claude"
    echo "   Mo dong cua may nay, bam 'Tao ma cai dat'."
    for _ in 1 2 3; do
        read -r -p "   Ma cai dat (dang XXXX-XXXX): " CODE
        RESULT="$(odoo_call /product_agent/enroll code "$CODE")"
        case "$RESULT" in
            OK*) TOKEN="$(printf '%s' "$RESULT" | cut -f2)"
                 ok "May: $(printf '%s' "$RESULT" | cut -f3)"; break ;;
            *)   warn "$(printf '%s' "$RESULT" | cut -f2)" ;;
        esac
    done
    [ -n "$TOKEN" ] || { bad "Het luot thu. Tao ma moi trong Odoo roi chay lai."; exit 1; }
fi

# --- 6. Ghi agent.yaml -----------------------------------------------------
step "Ghi cau hinh"
MODEL="${OLD_MODEL:-sonnet}"
umask 077   # file chua token: chi chinh tai khoan nay doc duoc
cat > "$YAML" <<EOF
# Sinh tu dong boi setup_mac.sh - $(date '+%Y-%m-%d %H:%M')
# Chua token Odoo. Dung chep di noi khac. Chay lai setup_mac.sh se ghi de file nay
# (giu nguyen model).

odoo_url: "$ODOO_URL"
token: "$TOKEN"
model: "$MODEL"
work_dir: "$BASE_DIR"
max_parallel: 2
turn_timeout_seconds: 300
# Duong dan tuyet doi: launchd khong co PATH de agent tu tim.
claude_path: "$CLAUDE"
EOF
umask 022
ok "$YAML (model: $MODEL)"

# --- 7. Kiem thu truoc khi dang ky -----------------------------------------
step "Kiem agent"
CHECK="$("$PY" "$AGENT_DIR/hlv_product_agent.py" --config "$YAML" --check 2>&1)"
if ! printf '%s' "$CHECK" | grep -q 'Odoo: OK' || printf '%s' "$CHECK" | grep -q 'Prompt: LOI'; then
    bad "Agent kiem khong qua:"; printf '%s\n' "$CHECK"; exit 1
fi
ok "Agent doc duoc cau hinh, tim thay Claude, Odoo nhan token, tai duoc prompt"

step "Thu mot cau hoi voi Claude (khoang 10 giay)"
mkdir -p "$BASE_DIR/sessions/_setup_check"
PING="$(cd "$BASE_DIR/sessions/_setup_check" && "$CLAUDE" -p 'Tra loi dung mot tu: OK' \
        --output-format json --restricted --strict-mcp-config --disable-slash-commands \
        --permission-mode dontAsk --no-session-persistence --model "$MODEL" 2>&1)"
if printf '%s' "$PING" | grep -q '"is_error": *false'; then
    ok "Claude tra loi binh thuong"
else
    bad "Claude chua tra loi duoc (het han muc? model '$MODEL' khong dung duoc?):"
    printf '%s\n' "$PING" | head -3
    warn "Van tiep tuc cai, nhung khung chat se bao loi toi khi sua duoc."
fi

# --- 8. Chay ngam bang launchd ---------------------------------------------
step "Dang ky chay ngam (launchd)"
# LaunchAgent (khong phai LaunchDaemon): chay trong phien dang nhap cua tai khoan nay,
# nen doc duoc Keychain chua dang nhap Claude. Doi lai: may phai co nguoi dang nhap.
# caffeinate -is: khong cho Mac ngu khi agent dang chay (Mac ngu = sale khong ai tra loi).
# KeepAlive: agent chet thi launchd bat lai; ThrottleInterval chan bat lai lien tuc khi loi.
AGENT_PATH="$(dirname "$CLAUDE"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-is</string>
        <string>$PY</string>
        <string>$AGENT_DIR/hlv_product_agent.py</string>
        <string>--config</string>
        <string>$YAML</string>
    </array>
    <key>WorkingDirectory</key><string>$BASE_DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>30</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>$AGENT_PATH</string>
        <key>PYTHONIOENCODING</key><string>utf-8</string>
    </dict>
    <key>StandardOutPath</key><string>$BASE_DIR/launchd.out.log</string>
    <key>StandardErrorPath</key><string>$BASE_DIR/launchd.err.log</string>
</dict>
</plist>
EOF
if ! plutil -lint "$PLIST" >/dev/null; then
    bad "File launchd sinh ra bi loi: $PLIST"; plutil -lint "$PLIST"; exit 1
fi
launchctl bootout "$GUI_DOMAIN/$LABEL" 2>/dev/null || true
if launchctl bootstrap "$GUI_DOMAIN" "$PLIST"; then
    ok "Chay ngam khi $USER dang nhap, tu bat lai neu bi tat, khong cho Mac ngu"
else
    bad "Khong dang ky duoc launchd. Chay tay de xem loi (lenh o cuoi)."
fi

step "Khoi dong agent"
sleep 6
if [ -f "$LOG" ] && tail -3 "$LOG" | grep -q 'Odoo t'; then
    bad "Odoo tu choi agent - kiem lai token"; tail -3 "$LOG"
elif launchctl print "$GUI_DOMAIN/$LABEL" 2>/dev/null | grep -q 'state = running'; then
    ok "Agent dang chay ngam"
else
    warn "Agent chua chay - xem $BASE_DIR/launchd.err.log"
fi

# --- 9. Xong ---------------------------------------------------------------
cat <<EOF

==================================================================
 XONG
==================================================================

Kiem tra:
  - Odoo > May chay Claude > "Tinh trang" phai la "Dang chay"
  - Mo $ODOO_URL/search_stock, bam nut "Tao ma hang" goc trai duoi.
  - Log:  tail -f "$LOG"

Luu y voi Mac:
  - May phai BAT va tai khoan $USER phai DANG NHAP (khoa man hinh van duoc).
    Khoi dong lai ma chua ai dang nhap thi agent chua chay.
  - Laptop gap nap (khong cam man hinh ngoai) van ngu - de mo nap hoac cam sac + man hinh.

Chay tay de xem log truc tiep:
  launchctl bootout $GUI_DOMAIN/$LABEL
  "$PY" "$AGENT_DIR/hlv_product_agent.py" --config "$YAML"

Bat lai chay ngam:   launchctl bootstrap $GUI_DOMAIN "$PLIST"
Dung han agent:      launchctl bootout $GUI_DOMAIN/$LABEL && rm "$PLIST"

EOF
