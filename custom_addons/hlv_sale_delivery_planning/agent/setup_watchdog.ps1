# Cai watchdog + in truc tiep cho MAY KHO - chay mot lenh duy nhat
#
#   $env:HLV_ODOO_URL='https://hoanglongvu.odoo.com'; irm https://hoanglongvu.odoo.com/iot_watchdog/download/setup | iex
#
# Script tu lam: tai watchdog tu Odoo, hoi thong so, kiem may in, chay thu mot luot,
# dang ky tac vu chay ngam. Khong phai chep file qua UltraViewer nua.
#
# Vi sao khong dat trong repo: may kho khong co repo. Odoo la nguon phat duy nhat - sua
# watchdog xong, moi may chay lai dung lenh tren la co ban moi.
#
# CAN QUYEN ADMINISTRATOR (ghi C:\hlv, C:\ProgramData, tao tac vu, bat lai service).
# Script tu xin quyen neu chua co.

$ErrorActionPreference = 'Stop'

$Dir      = 'C:\hlv'
$TaskName = 'HLV IoT Watchdog'
$LogFile  = "$env:ProgramData\HLV\iot_watchdog.log"
$CfgFile  = "$env:ProgramData\HLV\iot_watchdog.config.json"

function Step($m) { Write-Host "`n>> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "   [OK] $m" -ForegroundColor Green }
function Warn2($m){ Write-Host "   [!]  $m" -ForegroundColor Yellow }
function Bad($m)  { Write-Host "   [X]  $m" -ForegroundColor Red }
function Stop-Here($m) {
    Bad $m
    Write-Host "`nDung tai day. Sua xong chay lai dung lenh tren." -ForegroundColor Red
    Read-Host 'Nhan Enter de dong'
    exit 1
}

# --- 0. Quyen Administrator --------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "`nCan quyen Administrator - dang mo lai cua so co quyen (bam Yes)..." -ForegroundColor Yellow
    # Chay lai CHINH LENH MOT DONG nay trong cua so co quyen. Khong dung $PSCommandPath
    # vi script duoc nap tu internet qua 'irm | iex', khong ton tai duoi dang file.
    $url = $env:HLV_ODOO_URL
    if (-not $url) { $url = Read-Host 'Dia chi Odoo (vi du https://hoanglongvu.odoo.com)' }
    $url = $url.TrimEnd('/')
    $inner = "`$env:HLV_ODOO_URL='$url'; irm $url/iot_watchdog/download/setup | iex"
    Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-Command',$inner
    exit
}

Write-Host '=================================================================='
Write-Host ' Cai watchdog may kho (heartbeat + in truc tiep)' -ForegroundColor White
Write-Host "=================================================================="
Write-Host " May: $env:COMPUTERNAME    Nguoi dung: $env:USERNAME"

# --- 1. Dia chi Odoo ---------------------------------------------------------------
Step 'Dia chi Odoo'
$OdooUrl = $env:HLV_ODOO_URL
if (-not $OdooUrl) { $OdooUrl = Read-Host '   Dia chi Odoo (vi du https://hoanglongvu.odoo.com)' }
$OdooUrl = $OdooUrl.TrimEnd('/')
Ok $OdooUrl

# --- 2. Tai 2 file watchdog tu Odoo -------------------------------------------------
Step "Tai watchdog ve $Dir"
if (-not (Test-Path $Dir)) { New-Item -ItemType Directory -Force -Path $Dir | Out-Null }
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
foreach ($f in @(@{ n = 'watchdog'; f = 'iot_watchdog_windows.ps1' },
                 @{ n = 'hidden';   f = 'run_watchdog_hidden.vbs' })) {
    $dest = Join-Path $Dir $f.f
    try {
        Invoke-WebRequest -Uri "$OdooUrl/iot_watchdog/download/$($f.n)" -OutFile $dest -UseBasicParsing
        Ok "$($f.f)  ($((Get-Item $dest).Length) bytes)"
    } catch {
        Stop-Here "Khong tai duoc $($f.f): $($_.Exception.Message)"
    }
}
# PowerShell 5.1 doc file .ps1 khong BOM theo ANSI => chu Viet trong comment thanh dau
# nhay thong minh va script loi cu phap ngay dong dau. Invoke-WebRequest giu nguyen byte
# nen BOM con, nhung van kiem lai cho chac - hong cho nay rat kho doan.
$ps1 = Join-Path $Dir 'iot_watchdog_windows.ps1'
$head = [System.IO.File]::ReadAllBytes($ps1)[0..2]
if (-not ($head[0] -eq 0xEF -and $head[1] -eq 0xBB -and $head[2] -eq 0xBF)) {
    Warn2 'File tai ve thieu BOM - tieng Viet trong script co the loi. Bao lai nguoi phat trien.'
}

# --- 3. Thong so ---------------------------------------------------------------------
Step 'Thong so ket noi (Enter = giu gia tri da luu lan truoc)'
$cu = $null
if (Test-Path $CfgFile) {
    try { $cu = (Get-Content $CfgFile -Raw -Encoding UTF8) | ConvertFrom-Json } catch { $cu = $null }
    if ($cu) { Ok "Da co cau hinh cu, Enter de giu tung o" }
}
function Ask($label, $old, $example) {
    $show = if ($old) { $old } else { "(chua co) vi du: $example" }
    Write-Host ""
    Write-Host "   $label"
    Write-Host "     hien tai: $show" -ForegroundColor DarkGray
    $new = Read-Host '     nhap moi'
    if ([string]::IsNullOrWhiteSpace($new)) { return $old }
    return $new.Trim()
}

$Token = Ask 'Token watchdog (Odoo > Cai dat > HLV Delivery Planner)' $cu.Token 'chuoi dai ngau nhien'
$WhCode = Ask 'Ma kho trong Odoo (stock.warehouse.code)' $cu.WarehouseCode 'KBC'

Write-Host "`n   May in Windows tren may nay:" -ForegroundColor DarkGray
try { Get-Printer | ForEach-Object { Write-Host "     - $($_.Name)" -ForegroundColor DarkGray } }
catch { Write-Host '     (khong liet ke duoc)' -ForegroundColor DarkGray }
$Printer = Ask 'Ten may in phieu lay hang' $cu.PrinterName 'Xprinter XP-80'

if (-not $Token -or -not $WhCode) { Stop-Here 'Thieu token hoac ma kho.' }

# --- 4. Cong cu in PDF ---------------------------------------------------------------
Step 'Cong cu in PDF (PowerShell khong tu in PDF duoc)'
$Pdf = $cu.PdfPrintExe
$sumatra = Join-Path $Dir 'sumatra\SumatraPDF.exe'
if (-not $Pdf -and (Test-Path $sumatra)) { $Pdf = $sumatra }
if ($Pdf -and (Test-Path $Pdf)) {
    # Bay da gap that: file tai tu trang Sumatra la ban INSTALLER, chi chay nhu trinh in
    # khi co libmupdf.dll NAM CANH. Thieu DLL => no mo che do installer roi thoat voi
    # ExitCode=0, khong in gi, khong bao loi gi.
    if ((Split-Path -Leaf $Pdf) -like 'Sumatra*' -and
        -not (Test-Path (Join-Path (Split-Path -Parent $Pdf) 'libmupdf.dll'))) {
        Warn2 "Thieu libmupdf.dll canh $Pdf => dang la ban INSTALLER, se KHONG in duoc."
        Warn2 "Sua: chay  $Pdf -x -d `"$Dir\sumatra`"  roi chay lai script nay."
        $Pdf = ''
    } else {
        Ok $Pdf
    }
} else {
    Warn2 'Chua co cong cu in PDF. In truc tiep se khong dang tin.'
    Warn2 "Tai SumatraPDF portable, giai nen vao $Dir\sumatra roi chay lai script nay."
    $Pdf = ''
}

# --- 5. Chay thu mot luot + luu cau hinh ---------------------------------------------
Step 'Chay thu mot luot (gui heartbeat that ve Odoo) va luu cau hinh'
$args = @('-OdooUrl', $OdooUrl, '-Token', $Token, '-WarehouseCode', $WhCode,
          '-LocalDispatch', '-SaveConfig', '-LoopSeconds', '0')
if ($Printer) { $args += @('-PrinterName', $Printer) }
if ($Pdf)     { $args += @('-PdfPrintExe', $Pdf, '-PdfPrintSettings', 'noscale') }

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ps1 @args
if ($LASTEXITCODE -ne 0) {
    Bad "Chay thu tra ve ma loi $LASTEXITCODE."
    Warn2 'Hay gap: sai dia chi Odoo, sai token, sai ma kho, hoac may khong ra duoc internet.'
    Warn2 "Xem log: $LogFile"
    Stop-Here 'Chua tao tac vu - sua xong chay lai.'
}
Ok 'Chay thu xong, khong loi.'

# --- 6. Tac vu chay ngam --------------------------------------------------------------
Step "Tac vu '$TaskName'"
# 10 phut/lan chi de HOI SINH tien trinh neu no chet; nhip that la vong lap 120 giay ben
# trong. Script co mutex chong chay trung nen luot nao thay vong lap con song la tu thoat.
# /IT = chay trong phien dang nhap => popup canh bao hien duoc cho nguoi ngoi o kho.
$vbs = Join-Path $Dir 'run_watchdog_hidden.vbs'
schtasks /Create /TN "$TaskName" /SC MINUTE /MO 10 /RL HIGHEST /IT /F /TR "wscript.exe `"$vbs`" -LoopSeconds 120" | Out-Null
if ($LASTEXITCODE -ne 0) { Stop-Here "Khong tao duoc tac vu (ma $LASTEXITCODE)." }
Ok 'Da tao tac vu.'

schtasks /Run /TN "$TaskName" | Out-Null
if ($LASTEXITCODE -eq 0) { Ok 'Da bat chay ngay.' } else { Warn2 'Chua bat duoc ngay, luot sau tu chay.' }

# --- 7. Service Odoo IoT: tu chay khi boot, cho mang len truoc ------------------------
Step 'Service Odoo IoT'
$svc = Get-CimInstance Win32_Service -Filter "Name='odoo-server-18.0'" -ErrorAction SilentlyContinue
if (-not $svc) {
    Warn2 'Khong thay service odoo-server-18.0 tren may nay (may nay co phai may kho khong?).'
} else {
    Ok "Trang thai: $($svc.State), khoi dong: $($svc.StartMode)"
    if ($svc.StartMode -ne 'Auto') {
        Warn2 "StartMode dang la $($svc.StartMode) - service se khong tu chay khi bat may."
    }
    # delayed-auto: service khoi dong o dot dau cua boot se chay TRUOC khi card mang co IP,
    # luc do no tu dang ky voi Odoo bang 127.0.0.1 (dung ban ghi hop IoT thua ra da gap
    # ngay 24/09) va sang hom sau phai restart tay. Cho tre mot nhip la het.
    & sc.exe config 'odoo-server-18.0' start= delayed-auto | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok 'Da dat Automatic (Delayed Start).' } else { Warn2 'Khong doi duoc kieu khoi dong.' }
    # Tu bat lai 3 lan neu service chet, moi lan cach 60 giay.
    & sc.exe failure 'odoo-server-18.0' reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok 'Da dat tu bat lai khi service chet.' }
}

# --- Ket ------------------------------------------------------------------------------
Start-Sleep -Seconds 5
Write-Host "`n=================================================================="
Write-Host ' XONG' -ForegroundColor Green
Write-Host '=================================================================='
schtasks /Query /TN "$TaskName" /FO LIST /V |
    Select-String -Pattern 'TaskName|Status|Last Run Time|Last Result|Next Run Time'
Write-Host "`n 8 dong cuoi cua log:" -ForegroundColor DarkGray
if (Test-Path $LogFile) { Get-Content -LiteralPath $LogFile -Tail 8 }

Write-Host ""
Write-Host " Log      : $LogFile"
Write-Host " Cau hinh : $CfgFile  (co token, chi admin doc/ghi duoc)"
Write-Host " Go       : schtasks /Delete /TN `"$TaskName`" /F"
Write-Host ""
Write-Host " Kiem cuoi: vao Odoo > Kho hang > kho $WhCode > 'Watchdog: lan cuoi nhan tin hieu'"
Write-Host " phai nhay len gio hien tai trong vong 2 phut."
Write-Host ""
Read-Host 'Nhan Enter de dong'
