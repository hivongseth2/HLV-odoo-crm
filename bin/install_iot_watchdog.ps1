#Requires -Version 5.1
<#
=====================================================================================
 install_iot_watchdog.ps1 — CÀI WATCHDOG + IN TỰ ĐỘNG LÊN MÁY KHO, chạy một lần là xong.
=====================================================================================
 Bấm đôi vào install_iot_watchdog.cmd (cùng thư mục). Script tự xin quyền Administrator
 — cần quyền đó để: ghi vào C:\hlv và C:\ProgramData\HLV, bật lại service Odoo IoT khi
 nó tắt, và tạo tác vụ /RL HIGHEST.

 Cài đủ một máy kho gồm 6 bước, dừng ngay khi bước nào hỏng:
   1. Kiểm quyền Administrator (tự xin nếu chưa có)
   2. Chép iot_watchdog_windows.ps1 + run_watchdog_hidden.vbs vào C:\hlv
   3. Hỏi thông số (Enter = giữ giá trị đã lưu lần trước)
   4. Chạy thử MỘT LẦN kèm -SaveConfig: vừa kiểm kết nối, vừa ghi file cấu hình
   5. Tạo tác vụ "HLV IoT Watchdog" — 10 phút/lần gọi vòng lặp 2 phút, chạy ẩn
   6. Bật chạy ngay rồi soát lại trạng thái + log

 Watchdog làm gì trên máy kho:
   - Gửi heartbeat về Odoo mỗi 2 phút. Im lặng quá lâu thì Odoo gửi cảnh báo.
   - Canh service Odoo IoT và Spooler, tắt thì bật lại; job in treo thì xoá.
   - Nếu bật -LocalDispatch: TỰ nhận phiếu cần in từ Odoo và in thẳng ra máy in Windows,
     KHÔNG cần mở tab "Điều phối Giao hàng" nào. Đây là đường in đáng tin nhất.

 LÀM TRƯỚC TRONG ODOO (một lần): Cài đặt > HLV Delivery Planner > "Token watchdog máy
 chủ kho" — để trống thì tính năng heartbeat tắt hẳn. Đặt một chuỗi dài ngẫu nhiên.

 Gỡ: schtasks /Delete /TN "HLV IoT Watchdog" /F
=====================================================================================
#>

[CmdletBinding()]
param(
    # Bỏ qua bước chạy thử (chỉ dùng khi đã biết chắc cấu hình đúng).
    [switch]$SkipTest
)

$ErrorActionPreference = 'Stop'
$TEN_TAC_VU  = 'HLV IoT Watchdog'
$THU_MUC     = 'C:\hlv'
$FILE_CONFIG = "$env:ProgramData\HLV\iot_watchdog.config.json"
$FILE_LOG    = "$env:ProgramData\HLV\iot_watchdog.log"

function Buoc($so, $chu) {
    Write-Host ""
    Write-Host "[$so] $chu" -ForegroundColor Cyan
    Write-Host ("-" * 70)
}
function Ok($chu)   { Write-Host "  OK   $chu" -ForegroundColor Green }
function Loi($chu)  { Write-Host "  LỖI  $chu" -ForegroundColor Red }
function Nhac($chu) { Write-Host "  ->   $chu" -ForegroundColor Yellow }
function Dung($chu) {
    Loi $chu
    Write-Host ""
    Write-Host "Dừng tại đây. Sửa xong chạy lại file này." -ForegroundColor Red
    Read-Host "Nhấn Enter để đóng"
    exit 1
}

# --- 1. Quyền Administrator ---------------------------------------------------------
$laAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $laAdmin) {
    Write-Host ""
    Write-Host "Cần quyền Administrator — đang mở lại cửa sổ có quyền..." -ForegroundColor Yellow
    Write-Host "(bấm Yes ở hộp thoại Windows hiện lên)" -ForegroundColor DarkGray
    $tham = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    if ($SkipTest) { $tham += '-SkipTest' }
    try {
        Start-Process powershell.exe -Verb RunAs -ArgumentList $tham
    } catch {
        Write-Host "Bạn đã từ chối cấp quyền. Không cài được." -ForegroundColor Red
        Read-Host "Nhấn Enter để đóng"
    }
    exit
}

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor White
Write-Host "  CÀI WATCHDOG IoT — máy $env:COMPUTERNAME"
Write-Host "=====================================================================" -ForegroundColor White
Buoc 1 "Quyền Administrator"
Ok "Đang chạy với quyền Administrator."

# --- 2. Chép file ------------------------------------------------------------------
Buoc 2 "Chép script vào $THU_MUC"

$nguon = $PSScriptRoot
$canCo = @('iot_watchdog_windows.ps1', 'run_watchdog_hidden.vbs')
foreach ($f in $canCo) {
    if (-not (Test-Path (Join-Path $nguon $f))) {
        Dung "Không thấy $f trong $nguon — chạy file này từ thư mục bin\ của repo."
    }
}
if (-not (Test-Path $THU_MUC)) { New-Item -ItemType Directory -Force -Path $THU_MUC | Out-Null }
foreach ($f in $canCo) {
    Copy-Item (Join-Path $nguon $f) (Join-Path $THU_MUC $f) -Force
    Ok "$f"
}
# Chép vào C:\hlv chứ không chạy thẳng từ repo: repo có thể bị git pull/checkout đổi
# nhánh giữa chừng, máy kho phải chạy được kể cả khi không ai đụng tới repo nữa.
Nhac "Chạy từ $THU_MUC, không phụ thuộc repo — git pull hay đổi nhánh không làm kho chết."

$ps1  = Join-Path $THU_MUC 'iot_watchdog_windows.ps1'
$vbs  = Join-Path $THU_MUC 'run_watchdog_hidden.vbs'

# --- 3. Hỏi thông số ----------------------------------------------------------------
Buoc 3 "Thông số (Enter = giữ giá trị đã lưu lần trước)"

$cu = $null
if (Test-Path $FILE_CONFIG) {
    try { $cu = (Get-Content $FILE_CONFIG -Raw -Encoding UTF8) | ConvertFrom-Json } catch { $cu = $null }
}
if ($cu) { Ok "Đã có cấu hình cũ tại $FILE_CONFIG — Enter để giữ từng ô." }

function Hoi($nhan, $giaTriCu, $viDu) {
    $hienThi = if ($giaTriCu) { $giaTriCu } else { "(chưa có) ví dụ: $viDu" }
    Write-Host ""
    Write-Host "  $nhan"
    Write-Host "    hiện tại: $hienThi" -ForegroundColor DarkGray
    $moi = Read-Host "    nhập mới"
    if ([string]::IsNullOrWhiteSpace($moi)) { return $giaTriCu }
    return $moi.Trim()
}
function HoiCo($nhan, $macDinh) {
    $g = if ($macDinh) { 'C' } else { 'K' }
    Write-Host ""
    $tl = Read-Host "  $nhan  (C/K, Enter = $g)"
    if ([string]::IsNullOrWhiteSpace($tl)) { return $macDinh }
    return ($tl.Trim().ToUpper() -eq 'C')
}

$odooUrl  = Hoi 'Địa chỉ Odoo'                     $cu.OdooUrl       'https://hoanglongvu.odoo.com'
$token    = Hoi 'Token watchdog (ở Settings > HLV Delivery Planner)' $cu.Token 'chuỗi dài ngẫu nhiên'
$maKho    = Hoi 'Mã kho trong Odoo (stock.warehouse.code)' $cu.WarehouseCode 'KBC'

Write-Host ""
Write-Host "  Máy in Windows trên máy này:" -ForegroundColor DarkGray
try {
    Get-Printer -ErrorAction Stop | ForEach-Object { Write-Host "    - $($_.Name)" -ForegroundColor DarkGray }
} catch { Write-Host "    (không liệt kê được, gõ tay tên máy in)" -ForegroundColor DarkGray }
$mayIn    = Hoi 'Tên máy in cần theo dõi (để trống = không theo dõi máy in)' $cu.PrinterName 'Xprinter XP-80'

$macDinhLocal = if ($cu) { [bool]$cu.LocalDispatch } else { $true }
$localDispatch = HoiCo 'Bật IN TRỰC TIẾP tại máy này (không cần mở tab Điều phối)?' $macDinhLocal

$pdfExe = $cu.PdfPrintExe
if ($localDispatch) {
    $doanSumatra = Join-Path $THU_MUC 'SumatraPDF.exe'
    if (-not $pdfExe -and (Test-Path $doanSumatra)) { $pdfExe = $doanSumatra }
    $pdfExe = Hoi 'Đường dẫn SumatraPDF.exe (PowerShell không tự in PDF được)' $pdfExe $doanSumatra
    if (-not $pdfExe -or -not (Test-Path $pdfExe)) {
        Nhac "Chưa có công cụ in PDF. Vẫn cài tiếp, nhưng in trực tiếp sẽ KHÔNG đáng tin."
        Nhac "Tải SumatraPDF portable, đặt vào $doanSumatra rồi chạy lại file này."
    }
}

$thieu = @()
if (-not $odooUrl) { $thieu += 'Địa chỉ Odoo' }
if (-not $token)   { $thieu += 'Token' }
if (-not $maKho)   { $thieu += 'Mã kho' }
if ($thieu.Count)  { Dung ("Còn thiếu: " + ($thieu -join ', ')) }

# --- 4. Chạy thử + lưu cấu hình -----------------------------------------------------
$thamSo = @('-OdooUrl', $odooUrl, '-Token', $token, '-WarehouseCode', $maKho, '-SaveConfig')
if ($mayIn)        { $thamSo += @('-PrinterName', $mayIn) }
if ($localDispatch){ $thamSo += '-LocalDispatch' }
if ($pdfExe -and (Test-Path $pdfExe)) { $thamSo += @('-PdfPrintExe', $pdfExe) }

if ($SkipTest) {
    Buoc 4 "Chạy thử — BỎ QUA (-SkipTest). Vẫn phải lưu cấu hình:"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ps1 @thamSo -LoopSeconds 0 | Out-Null
} else {
    Buoc 4 "Chạy thử một lần + lưu cấu hình (gửi heartbeat thật về Odoo)"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ps1 @thamSo -LoopSeconds 0
    if ($LASTEXITCODE -ne 0) {
        Loi "Chạy thử trả về mã lỗi $LASTEXITCODE."
        Nhac "Thường gặp: sai địa chỉ Odoo, sai token, sai mã kho, hoặc máy không ra được internet."
        Nhac "Xem log: $FILE_LOG"
        Dung "Chưa tạo tác vụ — sửa xong chạy lại."
    }
    Ok "Chạy thử xong, không lỗi."
}
if (Test-Path $FILE_CONFIG) { Ok "Đã lưu cấu hình: $FILE_CONFIG" }
else { Nhac "Không thấy file cấu hình — xem log ở $FILE_LOG" }

# --- 5. Tác vụ ----------------------------------------------------------------------
Buoc 5 "Tác vụ '$TEN_TAC_VU'"

# 10 phút/lần gọi một vòng lặp 2 phút, KHÔNG phải 2 phút/lần gọi một lượt: tác vụ ở đây
# chỉ đóng vai HỒI SINH tiến trình nếu nó chết. Script có mutex chống chạy trùng nên lượt
# nào thấy vòng lặp còn sống là tự thoát ngay (log ghi "đã có 1 tiến trình... thoát ngay").
# /IT = chạy trong phiên đăng nhập, để popup cảnh báo hiện được cho người ngồi ở kho.
$lenh = "wscript.exe `"$vbs`" -LoopSeconds 120"
schtasks /Create /TN "$TEN_TAC_VU" /SC MINUTE /MO 10 /RL HIGHEST /IT /F /TR $lenh | Out-Null
if ($LASTEXITCODE -ne 0) { Dung "Không tạo được tác vụ (mã $LASTEXITCODE)." }
Ok "Đã tạo: 10 phút/lần hồi sinh, vòng lặp gửi heartbeat mỗi 2 phút, chạy ẩn."

# --- 6. Bật và soát -----------------------------------------------------------------
Buoc 6 "Bật ngay và soát lại"

schtasks /Run /TN "$TEN_TAC_VU" | Out-Null
if ($LASTEXITCODE -eq 0) { Ok "Đã bật." } else { Nhac "Chưa bật được ngay, tác vụ sẽ tự chạy ở lượt kế tiếp." }

Start-Sleep -Seconds 8
Write-Host ""
schtasks /Query /TN "$TEN_TAC_VU" /FO LIST /V |
    Select-String -Pattern 'TaskName|Status|Last Run Time|Last Result|Next Run Time|Task To Run'

Write-Host ""
Write-Host "  8 dòng cuối của log:" -ForegroundColor DarkGray
if (Test-Path $FILE_LOG) { Get-Content -LiteralPath $FILE_LOG -Tail 8 }
else { Nhac "Chưa có log — chờ vài phút rồi xem lại $FILE_LOG" }

# --- Kết ----------------------------------------------------------------------------
Write-Host ""
Write-Host "=====================================================================" -ForegroundColor White
Write-Host "  XONG" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor White
Write-Host "  Kiểm nhanh sau này : bin\check_iot_watchdog_task.cmd"
Write-Host "  Log                : $FILE_LOG"
Write-Host "  Cấu hình           : $FILE_CONFIG  (có token, chỉ admin đọc/ghi được)"
Write-Host "  Gỡ                 : schtasks /Delete /TN `"$TEN_TAC_VU`" /F"
Write-Host ""
Write-Host "  Đối chiếu bên Odoo: Kho hàng > kho $maKho > 'Watchdog: lần cuối nhận tín hiệu'"
Write-Host "  phải nhảy lên giờ hiện tại trong vòng 2 phút."
Write-Host ""
Read-Host "Nhấn Enter để đóng"
