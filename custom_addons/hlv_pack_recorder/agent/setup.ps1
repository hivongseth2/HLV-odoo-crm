# Cai dat agent ghi hinh dong goi - chay tren may dong goi
#
# Chay mot lenh duy nhat (lay o form Ban dong goi trong Odoo):
#   irm https://<odoo>/pack_agent/download/setup | iex
#
# Script tu lam: tai agent + ffmpeg, hoi ma cai dat, hoi URL camera,
# ghi agent.yaml, dang ky chay cung Windows. Khong can quyen admin.

$ErrorActionPreference = 'Stop'
$AgentDir = 'C:\hlv_agent'
$FfmpegUrl = 'https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip'
$TaskName = 'HLV Pack Agent'

function Write-Step($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "   [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "   [!] $msg" -ForegroundColor Yellow }

Write-Host "=================================================================="
Write-Host " Cai dat agent ghi hinh dong goi" -ForegroundColor White
Write-Host "=================================================================="

# --- 1. Dia chi Odoo -------------------------------------------------------
# Lay tu chinh URL da tai script nay ve, neu goi kieu irm ... | iex thi hoi.
$OdooUrl = $env:HLV_ODOO_URL
if (-not $OdooUrl) {
    $OdooUrl = Read-Host "`nDia chi Odoo (vi du https://hoanglongvu.odoo.com)"
}
$OdooUrl = $OdooUrl.TrimEnd('/')

# --- 2. Kiem tra Python ----------------------------------------------------
Write-Step "Kiem tra Python"
$python = $null
foreach ($cmd in @('python', 'py')) {
    try {
        $v = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0) { $python = (Get-Command $cmd).Source; Write-Ok "$v"; break }
    } catch {}
}
if (-not $python) {
    Write-Warn2 "Chua co Python. Dang cai bang winget..."
    try {
        winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path', 'User')
        $python = (Get-Command python).Source
        Write-Ok "Da cai Python"
    } catch {
        Write-Host "`nKhong tu cai duoc Python. Tai tai https://www.python.org/downloads/" -ForegroundColor Red
        Write-Host "Nho tick 'Add python.exe to PATH' luc cai, roi chay lai script nay." -ForegroundColor Red
        exit 1
    }
}

Write-Step "Cai thu vien Python"
& $python -m pip install --quiet --upgrade requests pyyaml
Write-Ok "requests, pyyaml"

# --- 3. Thu muc + agent ----------------------------------------------------
Write-Step "Tao thu muc $AgentDir"
New-Item -ItemType Directory -Force -Path $AgentDir, "$AgentDir\rec" | Out-Null
Write-Ok "Xong"

Write-Step "Tai agent tu Odoo"
Invoke-WebRequest -Uri "$OdooUrl/pack_agent/download/agent" -OutFile "$AgentDir\hlv_pack_agent.py"
Write-Ok "hlv_pack_agent.py"

# --- 4. ffmpeg -------------------------------------------------------------
if (Test-Path "$AgentDir\ffmpeg.exe") {
    Write-Step "ffmpeg da co, bo qua"
} else {
    Write-Step "Tai ffmpeg (~190MB, hoi lau)"
    $zip = "$env:TEMP\ffmpeg_hlv.zip"
    Invoke-WebRequest -Uri $FfmpegUrl -OutFile $zip
    $tmp = "$env:TEMP\ffmpeg_hlv"
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    Get-ChildItem -Path $tmp -Recurse -Filter 'ffmpeg.exe'  | Select-Object -First 1 |
        ForEach-Object { Copy-Item $_.FullName "$AgentDir\ffmpeg.exe" -Force }
    Get-ChildItem -Path $tmp -Recurse -Filter 'ffprobe.exe' | Select-Object -First 1 |
        ForEach-Object { Copy-Item $_.FullName "$AgentDir\ffprobe.exe" -Force }
    Remove-Item -Recurse -Force $tmp, $zip -ErrorAction SilentlyContinue
    Write-Ok "ffmpeg.exe + ffprobe.exe"
}

# --- 5. Ma cai dat ---------------------------------------------------------
Write-Step "Lay cau hinh ban dong goi tu Odoo"
Write-Host "   Mo Odoo: Ton kho > Cau hinh > Video dong goi > Ban dong goi"
Write-Host "   Chon dung ban ma may nay dang dat, bam 'Tao ma cai dat'."

$enroll = $null
for ($i = 1; $i -le 3; $i++) {
    $code = Read-Host "`n   Ma cai dat (dang XXXX-XXXX)"
    $body = @{ jsonrpc = '2.0'; method = 'call'; params = @{ code = $code } } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "$OdooUrl/pack_agent/enroll" -Method Post `
                              -ContentType 'application/json' -Body $body
    if ($resp.result.ok) { $enroll = $resp.result; break }
    Write-Warn2 $resp.result.error
}
if (-not $enroll) { Write-Host "`nHet luot thu. Tao ma moi trong Odoo roi chay lai." -ForegroundColor Red; exit 1 }
Write-Ok "Ban: $($enroll.station_name) - kho $($enroll.warehouse)"

# --- 6. Hoi URL camera -----------------------------------------------------
# Odoo co y khong luu URL/mat khau camera, nen phai hoi tai cho va chi ghi xuong
# may nay. Token Odoo ro ra ngoai cung khong lo duoc camera kho.
Write-Step "Khai camera"
if ($enroll.cameras.Count -eq 0) {
    Write-Warn2 "Ban nay chua khai camera nao trong Odoo. Khai xong thi chay lai script."
}

$camLines = @()
foreach ($cam in $enroll.cameras) {
    Write-Host "`n   Camera '$($cam.name)' (ma $($cam.code))"
    Write-Host "   - Camera IP : dan URL RTSP (lay trong OBS, nguon VLC)"
    Write-Host "   - Webcam USB: go chu  usb  roi Enter"
    $ans = Read-Host "   URL RTSP hoac 'usb'"

    if ($ans.Trim().ToLower() -eq 'usb') {
        Write-Host "   Cac webcam may nay thay:" -ForegroundColor Yellow
        & "$AgentDir\ffmpeg.exe" -hide_banner -list_devices true -f dshow -i dummy 2>&1 |
            Select-String '\(video\)' | ForEach-Object { Write-Host "     $_" }
        $dev  = Read-Host "   Chep chinh xac ten webcam trong dau nhay"
        $size = Read-Host "   Do phan giai (Enter = 1280x720)"
        if (-not $size) { $size = '1280x720' }
        $fps  = Read-Host "   FPS (Enter = 15)"
        if (-not $fps) { $fps = '15' }
        $camLines += @(
            "  `"$($cam.code)`":"
            "    type: usb"
            "    device: `"$dev`""
            "    size: `"$size`""
            "    fps: $fps"
            "    bitrate: `"3M`""
            "    overlay_time: true"
        )
    } else {
        $camLines += "  `"$($cam.code)`": `"$($ans.Trim())`""
    }
}

# --- 7. Ghi agent.yaml -----------------------------------------------------
Write-Step "Ghi cau hinh"
$yaml = @(
    "# Sinh tu dong boi setup.ps1 - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    "# File nay chua mat khau camera va token Odoo. Dung chep di noi khac."
    ""
    "odoo_url: `"$OdooUrl`""
    "station_key: `"$($enroll.station_key)`""
    "token: `"$($enroll.token)`""
    ""
    "ffmpeg_path: `"C:/hlv_agent/ffmpeg.exe`""
    "work_dir: `"C:/hlv_agent/rec`""
    ""
    "cameras:"
) + $camLines
$yaml -join "`r`n" | Set-Content -Path "$AgentDir\agent.yaml" -Encoding utf8
Write-Ok "agent.yaml"

# --- 8. Chay cung Windows --------------------------------------------------
# Scheduled Task thay vi Windows Service: khong can quyen admin, va van tu bat
# lai khi agent chet. Chay luc dang nhap vi may dong goi luon dang nhap san.
Write-Step "Dang ky chay cung Windows"
schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
$action = "`"$python`" `"$AgentDir\hlv_pack_agent.py`" --config `"$AgentDir\agent.yaml`""
schtasks /Create /TN $TaskName /TR $action /SC ONLOGON /RL LIMITED /F | Out-Null
schtasks /Change /TN $TaskName /RI 5 2>$null | Out-Null
Write-Ok "Tac vu '$TaskName' se tu chay moi lan dang nhap Windows"

Write-Step "Khoi dong agent"
Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $python } | Stop-Process -Force -ErrorAction SilentlyContinue
schtasks /Run /TN $TaskName | Out-Null
Start-Sleep -Seconds 4
Write-Ok "Da chay"

# --- 9. Xong ---------------------------------------------------------------
Write-Host "`n=================================================================="
Write-Host " XONG" -ForegroundColor Green
Write-Host "=================================================================="
Write-Host @"

Con MOT buoc cuoi, lam tren trinh duyet cua may nay:

    $OdooUrl/pack_recorder/set_station

  Bam chon ban "$($enroll.station_name)". Chi lam mot lan.

Kiem tra:
  - Odoo > Ban dong goi > o "Agent goi lan cuoi" phai co gio, cap nhat lien tuc
  - Log agent:  $AgentDir\agent_run.log
  - Chay tay de xem log truc tiep:
      cd $AgentDir
      $python hlv_pack_agent.py --config agent.yaml --verbose

"@ -ForegroundColor White

$open = Read-Host "Mo trang chon ban ngay bay gio? (y/n)"
if ($open -eq 'y') { Start-Process "$OdooUrl/pack_recorder/set_station" }
