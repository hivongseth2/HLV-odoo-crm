# Cai dat agent ghi hinh dong goi - chay tren may dong goi
#
# Chay mot lenh duy nhat (lay o form Ban dong goi trong Odoo):
#   $env:HLV_ODOO_URL='https://...'; irm https://.../pack_agent/download/setup | iex
#
# Script tu lam: tai agent + ffmpeg, hoi ma cai dat, hoi va KIEM URL camera,
# ghi agent.yaml, dang ky chay cung Windows. Khong can quyen admin.

$ErrorActionPreference = 'Stop'
$AgentDir  = 'C:\hlv_agent'
$FfmpegUrl = 'https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip'
$TaskName  = 'HLV Pack Agent'

function Write-Step($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "   [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "   [!] $msg" -ForegroundColor Yellow }
function Write-Bad($msg)  { Write-Host "   [X] $msg" -ForegroundColor Red }

# PowerShell 5.1 bien stderr cua file exe thanh loi terminating khi
# ErrorActionPreference = Stop, du chuong trinh chi dang ghi chu thich binh
# thuong. Moi lenh exe phai di qua day, dung goi thang.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out  = & $Exe @Arguments 2>&1 | Out-String
        $code = $LASTEXITCODE
        return @{ code = $code; out = $out }
    } finally { $ErrorActionPreference = $prev }
}

Write-Host "=================================================================="
Write-Host " Cai dat agent ghi hinh dong goi" -ForegroundColor White
Write-Host "=================================================================="

# --- 1. Dia chi Odoo -------------------------------------------------------
$OdooUrl = $env:HLV_ODOO_URL
if (-not $OdooUrl) { $OdooUrl = Read-Host "`nDia chi Odoo (vi du https://hoanglongvu.odoo.com)" }
$OdooUrl = $OdooUrl.TrimEnd('/')

# --- 2. Python -------------------------------------------------------------
Write-Step "Kiem tra Python"
$python = $null
foreach ($cmd in @('python', 'py')) {
    $r = Invoke-Native $cmd @('--version')
    if ($r.code -eq 0) { $python = (Get-Command $cmd).Source; Write-Ok $r.out.Trim(); break }
}
if (-not $python) {
    Write-Warn2 "Chua co Python. Dang cai bang winget..."
    $r = Invoke-Native 'winget' @('install','-e','--id','Python.Python.3.12','--silent',
                                  '--accept-package-agreements','--accept-source-agreements')
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path','User')
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $python) {
        Write-Bad "Khong tu cai duoc Python."
        Write-Host "   Tai tai https://www.python.org/downloads/ - nho tick" -ForegroundColor Red
        Write-Host "   'Add python.exe to PATH', roi chay lai lenh cai nay." -ForegroundColor Red
        exit 1
    }
    Write-Ok "Da cai Python"
}

Write-Step "Cai thu vien Python"
$r = Invoke-Native $python @('-m','pip','install','--quiet','--upgrade','requests','pyyaml')
if ($r.code -ne 0) { Write-Bad "pip loi:"; Write-Host $r.out; exit 1 }
Write-Ok "requests, pyyaml"

# --- 3. Thu muc + agent ----------------------------------------------------
Write-Step "Chuan bi $AgentDir"
New-Item -ItemType Directory -Force -Path $AgentDir, "$AgentDir\rec" | Out-Null
Invoke-WebRequest -Uri "$OdooUrl/pack_agent/download/agent" -OutFile "$AgentDir\hlv_pack_agent.py"
Write-Ok "hlv_pack_agent.py"

# --- 4. ffmpeg -------------------------------------------------------------
if ((Test-Path "$AgentDir\ffmpeg.exe") -and (Test-Path "$AgentDir\ffprobe.exe")) {
    Write-Step "ffmpeg da co, bo qua"
} else {
    Write-Step "Tai ffmpeg (~190MB, hoi lau)"
    $zip = "$env:TEMP\ffmpeg_hlv.zip"
    $tmp = "$env:TEMP\ffmpeg_hlv"
    Invoke-WebRequest -Uri $FfmpegUrl -OutFile $zip
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    foreach ($exe in @('ffmpeg.exe','ffprobe.exe')) {
        Get-ChildItem -Path $tmp -Recurse -Filter $exe | Select-Object -First 1 |
            ForEach-Object { Copy-Item $_.FullName "$AgentDir\$exe" -Force }
    }
    Remove-Item -Recurse -Force $tmp, $zip -ErrorAction SilentlyContinue
    Write-Ok "ffmpeg.exe + ffprobe.exe"
}
$ffmpeg  = "$AgentDir\ffmpeg.exe"
$ffprobe = "$AgentDir\ffprobe.exe"

# --- 5. Cau hinh ban: ma cai dat, hoac dung lai cai da co -------------------
$yamlPath = "$AgentDir\agent.yaml"
$enroll = $null

if (Test-Path $yamlPath) {
    # Lan cai truoc da lay duoc station_key + token roi moi hong o buoc sau. Ma
    # cai dat chi dung mot lan, nen cho dung lai thay vi bat vao Odoo xin ma moi.
    $old = Get-Content $yamlPath -Raw
    if ($old -match 'station_key:\s*"([^"]+)"' ) {
        $oldKey = $Matches[1]
        if ($old -match 'token:\s*"([^"]+)"') {
            $oldToken = $Matches[1]
            Write-Step "Da co cau hinh cu cho ban ma $oldKey"
            $reuse = Read-Host "   Dung lai station_key/token cu va chi khai lai camera? (y/n)"
            if ($reuse -eq 'y') {
                $body = @{ jsonrpc='2.0'; method='call'; params=@{
                    station_key=$oldKey; token=$oldToken; active_ids=@(); agent_version='setup' } } | ConvertTo-Json
                $chk = Invoke-RestMethod -Uri "$OdooUrl/pack_agent/poll" -Method Post `
                                         -ContentType 'application/json' -Body $body
                if ($chk.result.ok) {
                    Write-Ok "Cau hinh cu con dung"
                    $enroll = @{ station_key=$oldKey; token=$oldToken
                                 station_name='(dung lai cau hinh cu)'; warehouse=''
                                 cameras=@() }
                } else {
                    Write-Warn2 "Cau hinh cu khong con dung, phai xin ma cai dat moi."
                }
            }
        }
    }
}

if (-not $enroll) {
    Write-Step "Lay cau hinh ban dong goi tu Odoo"
    Write-Host "   Odoo: Ton kho > Cau hinh > Video dong goi > Ban dong goi"
    Write-Host "   Chon dung ban may nay dang dat, bam 'Tao ma cai dat'."
    for ($i = 1; $i -le 3; $i++) {
        $code = Read-Host "`n   Ma cai dat (dang XXXX-XXXX)"
        $body = @{ jsonrpc='2.0'; method='call'; params=@{ code=$code } } | ConvertTo-Json
        $resp = Invoke-RestMethod -Uri "$OdooUrl/pack_agent/enroll" -Method Post `
                                  -ContentType 'application/json' -Body $body
        if ($resp.result.ok) { $enroll = $resp.result; break }
        Write-Warn2 $resp.result.error
    }
    if (-not $enroll) { Write-Bad "Het luot thu. Tao ma moi trong Odoo roi chay lai."; exit 1 }
    Write-Ok "Ban: $($enroll.station_name) - $($enroll.warehouse)"
}

# --- 6. Khai va KIEM camera ------------------------------------------------
# Kiem ngay tai cho. Go nham rstp:// thay vi rtsp://, sai mat khau, sai IP - phai
# biet BAY GIO, chu khong phai luc khach khieu nai moi phat hien khong co video.
function Test-RtspUrl {
    param([string]$Url)
    if ($Url -notmatch '^(?i)rtsp://') {
        $got = ($Url -split '://')[0]
        return @{ ok=$false; msg="URL phai bat dau bang rtsp:// (ban go '$got')" }
    }
    Write-Host "   ... dang thu ket noi camera" -ForegroundColor DarkGray
    $r = Invoke-Native $ffprobe @(
        '-v','error','-rtsp_transport','tcp','-timeout','8000000',
        '-select_streams','v:0',
        '-show_entries','stream=codec_name,width,height',
        '-of','default=noprint_wrappers=1:nokey=0','-i',$Url)
    if ($r.code -ne 0 -or $r.out -notmatch 'width=') {
        $first = ($r.out -split "`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
        return @{ ok=$false; msg="khong ket noi duoc: $first" }
    }
    $w = if ($r.out -match 'width=(\d+)')  { $Matches[1] } else { '?' }
    $h = if ($r.out -match 'height=(\d+)') { $Matches[1] } else { '?' }
    $c = if ($r.out -match 'codec_name=(\w+)') { $Matches[1] } else { '?' }
    return @{ ok=$true; msg="$c ${w}x${h}" }
}

Write-Step "Khai camera"
if ($enroll.cameras.Count -eq 0) {
    Write-Warn2 "Khong co camera nao tu Odoo - giu nguyen phan cameras trong agent.yaml cu."
}

$camLines = @()
foreach ($cam in $enroll.cameras) {
    Write-Host "`n   Camera '$($cam.name)' (ma $($cam.code))"
    Write-Host "   - Camera IP : dan URL RTSP (lay trong OBS, nguon VLC)"
    Write-Host "   - Webcam USB: go chu  usb  roi Enter"

    while ($true) {
        $ans = (Read-Host "   URL RTSP hoac 'usb'").Trim()

        if ($ans.ToLower() -eq 'usb') {
            Write-Host "   Webcam may nay thay:" -ForegroundColor Yellow
            $r = Invoke-Native $ffmpeg @('-hide_banner','-list_devices','true','-f','dshow','-i','dummy')
            ($r.out -split "`n") | Where-Object { $_ -match '\(video\)' -and $_ -notmatch 'Alternative' } |
                ForEach-Object { Write-Host "     $($_.Trim())" }
            $dev  = Read-Host "   Chep chinh xac ten webcam trong dau nhay"
            $size = Read-Host "   Do phan giai (Enter = 1280x720)"; if (-not $size) { $size = '1280x720' }
            $fps  = Read-Host "   FPS (Enter = 15)";                if (-not $fps)  { $fps  = '15' }
            $camLines += @(
                "  `"$($cam.code)`":", "    type: usb", "    device: `"$dev`"",
                "    size: `"$size`"", "    fps: $fps", "    bitrate: `"3M`"",
                "    overlay_time: true")
            break
        }

        $check = Test-RtspUrl -Url $ans
        if ($check.ok) {
            Write-Ok "Camera tra loi: $($check.msg)"
            if ($ans -match 'subtype=1') {
                Write-Warn2 "URL dang dung subtype=1 (luong phu, mo). Nen doi thanh subtype=0."
            }
            $camLines += "  `"$($cam.code)`": `"$ans`""
            break
        }

        Write-Bad $check.msg
        $again = Read-Host "   Thu lai? (y = nhap lai / n = bo qua camera nay)"
        if ($again -ne 'y') {
            Write-Warn2 "Bo qua '$($cam.name)' - camera nay se khong co video."
            break
        }
    }
}

# --- 7. Ghi agent.yaml -----------------------------------------------------
Write-Step "Ghi cau hinh"
if ($camLines.Count -eq 0 -and (Test-Path $yamlPath)) {
    Write-Warn2 "Khong khai camera nao moi - giu nguyen $yamlPath"
} else {
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
    $yaml -join "`r`n" | Set-Content -Path $yamlPath -Encoding utf8
    Write-Ok "agent.yaml"
}

# --- 8. Chay cung Windows --------------------------------------------------
# Scheduled Task chu khong phai Windows Service: khong can quyen admin. Dung
# cmdlet ScheduledTasks thay vi schtasks.exe de khoi dinh chuyen stderr cua exe.
Write-Step "Dang ky chay cung Windows"
$taskArgs = "`"$AgentDir\hlv_pack_agent.py`" --config `"$AgentDir\agent.yaml`""
try {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }

    $action  = New-ScheduledTaskAction -Execute $python -Argument $taskArgs -WorkingDirectory $AgentDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    # RestartCount/Interval la phan lam watchdog: agent chet thi Windows bat lai.
    # ExecutionTimeLimit = 0 nghia la khong gioi han, vi agent chay ca ngay.
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                    -DontStopIfGoingOnBatteries -StartWhenAvailable `
                    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
                    -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
                           -Settings $settings -Force | Out-Null
    Write-Ok "Tac vu '$TaskName' se tu chay moi lan dang nhap Windows"
} catch {
    Write-Warn2 "Khong dang ky duoc tac vu tu dong: $($_.Exception.Message)"
    Write-Warn2 "Agent van chay duoc bang tay, xem lenh o cuoi."
}

Write-Step "Khoi dong agent"
try {
    Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Start-ScheduledTask
    Start-Sleep -Seconds 5
    Write-Ok "Da chay"
} catch {
    Write-Warn2 "Chua chay duoc tu dong, khoi dong bang tay theo lenh o cuoi."
}

# --- 9. Xong ---------------------------------------------------------------
Write-Host "`n=================================================================="
Write-Host " XONG" -ForegroundColor Green
Write-Host "=================================================================="
Write-Host @"

Con MOT buoc cuoi, lam tren trinh duyet cua may nay:

    $OdooUrl/pack_recorder/set_station

  Bam chon dung ban dong goi. Chi lam mot lan cho moi may.

Kiem tra:
  - Odoo > Ban dong goi > o "Agent goi lan cuoi" phai co gio, cap nhat lien tuc
  - Chay tay de xem log truc tiep:
      cd $AgentDir
      & "$python" hlv_pack_agent.py --config agent.yaml --verbose

"@ -ForegroundColor White

$open = Read-Host "Mo trang chon ban ngay bay gio? (y/n)"
if ($open -eq 'y') { Start-Process "$OdooUrl/pack_recorder/set_station" }
