<#
=====================================================================================
 iot_watchdog_windows.ps1 — CHẠY TRÊN MÁY CHỦ KHO (máy Windows nối máy in, chạy service
 Odoo IoT), KHÔNG chạy trên Odoo.sh.
=====================================================================================
 Mỗi vòng kiểm tra, script làm 4 việc:
   1. Kiểm tra service Odoo IoT (mặc định 'odoo-server-18.0') có đang Running không.
      Nếu tắt và có -AutoRestart thì TỰ BẬT LẠI.
   2. Nếu service vẫn tắt / không gửi được tín hiệu về Odoo => CẢNH BÁO NGAY TRÊN MÁY NÀY:
        - hộp thoại popup đỏ (tự tắt sau 60 giây, không chặn vòng lặp)
        - dòng chữ đỏ + tiếng bíp trong cửa sổ script (nếu đang chạy liên tục)
        - tin nhắn màn hình qua msg.exe (tới được cả khi script chạy dưới quyền SYSTEM)
        - ghi Windows Event Log (Application, source 'HLV IoT Watchdog') để đối soát sau
   3. (Tuỳ chọn) Kiểm tra máy in Windows còn nhận việc không (-PrinterName).
   4. Gửi tín hiệu "tôi còn sống" (heartbeat) về Odoo qua /api/iot_watchdog/heartbeat, để
      Odoo cảnh báo tiếp cho sale/kho bằng email + toast trên dashboard (xem
      stock_warehouse.cron_check_iot_watchdog).

 Vì sao cần script này: Odoo KHÔNG có cách tự biết máy kho còn sống —
 iot.device.connected có thể giữ True mãi sau khi hộp IoT chết đột ngột, còn write_date
 của device không phải heartbeat (đã đo thực tế: đứng yên 7-9.5 giờ dù máy vẫn in tốt,
 xem models/iot_print_queue.py). Chỉ chính máy đó tự báo về mới đáng tin.

-------------------------------------------------------------------------------------
 BƯỚC 1 — LƯU CẤU HÌNH 1 LẦN (sau đó KHÔNG phải nhập lại gì nữa)
-------------------------------------------------------------------------------------
 Lấy token ở: Odoo > Cài đặt > HLV Delivery Planner > "Token watchdog máy chủ kho"
 (nếu trống thì tự đặt 1 chuỗi dài ngẫu nhiên rồi Lưu). Rồi chạy 1 lần:

   .\iot_watchdog_windows.ps1 -OdooUrl "https://hoanglongvu.odoo.com" `
     -Token "DAN_TOKEN_VAO_DAY" -WarehouseCode "TSN" `
     -PrinterName "Brother HL-L2321D" -AutoOpenDispatcher -SaveConfig

 -AutoOpenDispatcher: khi Odoo báo "có yêu cầu in nằm chờ mà chưa ai đẩy xuống máy in"
 (= không tab "Điều phối Giao hàng" nào đang mở) thì script TỰ MỞ trang đó bằng trình
 duyệt của máy này, tối đa 1 lần / 10 phút. CHỈ bật trên MÁY Ở KHO — máy khác mở lên
 cũng không in được vì lệnh in phải đi từ trình duyệt tới hộp IoT trong LAN của kho.

 Cấu hình lưu tại C:\ProgramData\HLV\iot_watchdog.config.json (chứa token dạng chữ
 thường — để trong ProgramData nên chỉ admin ghi được). Từ lần sau chỉ cần:

   .\iot_watchdog_windows.ps1

 Muốn đổi 1 thông số: truyền lại trên dòng lệnh (dòng lệnh luôn thắng file cấu hình),
 thêm -SaveConfig nếu muốn ghi đè luôn vào file.

-------------------------------------------------------------------------------------
 IN TRỰC TIẾP TẠI MÁY KHO (-LocalDispatch) — khuyến nghị bật ở kho
-------------------------------------------------------------------------------------
 Có 2 ĐƯỜNG IN, chạy song song được, không sợ in trùng (cùng dùng 1 cơ chế claim
 nguyên tử trong Odoo nên mỗi phiếu chỉ 1 bên lấy được):

   1) Qua trình duyệt + hộp IoT (đường cũ): phải có tab "Điều phối Giao hàng" đang mở
      trên máy nối máy in. Đóng tab là hàng chờ nằm im vô thời hạn.
   2) Máy kho tự in (đường này): script hỏi Odoo "có phiếu nào cần in không", nhận PDF
      rồi in thẳng bằng driver máy in Windows. KHÔNG cần tab nào mở, không cần hộp IoT.

 PowerShell không tự in được PDF nên cần 1 công cụ nhỏ. Khuyến nghị SumatraPDF, tải ở
 https://www.sumatrapdfreader.org/download-free-pdf-viewer

 ⚠️ BẪY ĐÃ GẶP THẬT: file tải về là bản INSTALLER, và cùng 1 binary đó chỉ chạy như
 trình in khi có libmupdf.dll NẰM CẠNH. Nếu chỉ copy 1 mình .exe thì nó mở chế độ
 installer rồi thoát với ExitCode=0 — KHÔNG in gì, KHÔNG báo lỗi gì. Giải nén cho đúng:

   C:\hlv\SumatraPDF.exe -x -d "C:\hlv\sumatra"

 sẽ tạo C:\hlv\sumatra\{SumatraPDF.exe, libmupdf.dll, ...}. Trỏ vào file TRONG đó:

   .\iot_watchdog_windows.ps1 -LocalDispatch -PdfPrintExe "C:\hlv\sumatra\SumatraPDF.exe" `
     -PrinterName "Xprinter XP-80" -SaveConfig

 Script tự kiểm tra thiếu libmupdf.dll và báo đúng cách sửa. Cũng nhận PDFtoPrinter.exe.

 Không có công cụ nào thì script vẫn thử verb 'printto'/'print' của Windows, nhưng
 kém tin cậy (phụ thuộc trình đọc PDF đã cài) — thất bại sẽ báo rõ lý do vào Odoo,
 phiếu chuyển sang "Lỗi" để kho thấy, KHÔNG im lặng bỏ qua.

-------------------------------------------------------------------------------------
 BƯỚC 2 — CHỌN CÁCH CHẠY (2 chế độ)
-------------------------------------------------------------------------------------
 A) LIÊN TỤC (dễ nhìn, có người ngồi máy) — cửa sổ mở hoài, tự lặp mỗi 120 giây:

      .\iot_watchdog_windows.ps1 -LoopSeconds 120

    Nhược điểm: đóng cửa sổ / khởi động lại máy là DỪNG giám sát. (Không mất trắng: Odoo
    sẽ thấy "im lặng quá N phút" và tự gửi email cảnh báo.)

 B) CHẠY ẨN 24/7 (khuyến nghị chạy thật) — KHÔNG hiện cửa sổ nào, kể cả nháy 1 giây:

    schtasks /Create /TN "HLV IoT Watchdog" /SC MINUTE /MO 10 /RL HIGHEST /IT /F ^
      /TR "wscript.exe C:\hlv\run_watchdog_hidden.vbs -LoopSeconds 120"

    Cách này chạy 1 tiến trình ẩn duy nhất, tự kiểm tra mỗi 120 giây. Task 10 phút/lần
    chỉ để HỒI SINH nếu tiến trình đó chết (mutex trong script chặn chạy trùng nên không
    bao giờ có 2 tiến trình cùng lúc). run_watchdog_hidden.vbs phải nằm cùng thư mục.

    Vì sao không gọi thẳng powershell.exe trong task: mỗi lần chạy sẽ nháy 1 cửa sổ
    console lên màn hình máy kho (2 phút 1 lần) — không làm việc gì khác được.

    Lưu ý về popup: /IT = chạy dưới user đang đăng nhập nên popup cảnh báo hiện được.
    Nếu tạo task chạy dưới SYSTEM (/RU SYSTEM) thì popup KHÔNG hiện lên được (Windows
    chặn giao diện của session 0) — lúc đó chỉ còn msg.exe + Event Log. Đổi lại, chạy
    dưới user thường có thể KHÔNG đủ quyền bật lại service; máy kho thường đăng nhập sẵn
    bằng tài khoản admin nên /IT + /RL HIGHEST là đủ cả hai.

-------------------------------------------------------------------------------------
 BƯỚC 3 — KIỂM TRA
-------------------------------------------------------------------------------------
 - Phía Odoo: Kho hàng > kho tương ứng > field "Watchdog: lần cuối nhận tín hiệu" có
   cập nhật không. Hoặc chạy: bin/check_iot_watchdog_status.py
 - Phía máy kho: log tại C:\ProgramData\HLV\iot_watchdog.log

 GHI CHÚ:
 - Script TỰ BẬT LẠI service khi thấy service tắt (mặc định). Không muốn thì thêm
   -NoAutoRestart.
 - Đang lỗi liên tục thì popup chỉ hiện lại mỗi 15 phút (chống spam). Muốn hiện mỗi lần
   phát hiện: thêm -AlertRepeatMinutes 0. Khi bị chặn do chống spam, script vẫn ghi 1
   dòng WARN giải thích trong log/cửa sổ.
-------------------------------------------------------------------------------------
 LƯU Ý KHI SỬA FILE NÀY: phải lưu ở encoding UTF-8 CÓ BOM. Windows PowerShell 5.1 đọc
 file .ps1 không BOM theo ANSI, làm chữ Việt trong comment biến thành dấu nháy thông
 minh (‘ ’) — PowerShell hiểu đó là dấu mở chuỗi và script sẽ lỗi cú pháp ngay dòng đầu.
-------------------------------------------------------------------------------------
#>

[CmdletBinding()]
param(
    # 3 thông tin dưới đây KHÔNG bắt buộc trên dòng lệnh — nếu đã lưu vào file cấu hình
    # (chạy 1 lần với -SaveConfig) thì lần sau chỉ cần chạy script không cần tham số gì.
    # URL gốc của Odoo, VD https://hoanglongvu.odoo.com
    [string]$OdooUrl,
    # Token giống hệt Settings > HLV Delivery Planner > Token watchdog máy chủ kho
    [string]$Token,
    # MÃ KHO trong Odoo (stock.warehouse.code), VD 'KBC', 'TSN'
    [string]$WarehouseCode,
    # Tên service Odoo IoT trên máy này (xem services.msc)
    [string]$ServiceName = 'odoo-server-18.0',
    # (Tuỳ chọn) tên máy in Windows cần theo dõi thêm
    [string]$PrinterName = '',
    # Service hàng đợi in của Windows. Spooler chết/treo => Odoo báo "đã gửi lệnh in" nhưng
    # KHÔNG có job nào vào máy in. Watchdog cũng bật lại service này khi thấy tắt.
    [string]$SpoolerServiceName = 'Spooler',
    # Job nằm trong hàng đợi quá số phút này (hoặc đang ở trạng thái lỗi) thì coi là TREO.
    # Phiếu lấy hàng A5 in vài giây là xong, nên treo 5 phút gần như chắc chắn là nghẽn.
    [int]$StuckJobMinutes = 5,
    # Mặc định TỰ XOÁ job treo (đúng việc thủ kho đang phải làm tay: xoá queue thì in lại
    # bình thường). Thêm cờ này nếu muốn chỉ cảnh báo, không tự xoá.
    [switch]$NoAutoClearStuckJobs,
    # MẶC ĐỊNH LÀ CÓ tự bật lại service khi thấy nó tắt. Chỉ thêm cờ này nếu KHÔNG muốn
    # script tự động can thiệp (VD task chạy dưới user thường, không đủ quyền bật service).
    [switch]$NoAutoRestart,
    # 0 (mặc định) = chạy 1 LẦN rồi thoát, dùng cho Task Scheduler.
    # > 0 = chạy LIÊN TỤC, lặp lại mỗi N giây (Ctrl+C hoặc đóng cửa sổ để dừng).
    [int]$LoopSeconds = 0,
    # Đang lỗi thì nhắc lại cảnh báo trên máy tối đa mỗi N phút (tránh popup liên tục).
    # Đặt 0 = mỗi lần phát hiện lỗi đều cảnh báo lại ngay (dùng khi test).
    [int]$AlertRepeatMinutes = 15,
    # Tắt popup/msg trên máy (chỉ ghi log + Event Log) — dùng cho máy không có ai ngồi.
    [switch]$NoLocalPopup,
    # BẬT ĐƯỜNG IN TRỰC TIẾP: máy này tự hỏi Odoo lấy phiếu cần in rồi in thẳng ra máy in
    # Windows, KHÔNG cần tab "Điều phối Giao hàng" nào mở. Chỉ bật trên MÁY Ở KHO (máy nối máy in).
    [switch]$LocalDispatch,
    # Công cụ in PDF (PowerShell không tự in được PDF). Khuyến nghị SumatraPDF portable:
    # -PdfPrintExe "C:\hlv\SumatraPDF.exe". Cũng nhận PDFtoPrinter.exe. Để trống thì thử verb
    # 'printto'/'print' của Windows — kém tin cậy, chỉ là phương án chữa cháy.
    [string]$PdfPrintExe = '',
    # Tuỳ chọn in truyền thẳng cho SumatraPDF (-print-settings). Cần cho MÁY IN NHIỆT khổ hẹp
    # (Xprinter 80mm): mặc định Sumatra co giãn theo khổ giấy của driver, dễ làm phiếu bị thu nhỏ
    # hoặc cắt mất. Giá trị hay dùng: 'noscale' (in nguyên khổ), 'fit' (vừa khung), 'shrink'.
    [string]$PdfPrintSettings = '',
    # Mỗi lượt nhận tối đa bao nhiêu phiếu (tránh 1 lượt in cả trăm tờ nếu hàng chờ dồn).
    [int]$DispatchBatch = 5,
    # Khi Odoo báo "có yêu cầu in nằm chờ mà chưa ai đẩy xuống máy in" (= không tab "Điều phối
    # Giao hàng" nào đang mở), TỰ MỞ trang đó trong trình duyệt mặc định của máy này. Chỉ nên bật
    # trên MÁY Ở KHO (máy nối được máy in), vì mở ở máy khác thì cũng không in được.
    [switch]$AutoOpenDispatcher,
    # Đã tự mở trang điều phối thì chờ ít nhất bao nhiêu phút mới mở lại (tránh mở hàng loạt tab).
    [int]$AutoOpenRepeatMinutes = 10,
    # Lưu các thông số đang truyền vào file cấu hình rồi vẫn chạy tiếp như bình thường.
    [switch]$SaveConfig,
    # File cấu hình: chứa OdooUrl/Token/WarehouseCode/... để không phải nhập lại mỗi lần.
    [string]$ConfigFile = "$env:ProgramData\HLV\iot_watchdog.config.json",
    [string]$LogFile = "$env:ProgramData\HLV\iot_watchdog.log",
    # Nhớ trạng thái giữa các lần chạy để không spam cảnh báo mỗi 2 phút ở chế độ Task Scheduler.
    [string]$StateFile = "$env:ProgramData\HLV\iot_watchdog_state.json"
)

$ErrorActionPreference = 'Continue'
# Odoo.sh chỉ nhận TLS 1.2+; Windows PowerShell 5.1 mặc định có thể vẫn dùng TLS 1.0.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$script:EventSource = 'HLV IoT Watchdog'

function Write-WatchdogLog {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "{0} [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    if ($Level -eq 'ERROR') { Write-Host $line -ForegroundColor Red }
    elseif ($Level -eq 'WARN') { Write-Host $line -ForegroundColor Yellow }
    else { Write-Host $line -ForegroundColor Gray }
    try {
        $dir = Split-Path -Parent $LogFile
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        Add-Content -Path $LogFile -Value $line -Encoding utf8
    } catch {
        # Không ghi được log thì vẫn phải tiếp tục gửi heartbeat — log chỉ để đối soát.
    }
}

# --- Nạp cấu hình đã lưu (để không phải nhập lại mỗi lần chạy) ----------------------
# Thứ tự ưu tiên: tham số truyền trên dòng lệnh > file cấu hình > mặc định trong param().
$boundParams = $PSBoundParameters
$cfg = $null
if (Test-Path $ConfigFile) {
    try {
        $cfg = (Get-Content -Path $ConfigFile -Raw -Encoding UTF8) | ConvertFrom-Json
    } catch {
        Write-WatchdogLog "Không đọc được file cấu hình '$ConfigFile': $($_.Exception.Message)" 'WARN'
    }
}
if ($cfg) {
    if (-not $boundParams.ContainsKey('OdooUrl') -and $cfg.OdooUrl) { $OdooUrl = [string]$cfg.OdooUrl }
    if (-not $boundParams.ContainsKey('Token') -and $cfg.Token) { $Token = [string]$cfg.Token }
    if (-not $boundParams.ContainsKey('WarehouseCode') -and $cfg.WarehouseCode) { $WarehouseCode = [string]$cfg.WarehouseCode }
    if (-not $boundParams.ContainsKey('ServiceName') -and $cfg.ServiceName) { $ServiceName = [string]$cfg.ServiceName }
    if (-not $boundParams.ContainsKey('PrinterName') -and $cfg.PrinterName) { $PrinterName = [string]$cfg.PrinterName }
    if (-not $boundParams.ContainsKey('SpoolerServiceName') -and $cfg.SpoolerServiceName) { $SpoolerServiceName = [string]$cfg.SpoolerServiceName }
    if (-not $boundParams.ContainsKey('StuckJobMinutes') -and $null -ne $cfg.StuckJobMinutes) { $StuckJobMinutes = [int]$cfg.StuckJobMinutes }
    if (-not $boundParams.ContainsKey('NoAutoClearStuckJobs') -and $cfg.NoAutoClearStuckJobs -eq $true) { $NoAutoClearStuckJobs = [switch]$true }
    if (-not $boundParams.ContainsKey('LoopSeconds') -and $null -ne $cfg.LoopSeconds) { $LoopSeconds = [int]$cfg.LoopSeconds }
    if (-not $boundParams.ContainsKey('AlertRepeatMinutes') -and $null -ne $cfg.AlertRepeatMinutes) { $AlertRepeatMinutes = [int]$cfg.AlertRepeatMinutes }
    if (-not $boundParams.ContainsKey('NoAutoRestart') -and $cfg.NoAutoRestart -eq $true) { $NoAutoRestart = [switch]$true }
    if (-not $boundParams.ContainsKey('NoLocalPopup') -and $cfg.NoLocalPopup -eq $true) { $NoLocalPopup = [switch]$true }
    if (-not $boundParams.ContainsKey('LocalDispatch') -and $cfg.LocalDispatch -eq $true) { $LocalDispatch = [switch]$true }
    if (-not $boundParams.ContainsKey('PdfPrintExe') -and $cfg.PdfPrintExe) { $PdfPrintExe = [string]$cfg.PdfPrintExe }
    if (-not $boundParams.ContainsKey('PdfPrintSettings') -and $cfg.PdfPrintSettings) { $PdfPrintSettings = [string]$cfg.PdfPrintSettings }
    if (-not $boundParams.ContainsKey('DispatchBatch') -and $null -ne $cfg.DispatchBatch) { $DispatchBatch = [int]$cfg.DispatchBatch }
    if (-not $boundParams.ContainsKey('AutoOpenDispatcher') -and $cfg.AutoOpenDispatcher -eq $true) { $AutoOpenDispatcher = [switch]$true }
    if (-not $boundParams.ContainsKey('AutoOpenRepeatMinutes') -and $null -ne $cfg.AutoOpenRepeatMinutes) { $AutoOpenRepeatMinutes = [int]$cfg.AutoOpenRepeatMinutes }
}

if ($SaveConfig) {
    try {
        $dir = Split-Path -Parent $ConfigFile
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        ([ordered]@{
            OdooUrl            = $OdooUrl
            Token              = $Token
            WarehouseCode      = $WarehouseCode
            ServiceName        = $ServiceName
            PrinterName        = $PrinterName
            SpoolerServiceName = $SpoolerServiceName
            StuckJobMinutes    = $StuckJobMinutes
            NoAutoClearStuckJobs = [bool]$NoAutoClearStuckJobs
            LoopSeconds        = $LoopSeconds
            AlertRepeatMinutes = $AlertRepeatMinutes
            NoAutoRestart      = [bool]$NoAutoRestart
            NoLocalPopup       = [bool]$NoLocalPopup
            LocalDispatch      = [bool]$LocalDispatch
            PdfPrintExe        = $PdfPrintExe
            PdfPrintSettings   = $PdfPrintSettings
            DispatchBatch      = $DispatchBatch
            AutoOpenDispatcher = [bool]$AutoOpenDispatcher
            AutoOpenRepeatMinutes = $AutoOpenRepeatMinutes
        } | ConvertTo-Json) | Set-Content -Path $ConfigFile -Encoding utf8
        Write-WatchdogLog "Đã lưu cấu hình vào '$ConfigFile' — lần sau chạy script KHÔNG cần nhập lại gì." 'INFO'
        Write-WatchdogLog "LƯU Ý: file này chứa token dạng chữ thường, nên để trong ProgramData (chỉ admin ghi được)." 'WARN'
    } catch {
        Write-WatchdogLog "Không lưu được cấu hình: $($_.Exception.Message)" 'ERROR'
    }
}

# Thiếu thông tin bắt buộc thì báo rõ cách khắc phục, KHÔNG hỏi từng dòng như trước
# (trước đây 3 tham số này Mandatory nên PowerShell hỏi tay mỗi lần chạy — rất bất tiện).
$missing = @()
if (-not $OdooUrl) { $missing += 'OdooUrl' }
if (-not $Token) { $missing += 'Token' }
if (-not $WarehouseCode) { $missing += 'WarehouseCode' }
if ($missing.Count -gt 0) {
    Write-Host ''
    Write-Host "  THIẾU THÔNG TIN: $($missing -join ', ')" -ForegroundColor Red
    Write-Host "  Chưa có file cấu hình '$ConfigFile'." -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  Chạy 1 lần như dưới đây để LƯU cấu hình (lần sau chỉ cần chạy script, không tham số):' -ForegroundColor Cyan
    Write-Host '    .\iot_watchdog_windows.ps1 -OdooUrl "https://<odoo>.odoo.com" -Token "<token>" -WarehouseCode "TSN" -SaveConfig' -ForegroundColor White
    Write-Host ''
    exit 4
}

function Write-WatchdogEventLog {
    param([string]$Message, [string]$EntryType = 'Error')
    try {
        if (-not [System.Diagnostics.EventLog]::SourceExists($script:EventSource)) {
            # Cần quyền Administrator; nếu không có thì bỏ qua, các kênh khác vẫn chạy.
            New-EventLog -LogName Application -Source $script:EventSource -ErrorAction Stop
        }
        Write-EventLog -LogName Application -Source $script:EventSource -EntryType $EntryType `
            -EventId 1000 -Message $Message -ErrorAction Stop
    } catch {
        Write-Verbose "Không ghi được Event Log: $($_.Exception.Message)"
    }
}

function Show-LocalAlert {
    <# Cảnh báo NGAY TRÊN MÁY NÀY. Bắn qua nhiều kênh vì mỗi kênh có điểm chết riêng:
       - popup: chỉ hiện khi script chạy trong session của người đang đăng nhập
       - msg.exe: tới được mọi session (kể cả khi script chạy dưới SYSTEM), nhưng bản
         Windows Home có thể không có msg.exe
       - console: chỉ thấy nếu đang chạy chế độ -LoopSeconds với cửa sổ mở
       - Event Log: luôn ghi được (nếu đủ quyền), để đối soát về sau #>
    param([string]$Title, [string]$Message)

    Write-Host ''
    Write-Host '  ============================================================' -ForegroundColor Red
    Write-Host "   $Title" -ForegroundColor Red
    Write-Host "   $Message" -ForegroundColor Red
    Write-Host '  ============================================================' -ForegroundColor Red
    Write-Host ''
    try { for ($i = 0; $i -lt 3; $i++) { [console]::Beep(880, 350) } } catch {}

    Write-WatchdogEventLog -Message "$Title`r`n$Message" -EntryType 'Error'

    if ($NoLocalPopup) { return }

    # Popup KHÔNG CHẶN vòng lặp: chạy ở process riêng, tự tắt sau 60 giây.
    try {
        $safeMsg = $Message -replace "'", "''"
        $safeTitle = $Title -replace "'", "''"
        $inner = "`$w = New-Object -ComObject WScript.Shell; `$w.Popup('$safeMsg', 60, '$safeTitle', 16) | Out-Null"
        Start-Process -FilePath 'powershell.exe' `
            -ArgumentList '-NoProfile', '-WindowStyle', 'Hidden', '-Command', $inner `
            -WindowStyle Hidden | Out-Null
    } catch {
        Write-WatchdogLog "Không hiện được popup: $($_.Exception.Message)" 'WARN'
    }

    # msg.exe: gửi tin nhắn tới mọi session đang đăng nhập trên máy.
    try {
        if (Get-Command msg.exe -ErrorAction SilentlyContinue) {
            & msg.exe * /TIME:60 "$Title - $Message" 2>$null
        }
    } catch {
        Write-Verbose "msg.exe không dùng được: $($_.Exception.Message)"
    }
}

function Get-WatchdogState {
    if (-not (Test-Path $StateFile)) { return @{ bad = $false; lastAlertUtc = $null } }
    try {
        $raw = Get-Content -Path $StateFile -Raw -Encoding UTF8
        $obj = $raw | ConvertFrom-Json
        $last = $null
        # .ToUniversalTime() là BẮT BUỘC: [datetime]::Parse() với chuỗi có 'Z' trả về DateTime
        # Kind=Local, đem trừ với giờ UTC sẽ lệch đúng bằng múi giờ máy (VN = 7 tiếng) — làm
        # chống-spam khoá cảnh báo tới 7 giờ thay vì $AlertRepeatMinutes phút (đã gặp khi test).
        if ($obj.lastAlertUtc) { $last = ([datetime]::Parse($obj.lastAlertUtc)).ToUniversalTime() }
        return @{ bad = [bool]$obj.bad; lastAlertUtc = $last }
    } catch {
        return @{ bad = $false; lastAlertUtc = $null }
    }
}

function Set-WatchdogState {
    param([bool]$Bad, $LastAlertUtc)
    try {
        $dir = Split-Path -Parent $StateFile
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        $payload = @{ bad = $Bad; lastAlertUtc = $null }
        if ($LastAlertUtc) { $payload.lastAlertUtc = ([datetime]$LastAlertUtc).ToString('o') }
        ($payload | ConvertTo-Json -Compress) | Set-Content -Path $StateFile -Encoding utf8
    } catch {
        Write-WatchdogLog "Không ghi được state file: $($_.Exception.Message)" 'WARN'
    }
}

function Invoke-OdooJson {
    <#
      Gọi 1 route Odoo type='json' — bắt buộc bọc phong bì JSON-RPC 2.0 (JSON phẳng bị từ chối).
      Trả về $resp.result, hoặc $null nếu lỗi (đã ghi log). KHÔNG throw để 1 route lỗi không làm
      chết cả vòng kiểm tra.
    #>
    param([string]$Path, [hashtable]$Params, [int]$TimeoutSec = 120)

    $endpoint = "$($OdooUrl.TrimEnd('/'))$Path"
    $payload = @{ jsonrpc = '2.0'; method = 'call'; params = $Params } | ConvertTo-Json -Depth 6 -Compress
    try {
        $resp = Invoke-RestMethod -Uri $endpoint -Method Post -ContentType 'application/json; charset=utf-8' `
            -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -TimeoutSec $TimeoutSec -ErrorAction Stop
        if ($resp -is [string]) {
            # Không parse được thành JSON: gần như luôn là proxy/tường lửa trả trang HTML, hoặc
            # URL sai (trang login Odoo). Không được im lặng bỏ qua — nói rõ để người cài sửa URL.
            $head = $resp.Substring(0, [Math]::Min(200, $resp.Length)) -replace '\s+', ' '
            Write-WatchdogLog "Odoo tra ve du lieu KHONG phai JSON tai ${Path}: $head" 'ERROR'
            return $null
        }
        if ($resp.error) {
            Write-WatchdogLog "Odoo tra ve loi tai ${Path}: $($resp.error.data.message)" 'ERROR'
            return $null
        }
        if ($null -eq $resp.result) {
            Write-WatchdogLog "Odoo tra ve phan hoi thieu 'result' tai ${Path}." 'ERROR'
            return $null
        }
        return $resp.result
    } catch {
        Write-WatchdogLog "Khong goi duoc ${endpoint}: $($_.Exception.Message)" 'ERROR'
        return $null
    }
}

function Get-PrinterPrintedTotal {
    <#
      TỔNG số job máy in này đã in xong kể từ lúc Spooler chạy (performance counter Windows).
      $null nếu không đọc được (counter không có trên mọi bản Windows / tên máy in không khớp).
    #>
    param([string]$Printer)
    try {
        $samples = (Get-Counter '\Print Queue(*)\Total Jobs Printed' -ErrorAction Stop).CounterSamples
        $mine = @($samples | Where-Object { $_.InstanceName -eq $Printer.ToLower() })
        if ($mine.Count -gt 0) { return [int]$mine[0].CookedValue }
    } catch { }
    return $null
}

function Test-PrintAccepted {
    <#
      KIỂM CHỨNG là Windows THẬT SỰ nhận lệnh in, không tin suông ExitCode của công cụ in.
      Lý do có hàm này: SumatraPDF khi không tìm thấy máy in (VD tên bị cắt vì có dấu cách) sẽ
      THOÁT LẶNG LẼ với ExitCode=0 — script báo "đã in" mà giấy không ra, đúng kiểu lỗi im lặng.

      Chấp nhận 1 trong 2 bằng chứng:
        - có job nằm trong hàng đợi của máy in đó (Windows đã nhận; máy hết giấy/offline thì job
          nằm chờ — đó là lỗi khác, tầng đối chiếu với Odoo sẽ bắt).
        - số job đã in TĂNG so với trước khi in (in xong luôn, job đã rời hàng đợi).

      Nếu KHÔNG quan sát được gì (không đọc được counter lẫn hàng đợi) thì trả về ok=$true kèm
      ghi chú "khong xac minh duoc" — thà tin công cụ in còn hơn báo lỗi oan rồi in trùng.
    #>
    param([string]$Printer, $BeforeTotal, [int]$TimeoutSec = 20)

    $queueReadable = $false
    try { $null = @(Get-PrintJob -PrinterName $Printer -ErrorAction Stop); $queueReadable = $true } catch { }
    if (-not $queueReadable -and $null -eq $BeforeTotal) {
        return @{ ok = $true; how = 'khong xac minh duoc (khong doc duoc hang doi lan counter)' }
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ($true) {
        if ($queueReadable) {
            try {
                $jobs = @(Get-PrintJob -PrinterName $Printer -ErrorAction Stop)
                if ($jobs.Count -gt 0) {
                    return @{ ok = $true; how = "Windows da nhan ($($jobs.Count) job trong hang doi)" }
                }
            } catch { }
        }
        if ($null -ne $BeforeTotal) {
            $nowTotal = Get-PrinterPrintedTotal -Printer $Printer
            if ($null -ne $nowTotal -and $nowTotal -gt $BeforeTotal) {
                return @{ ok = $true; how = "da in xong (so job da in: $BeforeTotal -> $nowTotal)" }
            }
        }
        if ((Get-Date) -ge $deadline) { break }
        Start-Sleep -Milliseconds 1500
    }
    return @{ ok = $false; how = '' }
}

function Out-PdfToPrinter {
    <#
      In 1 file PDF ra máy in Windows. PowerShell KHÔNG tự in được PDF (không có bộ dựng hình
      PDF), nên thứ tự thử:
        1. -PdfPrintExe: SumatraPDF.exe (-print-to "<may in>" -silent) hoặc PDFtoPrinter.exe
           ("<file>" "<may in>"). Đây là cách DUY NHẤT chắc chắn im lặng và đúng máy in.
        2. Shell verb 'printto' (cần trình đọc PDF có đăng ký verb này, VD Adobe Reader/Foxit).
        3. Shell verb 'print' (in ra MÁY IN MẶC ĐỊNH — chỉ dùng khi không chỉ định được máy in).
      Trả về hashtable @{ ok = $true/$false; message = '...' } — thất bại phải báo được lý do
      về Odoo, không im lặng.
    #>
    param([string]$PdfPath, [string]$Printer)

    if ($PdfPrintExe) {
        if (-not (Test-Path $PdfPrintExe)) {
            return @{ ok = $false; message = "Khong tim thay cong cu in PDF: $PdfPrintExe" }
        }
        $exeName = (Split-Path -Leaf $PdfPrintExe).ToLower()
        # BẪY ĐÃ GẶP THẬT: file tải từ trang Sumatra là bản INSTALLER, và cùng 1 binary đó chỉ
        # chạy như trình xem/in khi có libmupdf.dll NẰM CẠNH nó. Thiếu DLL => nó mở chế độ
        # installer rồi thoát với ExitCode=0, không in gì, không báo lỗi gì. Bắt sớm ở đây thay
        # vì chờ 20 giây rồi đoán mò là "sai tên máy in".
        if ($exeName -like 'sumatra*') {
            $exeDir = Split-Path -Parent $PdfPrintExe
            if (-not (Test-Path (Join-Path $exeDir 'libmupdf.dll'))) {
                return @{ ok = $false; message = (
                    "Thieu libmupdf.dll canh $PdfPrintExe => file nay dang chay o CHE DO INSTALLER " +
                    '(thoat ngay, khong in gi). Cach sua: chay installer voi tham so -x -d ' +
                    '"C:\hlv\sumatra" de giai nen, roi tro -PdfPrintExe vao ' +
                    'C:\hlv\sumatra\SumatraPDF.exe (co libmupdf.dll ben canh).'
                ) }
            }
        }
        try {
            # PHẢI tự bọc dấu ngoặc: PowerShell 5.1 KHÔNG thêm ngoặc cho từng phần tử của mảng
            # -ArgumentList, nên tên máy in có dấu cách ("Brother DCP-B7620DW Printer") bị cắt
            # thành nhiều tham số. SumatraPDF khi đó không tìm thấy máy in và với -silent thì
            # THOÁT LẶNG LẼ với ExitCode=0 => script báo "đã in" mà giấy không ra. Đã gặp thật.
            $q = [char]34
            if ($exeName -like 'sumatra*') {
                $extra = ''
                if ($PdfPrintSettings) { $extra = " -print-settings $q$PdfPrintSettings$q" }
                $exeArgs = "-print-to $q$Printer$q$extra -silent -exit-when-done $q$PdfPath$q"
            } elseif ($exeName -like 'pdftoprinter*') {
                $exeArgs = "$q$PdfPath$q $q$Printer$q"
            } else {
                # Công cụ lạ: đưa theo thứ tự phổ biến nhất (file trước, máy in sau).
                $exeArgs = "$q$PdfPath$q $q$Printer$q"
            }
            Write-WatchdogLog "Goi cong cu in: $q$PdfPrintExe$q $exeArgs"
            $before = Get-PrinterPrintedTotal -Printer $Printer
            $proc = Start-Process -FilePath $PdfPrintExe -ArgumentList $exeArgs -PassThru -Wait `
                -WindowStyle Hidden -ErrorAction Stop
            if ($proc.ExitCode -ne 0) {
                return @{ ok = $false; message = "$exeName tra ve ExitCode=$($proc.ExitCode)" }
            }
            # KHÔNG tin suông ExitCode=0 — xem Windows có thật sự nhận job không.
            $accepted = Test-PrintAccepted -Printer $Printer -BeforeTotal $before
            if ($accepted.ok) {
                return @{ ok = $true; message = "$exeName -> $Printer ($($accepted.how))" }
            }
            return @{ ok = $false; message = (
                "$exeName bao thanh cong (ExitCode=0) nhung may in '$Printer' KHONG nhan them job nao. " +
                '3 nguyen nhan hay gap: (1) sai ten may in - kiem tra "Get-Printer | Select Name"; ' +
                '(2) cong cu in thieu DLL nen chay o che do installer/thoat ngay; ' +
                '(3) file PDF hong hoac rong. File PDF cua lan in nay duoc GIU LAI de kiem tra.'
            ) }
        } catch {
            return @{ ok = $false; message = "Loi khi goi $exeName : $($_.Exception.Message)" }
        }
    }

    # Không có công cụ in PDF: thử verb của shell. Kém tin cậy (phụ thuộc trình đọc PDF đã cài)
    # nên chỉ là phương án chữa cháy, và phải nói rõ trong log để người cài biết mà bổ sung.
    try {
        Start-Process -FilePath $PdfPath -Verb PrintTo -ArgumentList $Printer -ErrorAction Stop
        return @{ ok = $true; message = "shell verb printto -> $Printer (nen cai SumatraPDF de chac chan)" }
    } catch {
        try {
            Start-Process -FilePath $PdfPath -Verb Print -ErrorAction Stop
            return @{ ok = $true; message = 'shell verb print -> MAY IN MAC DINH (khong chi dinh duoc may in)' }
        } catch {
            return @{ ok = $false; message = (
                'Khong in duoc PDF: may nay khong co cong cu in PDF. Tai SumatraPDF portable roi ' +
                'chay lai script voi -PdfPrintExe "C:\hlv\SumatraPDF.exe" -SaveConfig.'
            ) }
        }
    }
}

function Invoke-LocalPrintDispatch {
    <#
      MÁY KHO TỰ NHẬN VIỆC IN — không cần trình duyệt mở trang "Điều phối Giao hàng".

      Vì sao cần: đường in qua hộp IoT bắt buộc phải có tab dashboard đang mở để JS gọi report
      action (server Odoo.sh không vào được LAN kho). Đóng tab là hàng chờ nằm im vô thời hạn.
      Hàm này hỏi Odoo lấy PDF rồi in thẳng bằng driver máy in Windows của máy này.

      Luôn BÁO KẾT QUẢ về Odoo (in được hay lỗi gì) — không báo thì bản ghi kẹt ở "Đang in..."
      và Odoo sẽ tự đưa lại vào hàng chờ sau vài phút.
      Trả về số phiếu đã in được trong lượt này.
    #>
    if (-not $PrinterName) {
        Write-WatchdogLog 'Bo qua in truc tiep: chua chi dinh -PrinterName cho may nay.' 'WARN'
        return 0
    }
    $claim = Invoke-OdooJson -Path '/api/iot_watchdog/claim_print_jobs' -Params @{
        token          = $Token
        warehouse_code = $WarehouseCode
        limit          = $DispatchBatch
    }
    if ($null -eq $claim) { return 0 }
    if (-not $claim.success) {
        Write-WatchdogLog "Odoo tu choi claim_print_jobs: $($claim.message)" 'ERROR'
        return 0
    }
    $jobs = @($claim.jobs)
    if ($jobs.Count -eq 0) { return 0 }

    Write-WatchdogLog "Nhan $($jobs.Count) phieu can in truc tiep tu Odoo (kho $WarehouseCode)."
    $results = @()
    $printedOk = 0
    foreach ($job in $jobs) {
        $tmp = Join-Path $env:TEMP ("hlv_print_{0}.pdf" -f $job.queue_id)
        $res = $null
        try {
            [IO.File]::WriteAllBytes($tmp, [Convert]::FromBase64String($job.pdf_b64))
            $res = Out-PdfToPrinter -PdfPath $tmp -Printer $PrinterName
        } catch {
            $res = @{ ok = $false; message = "Loi ghi file PDF tam: $($_.Exception.Message)" }
        }
        if ($res.ok) {
            $printedOk++
            Write-WatchdogLog "Da in phieu don $($job.sale_order_name) (hang cho #$($job.queue_id)): $($res.message)"
        } else {
            Write-WatchdogLog "IN THAT BAI phieu don $($job.sale_order_name) (hang cho #$($job.queue_id)): $($res.message)" 'ERROR'
            # Giữ lại file PDF khi in lỗi: cần biết PDF có hợp lệ không mới phân biệt được lỗi
            # nằm ở Odoo (render sai) hay ở công cụ in/máy in.
            Write-WatchdogLog "File PDF duoc giu lai de kiem tra: $tmp (mo thu bang tay xem co doc duoc khong)" 'WARN'
        }
        $results += @{
            queue_id = $job.queue_id
            success  = [bool]$res.ok
            message  = [string]$res.message
            printer  = $PrinterName
        }
        # Xoá file tạm khi ĐÃ IN ĐƯỢC: PDF chứa thông tin đơn hàng, không để rơi rớt trong TEMP.
        # Chờ 1 nhịp cho tiến trình in đọc xong file (Start-Process -Wait đã xong với SumatraPDF,
        # nhưng shell verb thì mở trình đọc PDF chạy nền nên có thể còn đang đọc).
        # In LỖI thì giữ file lại làm bằng chứng (xem log ở trên).
        if ($res.ok) {
            try { Start-Sleep -Milliseconds 500; Remove-Item $tmp -Force -ErrorAction Stop } catch { }
        }
    }

    $report = Invoke-OdooJson -Path '/api/iot_watchdog/report_print_result' -Params @{
        token          = $Token
        warehouse_code = $WarehouseCode
        results        = $results
    }
    if ($null -eq $report -or -not $report.success) {
        # Không báo được kết quả: Odoo vẫn thấy bản ghi ở "Đang in..." và sẽ tự đưa lại hàng chờ
        # sau ~10 phút => có thể IN TRÙNG 1 tờ. Nói rõ để người xử lý biết, đừng đoán.
        Write-WatchdogLog (
            'KHONG bao duoc ket qua in ve Odoo: cac phieu vua in se bi Odoo dua lai hang cho sau ' +
            '~10 phut va co the in trung 1 to. Kiem tra ket noi mang toi Odoo.'
        ) 'ERROR'
    }
    return $printedOk
}

function Invoke-WatchdogCycle {
    <# 1 vòng kiểm tra + gửi tín hiệu. Trả về hashtable để hàm gọi biết kết quả. #>

    # --- 1. Kiểm tra service --------------------------------------------------------
    $serviceOk = $false
    $serviceStatus = 'KHONG_TIM_THAY'
    $noteParts = @("may=$env:COMPUTERNAME")
    # Phải reset mỗi vòng: nếu vòng này không đọc được counter mà vẫn còn giá trị vòng trước,
    # Odoo sẽ tưởng máy in không in thêm tờ nào và kết luận oan là "chưa in ra".
    $script:PrintedTotal = $null
    $script:UnprintedFound = 0
    # Số yêu cầu in đang nằm chờ mà chưa ai đẩy xuống máy in (Odoo tính, trả về trong heartbeat).
    $script:PendingStuck = 0
    $script:PendingStuckMessage = ''

    try {
        $svc = Get-Service -Name $ServiceName -ErrorAction Stop
        $serviceStatus = "$($svc.Status)"
        $serviceOk = ($svc.Status -eq 'Running')
        $noteParts += "service=$serviceStatus"

        if (-not $serviceOk) {
            Write-WatchdogLog "Service '$ServiceName' đang $serviceStatus." 'WARN'
            if ($NoAutoRestart) {
                Write-WatchdogLog 'Bỏ qua việc tự bật lại service vì đang chạy với -NoAutoRestart.' 'WARN'
            } else {
                Write-WatchdogLog "Đang thử bật lại service '$ServiceName'..." 'WARN'
                try {
                    Start-Service -Name $ServiceName -ErrorAction Stop
                    Start-Sleep -Seconds 10
                    $svc = Get-Service -Name $ServiceName -ErrorAction Stop
                    $serviceStatus = "$($svc.Status)"
                    $serviceOk = ($svc.Status -eq 'Running')
                    if ($serviceOk) {
                        $noteParts += 'da_tu_restart=OK'
                        Write-WatchdogLog 'Đã bật lại service thành công.' 'INFO'
                    } else {
                        $noteParts += "da_tu_restart=THAT_BAI($serviceStatus)"
                        Write-WatchdogLog "Bật lại service KHÔNG thành công: $serviceStatus" 'ERROR'
                    }
                } catch {
                    $noteParts += 'da_tu_restart=LOI'
                    Write-WatchdogLog "Lỗi khi bật lại service: $($_.Exception.Message)" 'ERROR'
                }
            }
        }
    } catch {
        # Không tìm thấy service = cấu hình sai tên, hoặc Odoo IoT chưa cài như service.
        $noteParts += 'service=KHONG_TIM_THAY'
        Write-WatchdogLog "Không tìm thấy service '$ServiceName': $($_.Exception.Message)" 'ERROR'
    }

    # --- 2. Kiểm tra service hàng đợi in (Spooler) -----------------------------------
    # Spooler treo/tắt = Odoo vẫn báo "đã gửi lệnh in" nhưng KHÔNG có job nào vào máy in.
    $spoolerOk = $true
    try {
        $spooler = Get-Service -Name $SpoolerServiceName -ErrorAction Stop
        $noteParts += "spooler=$($spooler.Status)"
        $spoolerOk = ($spooler.Status -eq 'Running')
        if (-not $spoolerOk) {
            Write-WatchdogLog "Service hàng đợi in '$SpoolerServiceName' đang $($spooler.Status)." 'WARN'
            if (-not $NoAutoRestart) {
                try {
                    Start-Service -Name $SpoolerServiceName -ErrorAction Stop
                    Start-Sleep -Seconds 5
                    $spoolerOk = ((Get-Service -Name $SpoolerServiceName).Status -eq 'Running')
                    $noteParts += "spooler_restart=$(if ($spoolerOk) { 'OK' } else { 'THAT_BAI' })"
                    Write-WatchdogLog "Bật lại '$SpoolerServiceName': $(if ($spoolerOk) { 'thành công' } else { 'KHÔNG thành công' })" 'WARN'
                } catch {
                    $noteParts += 'spooler_restart=LOI'
                    Write-WatchdogLog "Lỗi bật lại '$SpoolerServiceName': $($_.Exception.Message)" 'ERROR'
                }
            }
        }
    } catch {
        $noteParts += 'spooler=KHONG_DOC_DUOC'
        Write-WatchdogLog "Không đọc được service '$SpoolerServiceName': $($_.Exception.Message)" 'WARN'
    }

    # --- 3. Kiểm tra máy in + JOB TREO trong hàng đợi --------------------------------
    # Đây là tình huống thực tế đã gặp: Odoo báo "đã gửi lệnh in" mà máy không ra giấy,
    # xoá hàng đợi thì in lại bình thường => hàng đợi bị nghẽn bởi 1 job treo, mọi lệnh
    # sau đó nằm im theo. Watchdog tự phát hiện và tự xoá đúng như thao tác tay đó.
    $clearedJobs = 0
    if ($PrinterName) {
        try {
            $printer = Get-Printer -Name $PrinterName -ErrorAction Stop
            $jobs = @(Get-PrintJob -PrinterName $PrinterName -ErrorAction SilentlyContinue)
            $noteParts += "may_in=$($printer.PrinterStatus)"
            $noteParts += "job_dang_cho=$($jobs.Count)"
            if ($printer.PrinterStatus -ne 'Normal') {
                Write-WatchdogLog "Máy in '$PrinterName' trạng thái $($printer.PrinterStatus), $($jobs.Count) job đang chờ." 'WARN'
            }

            # TỔNG SỐ JOB WINDOWS ĐÃ IN từ lúc khởi động máy (performance counter của Windows).
            # Đây là bằng chứng để phân biệt 2 tình huống "Odoo báo đã gửi lệnh in mà không ra giấy":
            #   - số này TĂNG  => Windows đã nhận + in, lỗi nằm ở máy in/giấy/mực.
            #   - số này ĐỨNG  => lệnh in KHÔNG hề tới Windows (đứt ở khâu trình duyệt/hộp IoT),
            #     lúc đó xoá hàng đợi vô ích, phải khởi động lại service Odoo IoT.
            # Ghi vào note nên xem lại được trong Odoo (Kho hàng > Watchdog: ghi chú lần cuối).
            $printedTotalNow = Get-PrinterPrintedTotal -Printer $PrinterName
            if ($null -ne $printedTotalNow) {
                $script:PrintedTotal = $printedTotalNow
                $noteParts += "da_in_tong=$($script:PrintedTotal)"
            }

            $nowLocal = Get-Date
            $stuck = @($jobs | Where-Object {
                # Không đọc được SubmittedTime => coi như KHÔNG treo (an toàn). Xoá oan 1 phiếu
                # vừa gửi in tệ hơn là bỏ sót 1 job treo — vòng sau (2 phút) vẫn bắt được nó.
                $ageMin = -1
                if ($_.SubmittedTime) { $ageMin = ($nowLocal - $_.SubmittedTime).TotalMinutes }
                ($ageMin -ge $StuckJobMinutes) -or ("$($_.JobStatus)" -match 'Error|Blocked|Offline|PaperOut|Paused')
            })
            if ($stuck.Count -gt 0) {
                $noteParts += "job_treo=$($stuck.Count)"
                Write-WatchdogLog "Phát hiện $($stuck.Count) job in TREO trên '$PrinterName' (>= $StuckJobMinutes phút hoặc trạng thái lỗi)." 'WARN'
                if ($NoAutoClearStuckJobs) {
                    Write-WatchdogLog 'Không tự xoá job treo vì đang chạy với -NoAutoClearStuckJobs.' 'WARN'
                } else {
                    $removeFailed = $false
                    foreach ($j in $stuck) {
                        try {
                            Remove-PrintJob -PrinterName $PrinterName -ID $j.Id -ErrorAction Stop
                            $clearedJobs++
                            Write-WatchdogLog "Đã xoá job treo #$($j.Id) '$($j.DocumentName)' (trạng thái $($j.JobStatus))." 'WARN'
                        } catch {
                            $removeFailed = $true
                            Write-WatchdogLog "Không xoá được job #$($j.Id): $($_.Exception.Message)" 'ERROR'
                        }
                    }
                    # Xoá từng job không được thì khởi động lại Spooler — cách này luôn dọn
                    # sạch được hàng đợi, nhưng xoá job của MỌI máy in trên máy này nên chỉ
                    # dùng khi cách nhẹ đã thất bại.
                    if ($removeFailed -and -not $NoAutoRestart) {
                        try {
                            Restart-Service -Name $SpoolerServiceName -Force -ErrorAction Stop
                            $noteParts += 'spooler=DA_RESTART_DE_DON_QUEUE'
                            Write-WatchdogLog "Đã khởi động lại '$SpoolerServiceName' để dọn hàng đợi in bị nghẽn." 'WARN'
                        } catch {
                            Write-WatchdogLog "Không khởi động lại được '$SpoolerServiceName': $($_.Exception.Message)" 'ERROR'
                        }
                    }
                }
            }
        } catch {
            $noteParts += 'may_in=KHONG_DOC_DUOC'
            Write-WatchdogLog "Không đọc được máy in '$PrinterName': $($_.Exception.Message)" 'WARN'
        }
    }

    # --- 2b. IN TRỰC TIẾP tại máy này (nếu bật -LocalDispatch) ----------------------
    # Đặt TRƯỚC heartbeat để con số "yêu cầu in đang nằm chờ" mà Odoo trả về phản ánh tình trạng
    # SAU khi đã in xong lượt này, tránh báo động oan.
    if ($LocalDispatch) {
        try {
            $dispatched = Invoke-LocalPrintDispatch
            if ($dispatched -gt 0) { $noteParts += "in_truc_tiep=$dispatched" }
        } catch {
            Write-WatchdogLog "Loi khong mong doi khi in truc tiep: $($_.Exception.Message)" 'ERROR'
        }
    }

    # --- 3. Gửi heartbeat về Odoo ---------------------------------------------------
    $note = ($noteParts -join '; ')
    $endpoint = "$($OdooUrl.TrimEnd('/'))/api/iot_watchdog/heartbeat"
    # Route Odoo type='json' cần đúng phong bì JSON-RPC 2.0, không phải JSON phẳng.
    $params = @{
        token          = $Token
        warehouse_code = $WarehouseCode
        service_ok     = [bool]$serviceOk
        note           = $note
    }
    # printed_total: TỔNG số job Windows đã in trên máy in này. Odoo lấy con số này đối chiếu
    # với số lệnh in đã gửi để phát hiện phiếu "đã gửi lệnh in" mà không ra giấy. Chỉ gửi khi
    # đọc được — gửi 0 khi không đọc được sẽ làm Odoo tưởng máy in không in gì và báo oan.
    if ($null -ne $script:PrintedTotal) { $params.printed_total = [int]$script:PrintedTotal }
    $payload = @{
        jsonrpc = '2.0'
        method  = 'call'
        params  = $params
    } | ConvertTo-Json -Depth 5 -Compress

    $heartbeatOk = $false
    $heartbeatError = ''
    try {
        $resp = Invoke-RestMethod -Uri $endpoint -Method Post -ContentType 'application/json; charset=utf-8' `
            -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -TimeoutSec 30 -ErrorAction Stop
        if ($resp.result -and $resp.result.success) {
            $heartbeatOk = $true
            Write-WatchdogLog "Đã gửi heartbeat cho kho $($resp.result.warehouse_name) (service_ok=$serviceOk; $note)."
            # Odoo đối chiếu xong và trả về số phiếu "đã gửi lệnh in mà máy in không in ra
            # giấy" — báo NGAY tại máy kho, đây là người duy nhất xử lý được (in lại/kiểm giấy).
            if ($resp.result.unprinted_found -and [int]$resp.result.unprinted_found -gt 0) {
                $script:UnprintedFound = [int]$resp.result.unprinted_found
                Write-WatchdogLog (
                    "Odoo phát hiện $($script:UnprintedFound) phiếu ĐÃ GỬI LỆNH IN nhưng máy in " +
                    'KHÔNG in ra giấy — xem "Hàng chờ in (IoT)" trên Odoo để gửi in lại.'
                ) 'ERROR'
            }
            # Máy in OK, service OK, mà phiếu vẫn không ra giấy vì KHÔNG CÓ AI DISPATCH: lệnh in
            # do trình duyệt đẩy xuống hộp IoT, không mở trang "Điều phối Giao hàng" thì hàng chờ
            # nằm im vô thời hạn. Người ngồi ở máy này là người duy nhất mở được trang đó.
            if ($resp.result.pending_stuck -and [int]$resp.result.pending_stuck -gt 0) {
                $script:PendingStuck = [int]$resp.result.pending_stuck
                $script:PendingStuckMessage = [string]$resp.result.pending_stuck_message
                $huong = if ($LocalDispatch) {
                    'duong in truc tiep dang bat nhung chua in duoc chung (xem log ben tren).'
                } else {
                    'can MO trang "Dieu phoi Giao hang" tren may nay (hoac bat -LocalDispatch).'
                }
                Write-WatchdogLog (
                    "Odoo bao co $($script:PendingStuck) yeu cau in dang NAM CHO chua duoc gui " +
                    "xuong may in — $huong"
                ) 'ERROR'
                $dispatcherUrl = [string]$resp.result.dispatcher_url
                if ($AutoOpenDispatcher -and $dispatcherUrl) {
                    $sinceOpen = $null
                    if ($script:LastDispatcherOpenUtc) {
                        $sinceOpen = ((Get-Date).ToUniversalTime() - $script:LastDispatcherOpenUtc).TotalMinutes
                    }
                    if ($null -eq $sinceOpen -or $sinceOpen -ge $AutoOpenRepeatMinutes) {
                        try {
                            Start-Process $dispatcherUrl -ErrorAction Stop
                            $script:LastDispatcherOpenUtc = (Get-Date).ToUniversalTime()
                            Write-WatchdogLog "Da tu mo trang dieu phoi: $dispatcherUrl" 'WARN'
                        } catch {
                            Write-WatchdogLog "Khong mo duoc trang dieu phoi '$dispatcherUrl': $($_.Exception.Message)" 'ERROR'
                        }
                    } else {
                        Write-WatchdogLog (
                            'Da tu mo trang dieu phoi cach day ' + [int]$sinceOpen + ' phut, cho du ' +
                            "$AutoOpenRepeatMinutes phut moi mo lai (tranh mo hang loat tab)."
                        ) 'WARN'
                    }
                }
            }
        } else {
            $heartbeatError = 'khong ro'
            if ($resp.result -and $resp.result.message) { $heartbeatError = $resp.result.message }
            elseif ($resp.error) { $heartbeatError = $resp.error.data.message }
            Write-WatchdogLog "Odoo TỪ CHỐI heartbeat: $heartbeatError" 'ERROR'
        }
    } catch {
        # Không gửi được = mất mạng/Odoo down. Odoo sẽ tự thấy "im lặng quá N phút" và cảnh báo.
        $heartbeatError = $_.Exception.Message
        # Kèm luôn $note: khi không gửi được về Odoo thì đây là chỗ DUY NHẤT còn thấy được
        # tình trạng service/spooler/máy in của máy kho lúc đó.
        Write-WatchdogLog "Không gửi được heartbeat tới $endpoint : $heartbeatError [trạng thái máy: $note]" 'ERROR'
    }

    # --- 4. Cảnh báo tại máy khi có sự cố (có chống spam) ---------------------------
    $problems = @()
    if (-not $serviceOk) {
        $problems += "Service Odoo IoT '$ServiceName' dang $serviceStatus (khong phai Running) => may in cua kho KHONG in duoc."
    }
    if (-not $spoolerOk) {
        $problems += "Service hang doi in Windows ('$SpoolerServiceName') KHONG chay => Odoo bao 'da gui lenh in' nhung may in khong nhan duoc job nao."
    }
    if ($script:UnprintedFound -gt 0) {
        $problems += "Odoo doi chieu: co $($script:UnprintedFound) phieu DA GUI LENH IN nhung may in KHONG in ra giay => vao 'Hang cho in (IoT)' tren Odoo gui in lai."
    }
    if ($script:PendingStuck -gt 0) {
        $msg = $script:PendingStuckMessage
        if (-not $msg) {
            $msg = "Co $($script:PendingStuck) yeu cau in dang nam cho chua duoc gui xuong may in."
        }
        # Lời khuyên phải ĐÚNG theo cấu hình: nếu đường in trực tiếp đang bật mà phiếu vẫn nằm
        # chờ thì mở tab điều phối không phải là cách sửa — chính đường in trực tiếp đang hỏng.
        if ($LocalDispatch) {
            $problems += (
                $msg + ' Duong in truc tiep DANG BAT ma phieu van nam cho => kiem tra log ' +
                "'$LogFile' xem cong cu in PDF (-PdfPrintExe) va ten may in (-PrinterName) co dung khong."
            )
        } else {
            $problems += (
                $msg + ' Lenh in duoc day tu TRINH DUYET: phai mo trang "Dieu phoi Giao hang" tren ' +
                'may nay thi cac phieu do moi in ra (hoac bat duong in truc tiep: -LocalDispatch). ' +
                'Yeu cau KHONG bi mat.'
            )
        }
    }
    if ($clearedJobs -gt 0) {
        # Cảnh báo NÀY quan trọng về nghiệp vụ: job đã bị xoá nghĩa là phiếu đó KHÔNG ra
        # giấy — kho phải chủ động gửi in lại, đừng tưởng Odoo báo "đã gửi lệnh in" là xong.
        $problems += "Da xoa $clearedJobs job in bi TREO tren may in '$PrinterName' => nhung phieu do CHUA IN RA, can vao Odoo gui in lai."
    }
    if (-not $heartbeatOk) {
        $problems += "Khong gui duoc tin hieu ve Odoo ($heartbeatError) => kiem tra mang/Internet cua may nay."
    }

    $state = Get-WatchdogState
    $nowUtc = (Get-Date).ToUniversalTime()
    if ($problems.Count -gt 0) {
        $shouldAlert = $true
        if ($state.bad -and $state.lastAlertUtc) {
            $minsSince = ($nowUtc - $state.lastAlertUtc).TotalMinutes
            if ($minsSince -lt $AlertRepeatMinutes) { $shouldAlert = $false }
        }
        if ($shouldAlert) {
            Show-LocalAlert -Title "LOI MAY IN IoT - KHO $WarehouseCode" -Message ($problems -join ' | ')
            Set-WatchdogState -Bad $true -LastAlertUtc $nowUtc
        } else {
            # Nói rõ VÌ SAO im lặng — trước đây script phát hiện lỗi rồi tắt luôn mà không hiện
            # gì, người dùng tưởng script hỏng. Giờ luôn có 1 dòng giải thích.
            $waitLeft = [math]::Max(0, [math]::Round($AlertRepeatMinutes - $minsSince, 1))
            Write-WatchdogLog (
                "VẪN ĐANG LỖI: $($problems -join ' | ') — đã cảnh báo cách đây " +
                "$([math]::Round($minsSince,1)) phút nên tạm không hiện lại (còn $waitLeft phút). " +
                'Muốn hiện ngay mỗi lần: thêm -AlertRepeatMinutes 0.'
            ) 'WARN'
            Set-WatchdogState -Bad $true -LastAlertUtc $state.lastAlertUtc
        }
    } else {
        if ($state.bad) {
            Write-WatchdogLog 'Đã hoạt động lại bình thường (service Running + gửi được tín hiệu về Odoo).' 'INFO'
            Write-WatchdogEventLog -Message "Kho ${WarehouseCode}: may in IoT da hoat dong lai binh thuong." -EntryType 'Information'
        }
        Set-WatchdogState -Bad $false -LastAlertUtc $null
    }

    $code = 0
    if (-not $serviceOk) { $code = 1 }
    elseif (-not $heartbeatOk) { $code = 3 }
    return @{ ServiceOk = $serviceOk; HeartbeatOk = $heartbeatOk; ExitCode = $code }
}

# --- Chạy: liên tục hoặc 1 lần ------------------------------------------------------
if ($LoopSeconds -gt 0) {
    # Chống chạy TRÙNG: chế độ liên tục thường được task "mỗi 10 phút" gọi lại để tự hồi sinh
    # nếu tiến trình cũ đã chết. Nếu tiến trình cũ VẪN CÒN thì bản mới phải thoát ngay, nếu
    # không sẽ có nhiều tiến trình cùng gửi heartbeat + cùng bật lại service.
    $mutexName = 'Global\HLV_IoT_Watchdog_' + $WarehouseCode
    try {
        $script:SingleInstance = New-Object System.Threading.Mutex($false, $mutexName)
    } catch {
        # Không tạo được mutex Global (thiếu quyền) thì lùi về phạm vi phiên đăng nhập.
        $script:SingleInstance = New-Object System.Threading.Mutex($false, ('Local\HLV_IoT_Watchdog_' + $WarehouseCode))
    }
    $gotLock = $false
    try { $gotLock = $script:SingleInstance.WaitOne(0) } catch { $gotLock = $false }
    if (-not $gotLock) {
        Write-WatchdogLog "Đã có 1 tiến trình watchdog chạy liên tục cho kho $WarehouseCode — thoát ngay, không chạy trùng." 'INFO'
        exit 0
    }
    Write-WatchdogLog "Bắt đầu chế độ CHẠY LIÊN TỤC: kiểm tra mỗi $LoopSeconds giây (Ctrl+C để dừng). Kho=$WarehouseCode, service=$ServiceName." 'INFO'
    while ($true) {
        try {
            $null = Invoke-WatchdogCycle
        } catch {
            Write-WatchdogLog "Lỗi bất ngờ trong vòng kiểm tra: $($_.Exception.Message)" 'ERROR'
        }
        Start-Sleep -Seconds $LoopSeconds
    }
}

$result = Invoke-WatchdogCycle
# Nói rõ vì sao cửa sổ tắt ngay: đây là chế độ CHẠY 1 LẦN (dành cho Task Scheduler).
Write-WatchdogLog (
    "Kết thúc (chế độ chạy 1 LẦN, exit=$($result.ExitCode)). Muốn cửa sổ chạy hoài và tự kiểm " +
    'tra lặp lại thì thêm: -LoopSeconds 120'
) 'INFO'
exit $result.ExitCode
