# Cai dat agent tro ly tao ma hang - chay tren may co Claude Code
#
# Chay mot lenh duy nhat (lay o form "May chay Claude" trong Odoo):
#   $env:HLV_ODOO_URL='https://...'; irm https://.../product_agent/download/setup | iex
#
# Script tu lam: kiem Claude Code (cai + dang nhap), kiem Python, tai agent tu Odoo,
# hoi ma cai dat, ghi agent.yaml, dang ky chay cung Windows, khoi dong agent.
# Khong can quyen admin. Chay lai dung lenh nay = cap nhat agent. Prompt va quy tac dat
# ten sua tren Odoo, agent tu tai ve - khong can chay lai script.

$ErrorActionPreference = 'Stop'
$BaseDir   = 'C:\hlv_product_agent'
$AgentDir  = "$BaseDir\agent"
$YamlPath  = "$BaseDir\agent.yaml"
$LogFile   = "$BaseDir\agent.log"
$TaskName  = 'HLV Product Agent'
$PythonEmbedUrl  = 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip'
$ClaudeInstaller = 'https://claude.ai/install.ps1'

function Write-Step($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "   [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "   [!] $msg" -ForegroundColor Yellow }
function Write-Bad($msg)  { Write-Host "   [X] $msg" -ForegroundColor Red }

# PowerShell 5.1 bien stderr cua file exe thanh loi terminating khi
# ErrorActionPreference = Stop. Moi lenh exe phai di qua day, dung goi thang.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out  = & $Exe @Arguments 2>&1 | Out-String
        $code = $LASTEXITCODE
        return @{ code = $code; out = $out }
    } catch {
        # Khong tim thay chuong trinh la loi o tang tim lenh; chay bang "irm | iex"
        # thi mot loi nem ra la chet ca script.
        return @{ code = 9009; out = $_.Exception.Message }
    } finally { $ErrorActionPreference = $prev }
}

function Invoke-OdooJson {
    param([string]$Path, [hashtable]$Params)
    $body = @{ jsonrpc = '2.0'; method = 'call'; params = $Params } | ConvertTo-Json -Depth 5
    $resp = Invoke-RestMethod -Uri "$OdooUrl$Path" -Method Post -ContentType 'application/json' -Body $body
    return $resp.result
}

Write-Host "=================================================================="
Write-Host " Cai dat agent tro ly tao ma hang (Claude)" -ForegroundColor White
Write-Host "=================================================================="

# --- 1. Dia chi Odoo -------------------------------------------------------
$OdooUrl = $env:HLV_ODOO_URL
if (-not $OdooUrl) { $OdooUrl = Read-Host "`nDia chi Odoo (vi du https://hoanglongvu.odoo.com)" }
$OdooUrl = $OdooUrl.TrimEnd('/')

# --- 2. Claude Code --------------------------------------------------------
# Cung thu tu tim voi agent (find_claude): PATH -> ~/.local/bin -> ban di kem
# extension VS Code. Ban VS Code doi thu muc moi lan extension cap nhat; agent tu tim
# lai moi luot nen van chay, nhung go VS Code la agent mat Claude.
function Find-Claude {
    $cmd = Get-Command claude -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return @{ path = $cmd.Source; bundled = $false } }
    $native = "$env:USERPROFILE\.local\bin\claude.exe"
    if (Test-Path $native) { return @{ path = $native; bundled = $false } }
    $ext = Get-ChildItem "$env:USERPROFILE\.vscode\extensions\anthropic.claude-code-*\resources\native-binary\claude.exe" `
               -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($ext) { return @{ path = $ext.FullName; bundled = $true } }
    return $null
}

function Install-ClaudeNative {
    Write-Step "Cai Claude Code ban rieng (trinh cai chinh thuc cua Anthropic)"
    # Chay trong tien trinh con: script cai cua Anthropic co the 'exit', khong duoc
    # de no dong luon script nay.
    $r = Invoke-Native 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
                                          "irm $ClaudeInstaller | iex")
    if ($r.code -ne 0) { Write-Bad "Cai Claude Code loi:"; Write-Host $r.out }
}

Write-Step "Kiem tra Claude Code"
$claude = Find-Claude
if (-not $claude) {
    Write-Warn2 "May chua co Claude Code."
    $ans = Read-Host "   Cai Claude Code ngay bay gio? (y/n)"
    if ($ans -ne 'y') { Write-Bad "Can Claude Code de chay agent."; exit 1 }
    Install-ClaudeNative
    $claude = Find-Claude
    if (-not $claude) { Write-Bad "Van khong thay claude.exe sau khi cai."; exit 1 }
} elseif ($claude.bundled) {
    Write-Warn2 "Chi co Claude di kem extension VS Code: $($claude.path)"
    Write-Warn2 "Go VS Code hoac extension la agent mat Claude."
    $ans = Read-Host "   Cai them Claude Code ban rieng cho chac? (y/n, Enter = n)"
    if ($ans -eq 'y') {
        Install-ClaudeNative
        $claude = Find-Claude
    }
}
$ClaudeExe = $claude.path
Write-Ok $ClaudeExe

# Agent chay duoi CHINH tai khoan Windows nay va dung dang nhap Claude cua no
# (luu trong %USERPROFILE%\.claude). Chua dang nhap thi moi luot chat deu loi.
function Test-ClaudeLogin {
    $r = Invoke-Native $ClaudeExe @('auth', 'status')
    return ($r.out -match '"loggedIn"\s*:\s*true')
}

if (-not (Test-ClaudeLogin)) {
    Write-Warn2 "Claude Code chua dang nhap tren tai khoan Windows nay ($env:USERNAME)."
    Write-Host "   Trinh duyet se mo trang dang nhap Anthropic. Dang nhap bang tai khoan" -ForegroundColor White
    Write-Host "   cong ty - luot dung cua tro ly tinh vao tai khoan nay." -ForegroundColor White
    Read-Host "   Enter de mo trang dang nhap"
    & $ClaudeExe auth login
    if (-not (Test-ClaudeLogin)) { Write-Bad "Chua dang nhap duoc Claude. Chay lai script sau khi dang nhap."; exit 1 }
}
$status = (Invoke-Native $ClaudeExe @('auth', 'status')).out
$who = if ($status -match '"email"\s*:\s*"([^"]+)"') { $Matches[1] } else { '?' }
Write-Ok "Da dang nhap: $who"

# --- 3. Python -------------------------------------------------------------
# Giong agent ghi hinh: uu tien Python san co, khong xai duoc thi tai ban NHUNG ve
# thang thu muc agent - khong cai gi vao may, khong can admin, khong dung PATH.
function Initialize-EmbeddedPython {
    $dir = "$BaseDir\python"
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

    $r = Invoke-Native $exe @('-m','pip','install','--quiet','--no-warn-script-location','requests','pyyaml')
    if ($r.code -ne 0) { Write-Bad "Khong cai duoc thu vien:"; Write-Host $r.out; exit 1 }
    Write-Ok "Python nhung san sang"
    return $exe
}

# Tra ve duong dan python.exe dung duoc, hoac $null.
function Resolve-SystemPython {
    foreach ($cmd in @('python', 'python3', 'py')) {
        $found = Get-Command $cmd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $found) { continue }
        # Bo qua bi danh Microsoft Store: goi vao chi mo Store chu khong chay Python.
        if ($found.Source -like '*\WindowsApps\*') { continue }
        $r = Invoke-Native $found.Source @('--version')
        if ($r.code -eq 0 -and $r.out -match 'Python\s+3\.(\d+)' -and [int]$Matches[1] -ge 10) {
            Write-Ok $r.out.Trim()
            return $found.Source
        }
    }
    return $null
}

Write-Step "Kiem tra Python"
$python = Resolve-SystemPython
if ($python) {
    $pyw = Join-Path (Split-Path $python) 'pythonw.exe'
    $r = Invoke-Native $python @('-m','pip','install','--quiet','--no-warn-script-location','requests','pyyaml')
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
    Write-Warn2 "May chua co Python 3.10+ - se dung ban nhung."
}
if (-not $python) { $python = Initialize-EmbeddedPython }

# --- 4. Tai agent tu Odoo --------------------------------------------------
# Dung agent cu truoc khi thay file: tien trinh dang chay van giu code cu trong bo
# nho, khong khoi dong lai thi cap nhat nhu khong.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Step "Dung agent dang chay de cap nhat"
    Write-Warn2 "Luot chat dang xu ly (neu co) se bi ngat; Odoo tu bao sale gui lai."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

Write-Step "Tai agent tu Odoo"
New-Item -ItemType Directory -Force -Path $BaseDir, $AgentDir | Out-Null
# Ban cu tai prompt ve may; gio prompt sua tren Odoo, agent tu tai. Xoa cho khoi nham.
Remove-Item -Recurse -Force "$AgentDir\prompt" -ErrorAction SilentlyContinue
$manifest = (Invoke-WebRequest -Uri "$OdooUrl/product_agent/download/manifest" -UseBasicParsing).Content
foreach ($line in ($manifest -split "`n" | Where-Object { $_.Trim() })) {
    $key, $target = $line.Trim() -split '\s+', 2
    $dest = Join-Path $AgentDir ($target -replace '/', '\')
    # Tai qua file tam roi moi thay: tai hong giua chung khong de lai file cut.
    Invoke-WebRequest -Uri "$OdooUrl/product_agent/download/$key" -OutFile "$dest.part" -UseBasicParsing
    Move-Item -Force "$dest.part" $dest
    Write-Ok $target
}

# --- 5. Token: dung lai cai cu, hoac doi ma cai dat ------------------------
$token = $null
$oldModel = $null
if (Test-Path $YamlPath) {
    $old = Get-Content $YamlPath -Raw -Encoding UTF8
    if ($old -match 'model:\s*"([^"]+)"') { $oldModel = $Matches[1] }
    if ($old -match 'token:\s*"([^"]+)"') {
        $check = Invoke-OdooJson '/product_agent/agent/poll' @{
            token = $Matches[1]; agent_version = 'setup'; max_jobs = 0 }
        if ($check.ok) { $token = $Matches[1]; Write-Step "Dung lai token cu (van con hieu luc)" }
        else { Write-Warn2 "Token trong agent.yaml cu khong con dung, phai xin ma cai dat moi." }
    }
}

if (-not $token) {
    Write-Step "Lay token tu Odoo"
    Write-Host "   Odoo: Ton kho > Cau hinh > Tro ly tao ma hang > May chay Claude"
    Write-Host "   Mo dong cua may nay, bam 'Tao ma cai dat'."
    for ($i = 1; $i -le 3; $i++) {
        $code = Read-Host "`n   Ma cai dat (dang XXXX-XXXX)"
        $resp = Invoke-OdooJson '/product_agent/enroll' @{ code = $code }
        if ($resp.ok) { $token = $resp.token; Write-Ok "May: $($resp.agent_name)"; break }
        Write-Warn2 $resp.error
    }
    if (-not $token) { Write-Bad "Het luot thu. Tao ma moi trong Odoo roi chay lai."; exit 1 }
}

# --- 6. Ghi agent.yaml -----------------------------------------------------
Write-Step "Ghi cau hinh"
$model = if ($oldModel) { $oldModel } else { 'sonnet' }
$yaml = @(
    "# Sinh tu dong boi setup.ps1 - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    "# Chua token Odoo. Dung chep di noi khac. Chay lai setup.ps1 se ghi de file nay"
    "# (giu nguyen model)."
    ""
    "odoo_url: `"$OdooUrl`""
    "token: `"$token`""
    "model: `"$model`""
    "work_dir: `"$($BaseDir -replace '\\', '/')`""
    "max_parallel: 2"
    "turn_timeout_seconds: 300"
    "claude_path: `"`""
)
# UTF-8 KHONG BOM: PyYAML doc duoc ca hai, nhung Set-Content -Encoding utf8 cua
# PowerShell 5.1 them BOM, de tranh bat ngo thi ghi bang .NET.
[System.IO.File]::WriteAllText($YamlPath, ($yaml -join "`r`n") + "`r`n", (New-Object System.Text.UTF8Encoding $false))
Write-Ok "$YamlPath (model: $model)"

# --- 7. Kiem thu truoc khi dang ky -----------------------------------------
Write-Step "Kiem agent"
$r = Invoke-Native $python @("$AgentDir\hlv_product_agent.py", '--config', $YamlPath, '--check')
if ($r.code -ne 0 -or $r.out -notmatch 'Odoo: OK' -or $r.out -match 'Prompt: LOI') {
    Write-Bad "Agent kiem khong qua:"; Write-Host $r.out; exit 1
}
Write-Ok "Agent doc duoc cau hinh, tim thay Claude, Odoo nhan token, tai duoc prompt"

Write-Step "Thu mot cau hoi voi Claude (khoang 10 giay)"
$pingDir = "$BaseDir\sessions\_setup_check"
New-Item -ItemType Directory -Force -Path $pingDir | Out-Null
Push-Location $pingDir
try {
    $r = Invoke-Native $ClaudeExe @('-p', 'Tra loi dung mot tu: OK', '--output-format', 'json',
                                    '--restricted', '--strict-mcp-config', '--disable-slash-commands',
                                    '--permission-mode', 'dontAsk', '--no-session-persistence',
                                    '--model', $model)
} finally { Pop-Location }
if ($r.out -match '"is_error"\s*:\s*false') {
    Write-Ok "Claude tra loi binh thuong"
} else {
    Write-Bad "Claude chua tra loi duoc (het han muc? model '$model' khong dung duoc?):"
    Write-Host ($r.out.Trim() | Select-Object -First 1)
    Write-Warn2 "Van tiep tuc cai, nhung khung chat se bao loi toi khi sua duoc."
}

# --- 8. Chay cung Windows --------------------------------------------------
Write-Step "Dang ky chay ngam cung Windows"
# pythonw.exe: khong bung cua so console. Log ra agent.log.
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) {
    $pythonw = $python
    Write-Warn2 "Khong thay pythonw.exe - agent se chay kem mot cua so console."
}

$taskArgs = "`"$AgentDir\hlv_product_agent.py`" --config `"$YamlPath`""
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $taskArgs -WorkingDirectory $BaseDir
# MultipleInstances=IgnoreNew bien trigger lap thanh canh gac: cu 5 phut Windows thu
# chay lai, agent con song thi lan moi bi bo qua, chet thi duoc bat len.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries -StartWhenAvailable `
                -MultipleInstances IgnoreNew `
                -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
                -ExecutionTimeLimit ([TimeSpan]::Zero)
$tWatchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
                 -RepetitionInterval (New-TimeSpan -Minutes 5)

# KHONG chay duoi SYSTEM nhu agent ghi hinh: dang nhap Claude nam trong ho so cua
# tai khoan nay, SYSTEM khong co. Phai khai ro -User va -RunLevel Limited, thieu la
# Register-ScheduledTask doi quyen admin.
$me = "$env:USERDOMAIN\$env:USERNAME"
$registered = $false
try {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        # -Force khong du de ghi de tac vu do phien quyen cao hon tao: phai xoa truoc.
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    }
    Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger @((New-ScheduledTaskTrigger -AtLogOn -User $me), $tWatchdog) `
        -Settings $settings -User $me -RunLevel Limited | Out-Null
    $registered = $true
    Write-Ok "Chay khi $me dang nhap Windows, tu bat lai trong vong 5 phut neu bi tat"
} catch {
    Write-Bad "KHONG dang ky duoc tac vu '$TaskName': $($_.Exception.Message)"
    Write-Warn2 "Tac vu cu co the do PowerShell (Admin) tao. Mo PowerShell (Admin), chay:"
    Write-Host "     Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false" -ForegroundColor White
    Write-Warn2 "roi dan lai lenh cai o PowerShell THUONG."
}

Write-Step "Khoi dong agent"
if ($registered) {
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 6
    if (Test-Path $LogFile) {
        $tail = Get-Content $LogFile -Tail 3 -Encoding UTF8
        if ($tail -match 'Odoo t') {
            Write-Bad "Odoo tu choi agent - kiem lai token"
            $tail | ForEach-Object { Write-Host "     $_" }
        } else {
            Write-Ok "Agent dang chay ngam (khong co cua so)"
        }
    } else {
        Write-Warn2 "Chua thay agent.log - xem lai bang lenh chay tay o cuoi."
    }
}

# --- 9. Xong ---------------------------------------------------------------
Write-Host "`n=================================================================="
Write-Host " XONG" -ForegroundColor Green
Write-Host "=================================================================="
Write-Host @"

Kiem tra:
  - Odoo > May chay Claude > "Tinh trang" phai la "Dang chay"
  - Mo $OdooUrl/search_stock, bam nut "Tao ma hang" goc trai duoi.
  - Log:  Get-Content $LogFile -Tail 20 -Wait -Encoding UTF8

Chay tay de xem log truc tiep:
  Stop-ScheduledTask -TaskName "$TaskName"
  & "$python" "$AgentDir\hlv_product_agent.py" --config "$YamlPath"

Dung han agent:
  Stop-ScheduledTask    -TaskName "$TaskName"
  Disable-ScheduledTask -TaskName "$TaskName"

Doi model (sonnet / opus): sua dong model trong $YamlPath roi
  Stop-ScheduledTask -TaskName "$TaskName"; Start-ScheduledTask -TaskName "$TaskName"

"@ -ForegroundColor White
