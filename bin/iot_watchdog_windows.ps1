<#
=====================================================================================
 iot_watchdog_windows.ps1 — CHẠY TRÊN MÁY CHỦ KHO (máy Windows nối máy in, chạy service
 Odoo IoT), KHÔNG chạy trên Odoo.sh.
=====================================================================================
 Mục đích:
   1. Kiểm tra service Odoo IoT (mặc định 'odoo-server-18.0') có đang Running không.
      Nếu tắt và có -AutoRestart thì tự bật lại.
   2. (Tuỳ chọn) Kiểm tra máy in Windows còn nhận việc không (-PrinterName).
   3. Gửi tín hiệu "tôi còn sống" (heartbeat) về Odoo qua /api/iot_watchdog/heartbeat.
      => Odoo mới biết máy kho còn sống hay đã tắt/mất mạng. Nếu quá N phút không nhận
      được tín hiệu (Settings > HLV Delivery Planner), Odoo tự gửi CẢNH BÁO (email +
      toast trên dashboard) — xem stock_warehouse.cron_check_iot_watchdog().
   4. Ghi log tại chỗ để đối soát khi máy kho mất mạng (lúc đó không gửi về được Odoo).

 Vì sao cần script này: Odoo KHÔNG có cách tự biết máy kho còn sống —
 iot.device.connected có thể giữ True mãi sau khi hộp IoT chết đột ngột, còn write_date
 của device không phải heartbeat (đã đo thực tế: đứng yên 7-9.5 giờ dù máy vẫn in tốt,
 xem models/iot_print_queue.py). Chỉ chính máy đó tự báo về mới đáng tin.

-------------------------------------------------------------------------------------
 CÀI ĐẶT (làm 1 lần trên mỗi máy chủ kho, chạy PowerShell với quyền Administrator):

 1) Lấy token: Odoo > Cài đặt > HLV Delivery Planner > "Token watchdog máy chủ kho"
    (nếu trống thì tự đặt 1 chuỗi dài ngẫu nhiên rồi Lưu).

 2) Chạy thử 1 lần cho chắc (đổi URL/token/mã kho cho đúng):

    powershell -ExecutionPolicy Bypass -File C:\hlv\iot_watchdog_windows.ps1 `
      -OdooUrl "https://hoanglongvu.odoo.com" -Token "DAN_TOKEN_VAO_DAY" `
      -WarehouseCode "KBC" -PrinterName "Brother HL-L2321D" -AutoRestart -Verbose

 3) Đặt chạy tự động mỗi 2 phút (chạy dưới SYSTEM để có quyền bật lại service):

    schtasks /Create /TN "HLV IoT Watchdog" /SC MINUTE /MO 2 /RU SYSTEM /RL HIGHEST /F ^
      /TR "powershell -ExecutionPolicy Bypass -NoProfile -File C:\hlv\iot_watchdog_windows.ps1 -OdooUrl https://hoanglongvu.odoo.com -Token DAN_TOKEN_VAO_DAY -WarehouseCode KBC -AutoRestart"

 4) Kiểm tra: mở Odoo > Kho hàng > kho tương ứng, xem field "Watchdog: lần cuối nhận
    tín hiệu" có cập nhật không. Hoặc xem log: C:\ProgramData\HLV\iot_watchdog.log
-------------------------------------------------------------------------------------
 LƯU Ý KHI SỬA FILE NÀY: phải lưu ở encoding UTF-8 CÓ BOM. Windows PowerShell 5.1 đọc
 file .ps1 không BOM theo ANSI, làm chữ Việt trong comment biến thành dấu nháy thông
 minh (‘ ’) — PowerShell hiểu đó là dấu mở chuỗi và script sẽ lỗi cú pháp ngay dòng đầu.
-------------------------------------------------------------------------------------
#>

[CmdletBinding()]
param(
    # URL gốc của Odoo (production), VD https://hoanglongvu.odoo.com
    [Parameter(Mandatory = $true)][string]$OdooUrl,
    # Token giống hệt Settings > HLV Delivery Planner > Token watchdog máy chủ kho
    [Parameter(Mandatory = $true)][string]$Token,
    # MÃ KHO trong Odoo (stock.warehouse.code), VD 'KBC', 'TSN'
    [Parameter(Mandatory = $true)][string]$WarehouseCode,
    # Tên service Odoo IoT trên máy này (xem services.msc)
    [string]$ServiceName = 'odoo-server-18.0',
    # (Tuỳ chọn) tên máy in Windows cần theo dõi thêm
    [string]$PrinterName = '',
    # Có tự bật lại service khi thấy nó tắt hay không
    [switch]$AutoRestart,
    [string]$LogFile = "$env:ProgramData\HLV\iot_watchdog.log"
)

$ErrorActionPreference = 'Continue'
# Odoo.sh chỉ nhận TLS 1.2+; Windows PowerShell 5.1 mặc định có thể vẫn dùng TLS 1.0.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

function Write-WatchdogLog {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "{0} [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Write-Verbose $line
    try {
        $dir = Split-Path -Parent $LogFile
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        Add-Content -Path $LogFile -Value $line -Encoding utf8
    } catch {
        # Không ghi được log thì vẫn phải tiếp tục gửi heartbeat — log chỉ để đối soát.
    }
}

# --- 1. Kiểm tra service ------------------------------------------------------------
$serviceOk = $false
$noteParts = @("may=$env:COMPUTERNAME")

try {
    $svc = Get-Service -Name $ServiceName -ErrorAction Stop
    $serviceOk = ($svc.Status -eq 'Running')
    $noteParts += "service=$($svc.Status)"

    if (-not $serviceOk) {
        Write-WatchdogLog "Service '$ServiceName' đang $($svc.Status)." 'WARN'
        if ($AutoRestart) {
            Write-WatchdogLog "Đang thử bật lại service '$ServiceName'..." 'WARN'
            try {
                Start-Service -Name $ServiceName -ErrorAction Stop
                Start-Sleep -Seconds 10
                $svc = Get-Service -Name $ServiceName -ErrorAction Stop
                $serviceOk = ($svc.Status -eq 'Running')
                if ($serviceOk) {
                    $noteParts += 'da_tu_restart=OK'
                    Write-WatchdogLog "Đã bật lại service thành công." 'INFO'
                } else {
                    $noteParts += "da_tu_restart=THAT_BAI($($svc.Status))"
                    Write-WatchdogLog "Bật lại service KHÔNG thành công: $($svc.Status)" 'ERROR'
                }
            } catch {
                $noteParts += 'da_tu_restart=LOI'
                Write-WatchdogLog "Lỗi khi bật lại service: $($_.Exception.Message)" 'ERROR'
            }
        }
    }
} catch {
    # Không tìm thấy service = cấu hình sai tên, hoặc Odoo IoT chưa được cài như service.
    $noteParts += 'service=KHONG_TIM_THAY'
    Write-WatchdogLog "Không tìm thấy service '$ServiceName': $($_.Exception.Message)" 'ERROR'
}

# --- 2. (Tuỳ chọn) Kiểm tra máy in --------------------------------------------------
if ($PrinterName) {
    try {
        $printer = Get-Printer -Name $PrinterName -ErrorAction Stop
        $jobs = @(Get-PrintJob -PrinterName $PrinterName -ErrorAction SilentlyContinue)
        $noteParts += "may_in=$($printer.PrinterStatus)"
        $noteParts += "job_dang_cho=$($jobs.Count)"
        if ($printer.PrinterStatus -ne 'Normal') {
            Write-WatchdogLog "Máy in '$PrinterName' trạng thái $($printer.PrinterStatus), $($jobs.Count) job đang chờ." 'WARN'
        }
    } catch {
        $noteParts += 'may_in=KHONG_DOC_DUOC'
        Write-WatchdogLog "Không đọc được máy in '$PrinterName': $($_.Exception.Message)" 'WARN'
    }
}

# --- 3. Gửi heartbeat về Odoo -------------------------------------------------------
$note = ($noteParts -join '; ')
$endpoint = "$($OdooUrl.TrimEnd('/'))/api/iot_watchdog/heartbeat"
# Route Odoo type='json' cần đúng phong bì JSON-RPC 2.0, không phải JSON phẳng.
$payload = @{
    jsonrpc = '2.0'
    method  = 'call'
    params  = @{
        token          = $Token
        warehouse_code = $WarehouseCode
        service_ok     = [bool]$serviceOk
        note           = $note
    }
} | ConvertTo-Json -Depth 5 -Compress

try {
    $resp = Invoke-RestMethod -Uri $endpoint -Method Post -ContentType 'application/json; charset=utf-8' `
        -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -TimeoutSec 30 -ErrorAction Stop
    if ($resp.result -and $resp.result.success) {
        Write-WatchdogLog "Đã gửi heartbeat cho kho $($resp.result.warehouse_name) (service_ok=$serviceOk; $note)."
    } else {
        $msg = 'khong ro'
        if ($resp.result -and $resp.result.message) { $msg = $resp.result.message }
        elseif ($resp.error) { $msg = $resp.error.data.message }
        Write-WatchdogLog "Odoo TỪ CHỐI heartbeat: $msg" 'ERROR'
        exit 2
    }
} catch {
    # Không gửi được = mất mạng/Odoo down. Không sao: Odoo sẽ tự thấy "im lặng quá N phút"
    # và gửi cảnh báo cho người dùng.
    Write-WatchdogLog "Không gửi được heartbeat tới $endpoint : $($_.Exception.Message)" 'ERROR'
    exit 3
}

if (-not $serviceOk) { exit 1 }
exit 0
