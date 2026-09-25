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
$PythonEmbedUrl = 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip'
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
# Truoc day goi winget de cai Python. Khong dung duoc o kho: may Win10 cu hoac ban
# LTSC khong co winget, cai xong thi PATH cua phien hien tai chua cap nhat, va buoc
# do doi quyen admin. Gio: uu tien Python san co, khong xai duoc thi tai ban NHUNG
# ve thang thu muc agent — khong cai gi vao may, khong can admin, khong dung PATH.

function Initialize-EmbeddedPython {
    $dir = "$AgentDir\python"
    $exe = "$dir\python.exe"

    if (Test-Path $exe) {
        $chk = Invoke-Native $exe @('-c', 'import requests, yaml')
        if ($chk.code -eq 0) { Write-Ok "Dung lai Python nhung da co san"; return $exe }
    }

    Write-Step "Tai Python nhung (~11MB, khong cai gi vao may)"
    $zip = "$env:TEMP\hlv_python_embed.zip"
    Invoke-WebRequest -Uri $PythonEmbedUrl -OutFile $zip
    Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
    Expand-Archive -Path $zip -DestinationPath $dir -Force
    Remove-Item -Force $zip -ErrorAction SilentlyContinue

    # Ban nhung chan site-packages bang file pythonNNN._pth. Khong bo comment dong
    # 'import site' thi pip cai xong nhung import van bao khong tim thay goi nao.
    Get-ChildItem -Path $dir -Filter 'python*._pth' | ForEach-Object {
        (Get-Content $_.FullName) -replace '^#\s*import site', 'import site' |
            Set-Content $_.FullName -Encoding ascii
    }

    Write-Step "Cai pip cho Python nhung"
    $getPip = "$env:TEMP\get-pip.py"
    Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getPip
    $r = Invoke-Native $exe @($getPip, '--quiet', '--no-warn-script-location')
    Remove-Item -Force $getPip -ErrorAction SilentlyContinue
    if ($r.code -ne 0) { Write-Bad "Khong cai duoc pip:"; Write-Host $r.out; exit 1 }

    $r = Invoke-Native $exe @('-m','pip','install','--quiet','--no-warn-script-location',
                              'requests','pyyaml')
    if ($r.code -ne 0) { Write-Bad "Khong cai duoc thu vien:"; Write-Host $r.out; exit 1 }
    Write-Ok "Python nhung san sang (khong dung toi Python cua may)"
    return $exe
}

Write-Step "Kiem tra Python"
$python = $null
foreach ($cmd in @('python', 'py')) {
    $r = Invoke-Native $cmd @('--version')
    if ($r.code -eq 0) { $python = (Get-Command $cmd).Source; Write-Ok $r.out.Trim(); break }
}

if ($python) {
    # Co Python chua chac dung duoc: thieu pythonw.exe (ban Store), pip bi chan boi
    # proxy cong ty, hoac ban qua cu. Thu cai thu vien ngay — that bai thi chuyen
    # sang ban nhung thay vi bo cuoc giua chung.
    $pyw = Join-Path (Split-Path $python) 'pythonw.exe'
    $r = Invoke-Native $python @('-m','pip','install','--quiet','--no-warn-script-location',
                                 'requests','pyyaml')
    if ($r.code -ne 0) {
        Write-Warn2 "Python cua may khong cai duoc thu vien - chuyen sang Python nhung."
        $python = $null
    } elseif (-not (Test-Path $pyw)) {
        Write-Warn2 "Python cua may khong co pythonw.exe - chuyen sang Python nhung."
        $python = $null
    } else {
        Write-Ok "requests, pyyaml"
    }
} else {
    Write-Warn2 "May chua co Python - se dung ban nhung, khong cai gi vao may."
}

if (-not $python) { $python = Initialize-EmbeddedPython }

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
Write-Step "Dang ky chay ngam cung Windows"

# pythonw.exe thay vi python.exe: khong bung cua so console nao. Log di ra
# C:\hlv_agent\agent.log vi khong con console de doc.
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) {
    $pythonw = $python
    Write-Warn2 "Khong thay pythonw.exe - agent se chay kem mot cua so console."
}

$isAdmin = ([Security.Principal.WindowsPrincipal] `
            [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# Webcam USB khong mo duoc tu tai khoan SYSTEM (session 0 bi cach ly khoi thiet
# bi cua nguoi dung). Co webcam thi buoc phai chay duoi tai khoan dang nhap,
# doi lai nguoi dung van tat duoc tac vu.
$hasUsbCam = ($camLines -join "`n") -match 'type:\s*usb'
if (-not $hasUsbCam -and (Test-Path $yamlPath)) {
    $hasUsbCam = (Get-Content $yamlPath -Raw) -match 'type:\s*usb'
}

$taskArgs = "`"$AgentDir\hlv_pack_agent.py`" --config `"$AgentDir\agent.yaml`""
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $taskArgs -WorkingDirectory $AgentDir

# MultipleInstances=IgnoreNew bien trigger lap thanh canh gac: cu 5 phut Windows
# thu chay lai, agent con song thi lan chay moi bi bo qua, chet thi duoc bat len.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries -StartWhenAvailable `
                -MultipleInstances IgnoreNew `
                -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
                -ExecutionTimeLimit ([TimeSpan]::Zero)
$tWatchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
                 -RepetitionInterval (New-TimeSpan -Minutes 5)

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$registered = $false
$protected = $false
try {
    if ($existing) {
        # -Force KHONG du de ghi de mot tac vu do phien co quyen cao hon tao ra:
        # Windows kiem ACL cua chinh tac vu, khong phai quyen tao tac vu moi. Phai
        # xoa truoc; xoa khong duoc thi bao ro chu dung nuot (da gap that: tac vu cu
        # van chay python.exe nen van bung cua so console, ma script bao cai xong).
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    }

    if ($isAdmin -and -not $hasUsbCam) {
        # Chay duoi SYSTEM: bat tu luc khoi dong may (khong can ai dang nhap),
        # va nguoi dung thuong khong tat duoc neu khong co quyen admin.
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' `
                         -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskName $TaskName -Action $action `
            -Trigger @((New-ScheduledTaskTrigger -AtStartup), $tWatchdog) `
            -Settings $settings -Principal $principal | Out-Null
        $protected = $true
        Write-Ok "Chay duoi tai khoan SYSTEM - can quyen admin moi dung duoc"
    } else {
        # PHAI khai ro -User va -RunLevel Limited: thieu chung thi
        # Register-ScheduledTask doi quyen admin va bao Access denied.
        $me = "$env:USERDOMAIN\$env:USERNAME"
        Register-ScheduledTask -TaskName $TaskName -Action $action `
            -Trigger @((New-ScheduledTaskTrigger -AtLogOn -User $me), $tWatchdog) `
            -Settings $settings -User $me -RunLevel Limited | Out-Null
        Write-Ok "Chay khi dang nhap Windows"
        if ($hasUsbCam) {
            Write-Warn2 "Ban nay co webcam USB nen khong chay duoi SYSTEM duoc."
        } elseif (-not $isAdmin) {
            Write-Warn2 "Chay lai bang PowerShell (Admin) de nguoi dung khong tat duoc agent."
        }
    }
    $registered = $true
    Write-Ok "Chay ngam bang pythonw, tu bat lai trong vong 5 phut neu bi tat"
} catch {
    Write-Bad "KHONG thay duoc tac vu '$TaskName': $($_.Exception.Message)"
    if ($existing) {
        $oldExe = $existing.Actions[0].Execute
        Write-Bad "Tac vu CU van con nguyen va van dang chay: $oldExe"
        if ($oldExe -notlike '*pythonw.exe') {
            Write-Bad "=> DAY LA LY DO VAN THAY CUA SO CONSOLE HIEN LEN."
        }
        Write-Host ''
        Write-Host '   Tac vu cu duoc tao boi mot phien co quyen cao hon nen phien nay khong' -ForegroundColor Yellow
        Write-Host '   sua duoc no. Cach sua:' -ForegroundColor Yellow
        Write-Host '     1. Dong cua so nay' -ForegroundColor White
        Write-Host '     2. Mo PowerShell bang chuot phai > "Run as administrator"' -ForegroundColor White
        Write-Host '     3. Dan lai dung lenh cai nay' -ForegroundColor White
        Write-Host ''
    } else {
        Write-Warn2 "Agent van chay duoc bang tay, xem lenh o cuoi."
    }
}

Write-Step "Khoi dong agent"
if (-not $registered) {
    Write-Warn2 "Bo qua buoc khoi dong: tac vu moi chua dang ky duoc (xem huong dan ben tren)."
}
try {
    if (-not $registered) { throw 'tac vu moi chua dang ky duoc' }
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Start-Sleep -Seconds 6
    $logFile = "$AgentDir\agent.log"
    if (Test-Path $logFile) {
        $tail = Get-Content $logFile -Tail 3
        if ($tail -match 'Odoo t') {
            Write-Bad "Odoo tu choi agent - kiem lai station_key/token"
            $tail | ForEach-Object { Write-Host "     $_" }
        } else {
            Write-Ok "Agent dang chay ngam (khong co cua so)"
        }
    } else {
        Write-Warn2 "Chua thay agent.log - xem lai bang lenh chay tay o cuoi."
    }
} catch {
    Write-Warn2 "Chua chay duoc tu dong: $($_.Exception.Message)"
}

# --- 9. Xong ---------------------------------------------------------------
Write-Host "`n=================================================================="
Write-Host " XONG" -ForegroundColor Green
Write-Host "=================================================================="
Write-Host @"

Con MOT buoc cuoi, lam tren trinh duyet cua may nay:

    $OdooUrl/pack_recorder/set_station

  Bam chon dung ban dong goi. Chi lam mot lan cho moi may.

Agent chay NGAM, khong co cua so. Kiem tra:

  - Odoo > Ban dong goi > cot "Tinh trang agent" phai la "Dang chay"
  - Log:  $AgentDir\agent.log
      Get-Content $AgentDir\agent.log -Tail 20 -Wait

  - Chay tay de xem log truc tiep tren man hinh:
      & "$python" "$AgentDir\hlv_pack_agent.py" --config "$AgentDir\agent.yaml" --verbose

Dung agent (can quyen admin neu tac vu chay duoi SYSTEM):
      Stop-ScheduledTask  -TaskName "$TaskName"
      Disable-ScheduledTask -TaskName "$TaskName"

"@ -ForegroundColor White

$open = Read-Host "Mo trang chon ban ngay bay gio? (y/n)"
if ($open -eq 'y') { Start-Process "$OdooUrl/pack_recorder/set_station" }
