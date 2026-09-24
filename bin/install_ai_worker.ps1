#Requires -Version 5.1
<#
=====================================================================================
 install_ai_worker.ps1 — CÀI WORKER AI LÊN MỘT MÁY MỚI, chạy một lần là xong.
=====================================================================================
 Worker là script Python nằm chờ Odoo gọi: máy này mở MỘT websocket ra Odoo và giữ,
 nên KHÔNG phải mở port nào trên router.

 Bấm đôi vào install_ai_worker.cmd (cùng thư mục) là chạy file này. Không cần quyền
 Administrator: biến môi trường đặt ở phạm vi User, tác vụ tạo cho chính người đang
 đăng nhập (/RL LIMITED).

 Làm 7 bước, dừng ngay khi có bước hỏng chứ không chạy tiếp:
   1. Tìm Python và ai_worker.py trong repo
   2. Tìm claude.exe (worker gọi Claude bằng tài khoản đang đăng nhập trên máy này)
   3. Cài thư viện websockets
   4. Hỏi 5 thông số kết nối (bỏ trống = giữ giá trị cũ, nên chạy lại rất nhanh)
   5. Ghi biến môi trường phạm vi User + nạp luôn vào phiên này
   6. Chạy thử --once, phải thành công mới đi tiếp
   7. Tạo tác vụ "HLV AI Worker" chạy khi đăng nhập Windows, rồi bật luôn

 LÀM TRƯỚC TRONG ODOO (một lần cho cả công ty, không phải mỗi máy):
   - Tạo user riêng cho worker, cho nhóm "Xem bản đồ đội xe"
   - V-Tracking > Cấu hình > Kết nối vTracking: chọn user đó ở ô "Tài khoản worker AI"
   - V-Tracking > Cấu hình > Khoá API: tạo khoá, BẬT "Cho phép ghi"

 Gỡ: schtasks /Delete /TN "HLV AI Worker" /F
=====================================================================================
#>

[CmdletBinding()]
param(
    # Bỏ qua bước chạy thử (chỉ dùng khi đã biết chắc cấu hình đúng).
    [switch]$SkipTest
)

$ErrorActionPreference = 'Stop'
$TEN_TAC_VU = 'HLV AI Worker'

function Buoc($so, $chu) {
    Write-Host ""
    Write-Host ("[$so] $chu") -ForegroundColor Cyan
    Write-Host ("-" * 68)
}
function Ok($chu)   { Write-Host "  OK   $chu" -ForegroundColor Green }
function Loi($chu)  { Write-Host "  LỖI  $chu" -ForegroundColor Red }
function Nhac($chu) { Write-Host "  ->   $chu" -ForegroundColor Yellow }

function Dung($chu) {
    Loi $chu
    Write-Host ""
    Write-Host "Dừng tại đây, chưa thay đổi gì thêm. Sửa xong chạy lại file này." -ForegroundColor Red
    Read-Host "Nhấn Enter để đóng"
    exit 1
}

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor White
Write-Host "  CÀI WORKER AI — máy $env:COMPUTERNAME, người dùng $env:USERNAME"
Write-Host "=====================================================================" -ForegroundColor White

# --- 1. Python + repo ---------------------------------------------------------------
Buoc 1 "Tìm Python và script worker"

$py = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $py) { $py = (Get-Command python -ErrorAction SilentlyContinue) }
if (-not $py) {
    Dung "Chưa có Python. Cài từ python.org (nhớ tick 'Add python.exe to PATH') rồi chạy lại."
}
Ok "Python: $($py.Source)  ($(& $py.Source -V 2>&1))"

# bin\install_ai_worker.ps1 -> gốc repo là thư mục cha của bin
$repo = Split-Path -Parent $PSScriptRoot
$workerPy = Join-Path $repo '.claude\skills\dieu-phoi-giao-hang\scripts\ai_worker.py'
if (-not (Test-Path $workerPy)) {
    Dung "Không thấy $workerPy — file này phải nằm trong thư mục bin\ của repo đã clone."
}
Ok "Worker: $workerPy"

# pythonw/pyw chạy không hiện cửa sổ đen mỗi lần đăng nhập.
$pyw = (Get-Command pyw -ErrorAction SilentlyContinue)
if (-not $pyw) { $pyw = (Get-Command pythonw -ErrorAction SilentlyContinue) }
if ($pyw) { Ok "Chạy ẩn bằng: $($pyw.Source)" }
else      { Nhac "Không có pyw/pythonw — sẽ chạy bằng $($py.Source), có cửa sổ đen khi đăng nhập." }

# --- 2. Claude ----------------------------------------------------------------------
Buoc 2 "Tìm Claude (worker gọi Claude bằng tài khoản đang đăng nhập trên MÁY NÀY)"

$claude = $env:CLAUDE_BIN
if ($claude -and -not (Test-Path $claude)) { $claude = $null }
if (-not $claude) {
    $c = Get-Command claude -ErrorAction SilentlyContinue
    if ($c) { $claude = $c.Source }
}
if (-not $claude) {
    # Bản đi kèm extension VSCode — đúng chỗ ai_worker.py tự dò.
    $mau = Join-Path $env:USERPROFILE '.vscode\extensions\anthropic.claude-code-*\resources\native-binary\claude*'
    $tim = Get-ChildItem -Path $mau -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($tim) { $claude = $tim.FullName }
}
if ($claude) {
    Ok "Claude: $claude"
} else {
    Nhac "Chưa tìm thấy claude.exe. Worker vẫn cài được nhưng sẽ KHÔNG xử lý được phiếu."
    Nhac "Cài Claude Code trên máy này rồi đăng nhập, hoặc đặt biến CLAUDE_BIN trỏ tới claude.exe."
}

# --- 3. Thư viện --------------------------------------------------------------------
Buoc 3 "Thư viện websockets"

& $py.Source -c "import websockets" 2>$null
if ($LASTEXITCODE -eq 0) {
    Ok "Đã có sẵn."
} else {
    Write-Host "  Đang cài (pip install --user websockets)..."
    & $py.Source -m pip install --user --quiet websockets
    & $py.Source -c "import websockets" 2>$null
    if ($LASTEXITCODE -ne 0) { Dung "Cài websockets không xong. Xem lỗi pip phía trên." }
    Ok "Cài xong."
}

# --- 4. Hỏi thông số ----------------------------------------------------------------
Buoc 4 "Thông số kết nối Odoo (Enter = giữ nguyên giá trị đang có)"

function HoiGiaTri($ten, $nhan, $mau) {
    $cu = [Environment]::GetEnvironmentVariable($ten, 'User')
    $hienThi = if ($cu) { $cu } else { "(chưa có) ví dụ: $mau" }
    Write-Host ""
    Write-Host "  $nhan"
    Write-Host "    hiện tại: $hienThi" -ForegroundColor DarkGray
    $moi = Read-Host "    nhập mới"
    if ([string]::IsNullOrWhiteSpace($moi)) { return $cu }
    return $moi.Trim()
}

$baseUrl = HoiGiaTri 'VTRACKING_BASE_URL'  'Địa chỉ Odoo'                'https://hoanglongvu.odoo.com'
$apiKey  = HoiGiaTri 'VTRACKING_API_KEY'   'Khoá API (đã bật Cho phép ghi)' 'abc123...'
$db      = HoiGiaTri 'VTRACKING_DB'        'Tên database'                'hoanglongvu'
$login   = HoiGiaTri 'VTRACKING_WORKER_LOGIN' 'Tài khoản worker'         'ai.worker@hoanglongvu.com'

$cuPass = [Environment]::GetEnvironmentVariable('VTRACKING_WORKER_PASSWORD', 'User')
Write-Host ""
Write-Host "  Mật khẩu tài khoản worker"
Write-Host ("    hiện tại: " + $(if ($cuPass) { "(đã có, Enter để giữ)" } else { "(chưa có)" })) -ForegroundColor DarkGray
$secure = Read-Host "    nhập mới" -AsSecureString
$passMoi = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
$password = if ([string]::IsNullOrWhiteSpace($passMoi)) { $cuPass } else { $passMoi }

$thieu = @()
if (-not $baseUrl)  { $thieu += 'VTRACKING_BASE_URL' }
if (-not $apiKey)   { $thieu += 'VTRACKING_API_KEY' }
if (-not $db)       { $thieu += 'VTRACKING_DB' }
if (-not $login)    { $thieu += 'VTRACKING_WORKER_LOGIN' }
if (-not $password) { $thieu += 'VTRACKING_WORKER_PASSWORD' }
if ($thieu.Count) { Dung ("Còn thiếu: " + ($thieu -join ', ')) }

# --- 5. Ghi biến môi trường ---------------------------------------------------------
Buoc 5 "Ghi biến môi trường (phạm vi User — không nằm trong repo, không dùng chung máy)"

$bien = @{
    'VTRACKING_BASE_URL'        = $baseUrl
    'VTRACKING_API_KEY'         = $apiKey
    'VTRACKING_DB'              = $db
    'VTRACKING_WORKER_LOGIN'    = $login
    'VTRACKING_WORKER_PASSWORD' = $password
}
foreach ($k in $bien.Keys) {
    [Environment]::SetEnvironmentVariable($k, $bien[$k], 'User')
    # Nạp luôn vào phiên đang chạy, để bước 6 thử được ngay mà không cần mở cửa sổ mới.
    Set-Item -Path "Env:$k" -Value $bien[$k]
}
if ($claude -and -not $env:CLAUDE_BIN) {
    [Environment]::SetEnvironmentVariable('CLAUDE_BIN', $claude, 'User')
    Set-Item -Path 'Env:CLAUDE_BIN' -Value $claude
    Ok "Ghi thêm CLAUDE_BIN để worker khỏi phải dò lại."
}
Ok ("Đã ghi " + $bien.Count + " biến. Mật khẩu chỉ nằm trong biến môi trường của người dùng Windows.")

# --- 6. Chạy thử --------------------------------------------------------------------
if ($SkipTest) {
    Buoc 6 "Chạy thử — BỎ QUA theo yêu cầu (-SkipTest)"
} else {
    Buoc 6 "Chạy thử: xử lý hết phiếu đang chờ rồi thoát (py ai_worker.py --once)"
    Write-Host "  Đang chạy, chờ chút..." -ForegroundColor DarkGray
    & $py.Source $workerPy --once
    if ($LASTEXITCODE -ne 0) {
        Loi "Chạy thử trả về mã lỗi $LASTEXITCODE."
        Nhac "Thường gặp: sai địa chỉ Odoo, sai khoá API, khoá API chưa bật 'Cho phép ghi',"
        Nhac "sai tài khoản/mật khẩu worker, hoặc máy không ra được internet."
        Nhac "Nhật ký: $env:LOCALAPPDATA\hlv_ai_worker\worker.log"
        Dung "Chưa tạo tác vụ tự chạy — sửa xong chạy lại file này."
    }
    Ok "Chạy thử xong, không lỗi."
}

# --- 7. Tác vụ tự chạy --------------------------------------------------------------
Buoc 7 "Tác vụ '$TEN_TAC_VU' — tự chạy mỗi lần đăng nhập Windows"

$chayBang = if ($pyw) { $pyw.Source } else { $py.Source }
$lenh = '"{0}" "{1}"' -f $chayBang, $workerPy
schtasks /Create /TN "$TEN_TAC_VU" /SC ONLOGON /RL LIMITED /F /TR $lenh | Out-Null
if ($LASTEXITCODE -ne 0) { Dung "Không tạo được tác vụ (mã $LASTEXITCODE)." }
Ok "Đã tạo tác vụ."

schtasks /Run /TN "$TEN_TAC_VU" | Out-Null
if ($LASTEXITCODE -eq 0) { Ok "Đã bật chạy ngay, không cần đăng xuất." }
else { Nhac "Chưa bật được ngay — đăng xuất rồi đăng nhập lại là nó tự chạy." }

Start-Sleep -Seconds 3
Write-Host ""
schtasks /Query /TN "$TEN_TAC_VU" /FO LIST /V | Select-String -Pattern 'TaskName|Status|Last Run Time|Last Result|Task To Run'

# --- Kết ----------------------------------------------------------------------------
Write-Host ""
Write-Host "=====================================================================" -ForegroundColor White
Write-Host "  XONG" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor White
Write-Host "  Nhật ký worker : $env:LOCALAPPDATA\hlv_ai_worker\worker.log"
Write-Host "  Xem tác vụ     : schtasks /Query /TN `"$TEN_TAC_VU`" /FO LIST /V"
Write-Host "  Gỡ cài         : schtasks /Delete /TN `"$TEN_TAC_VU`" /F"
Write-Host ""
Write-Host "  Kiểm cuối: vào Odoo tạo một phiếu yêu cầu thử, phiếu phải chuyển sang"
Write-Host "  'AI đã trả lời' trong vòng vài giây."
Write-Host ""
Write-Host "  Lưu ý: worker chỉ chạy khi NGƯỜI DÙNG NÀY đang đăng nhập Windows. Máy tắt"
Write-Host "  hay đăng xuất thì phiếu nằm chờ chứ không mất — bật lại là vét hết."
Write-Host ""
Read-Host "Nhấn Enter để đóng"
