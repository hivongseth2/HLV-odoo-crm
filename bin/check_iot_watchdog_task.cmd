@echo off
setlocal
chcp 65001 >nul 2>&1
:: =====================================================================================
::  check_iot_watchdog_task.cmd — CHAY TREN MAY CHU KHO (may Windows noi may in).
:: =====================================================================================
::  Tra loi dung mot cau hoi: may nay da chay tac vu dinh ky watchdog chua, va no co
::  dang song khong.
::
::  Chay: bam doi vao file, hoac mo cmd roi go duong dan toi file nay.
::  Khong can quyen Administrator de XEM (chi can quyen do neu muon tao/sua tac vu).
::
::  DUNG DAN NOI DUNG FILE NAY VAO CMD. Batch co label (:phan_3) va khoi ngoac, dan tung
::  dong vao cmd tuong tac se hong: '@echo off' mat tac dung, va '%%F' bao loi
::  "%%F was unexpected at this time" (go truc tiep thi phai la %F, trong file moi la %%F).
::  Muon dan mot phat thi dung dong duoi day thay vi ca file:
::
::    schtasks /Query /TN "HLV IoT Watchdog" /FO LIST /V & sc query odoo-server-18.0 | findstr /I "STATE" & powershell -NoProfile -Command "Get-Content 'C:\ProgramData\HLV\iot_watchdog.log' -Tail 5"
::
::  Kiem 4 thu, theo thu tu tu goc ra ngon:
::    1. Tac vu dinh ky co ton tai khong          (schtasks)
::    2. Chi tiet tac vu: lan chay cuoi, ket qua  (schtasks /V)
::    3. Service Odoo IoT co dang Running khong   (sc query)
::    4. File log co moi khong                    (dir + 8 dong cuoi)
::
::  Chu y ve tieng Viet: file nay co dau va dat chcp 65001. Neu console cua may hien
::  chu loi font thi ket qua van dung, chi la hien thi xau — doc phan tieng Anh cua
::  schtasks/sc la du.
:: =====================================================================================

set "TEN_TAC_VU=HLV IoT Watchdog"
set "TEN_SERVICE=odoo-server-18.0"
set "FILE_LOG=C:\ProgramData\HLV\iot_watchdog.log"

echo(
echo ====================================================================
echo   KIEM TRA WATCHDOG TREN MAY NAY
echo   May: %COMPUTERNAME%   Luc: %DATE% %TIME%
echo ====================================================================

echo(
echo [1] Tac vu dinh ky "%TEN_TAC_VU%" co ton tai khong?
echo --------------------------------------------------------------------
schtasks /Query /TN "%TEN_TAC_VU%" >nul 2>&1
if errorlevel 1 (
    echo   KET QUA: CHUA TAO TAC VU  ^<-- watchdog chua duoc khoi chay tren may nay.
    echo(
    echo   Tao bang lenh sau ^(mo cmd/PowerShell bang quyen Administrator,
    echo   doi token va ma kho cho dung^):
    echo(
    echo     schtasks /Create /TN "%TEN_TAC_VU%" /SC MINUTE /MO 2 /RU SYSTEM /RL HIGHEST /F ^^
    echo       /TR "powershell -ExecutionPolicy Bypass -NoProfile -File C:\hlv\iot_watchdog_windows.ps1 -OdooUrl https://hoanglongvu.odoo.com -Token DAN_TOKEN_VAO_DAY -WarehouseCode KBC -AutoRestart"
    echo(
    goto :phan_3
)
echo   KET QUA: DA CO TAC VU.

echo(
echo [2] Chi tiet tac vu ^(xem Status / Last Run Time / Last Result / Next Run Time^)
echo --------------------------------------------------------------------
schtasks /Query /TN "%TEN_TAC_VU%" /FO LIST /V
echo(
echo   Cach doc:
echo     Status / Trang thai   : Ready = san sang, Running = dang chay, Disabled = BI TAT.
echo     Last Run Time         : rong hoac qua cu = tac vu co ma KHONG chay.
echo     Last Result           : 0 la chay xong khong loi. Khac 0 la lan chay cuoi bi loi
echo                             ^(267011 nghia la chua chay lan nao^).
echo     Next Run Time         : lan chay ke tiep. Rong ma Status=Ready la lich bi hong.

:phan_3
echo(
echo [3] Service Odoo IoT "%TEN_SERVICE%"
echo --------------------------------------------------------------------
sc query "%TEN_SERVICE%" 2>nul | findstr /I "SERVICE_NAME STATE"
if errorlevel 1 (
    echo   KHONG THAY SERVICE nay tren may. Kiem lai ten trong services.msc roi sua
    echo   bien TEN_SERVICE o dau file nay va trong tham so -ServiceName cua tac vu.
)

echo(
echo [4] File log "%FILE_LOG%"
echo --------------------------------------------------------------------
if not exist "%FILE_LOG%" (
    echo   CHUA CO FILE LOG  ^<-- script watchdog chua chay lan nao tren may nay.
    goto :ket_luan
)
echo   Lan ghi cuoi cung:
for %%F in ("%FILE_LOG%") do echo     %%~tF     ^(kich thuoc %%~zF bytes^)
echo(
echo   8 dong cuoi cua log:
powershell -NoProfile -Command "Get-Content -LiteralPath '%FILE_LOG%' -Tail 8" 2>nul
if errorlevel 1 (
    echo     ^(khong doc duoc bang PowerShell, mo file bang Notepad de xem^)
)

:ket_luan
echo(
echo ====================================================================
echo   KET LUAN
echo ====================================================================
echo   Watchdog dang chay dung khi CA BA dieu sau cung dung:
echo     - Phan [1] bao DA CO TAC VU
echo     - Phan [2] Status=Ready ^(hoac Running^), Last Result=0, va Last Run Time
echo       cach day khong qua vai phut
echo     - Phan [4] thoi diem ghi log cuoi cach day khong qua vai phut
echo(
echo   Thieu bat ky dieu nao thi Odoo se coi may nay la mat tin hieu va gui canh bao
echo   "MAY IN IoT KHO ... CO SU CO" sau so phut cau hinh o Settings.
echo(
echo   Doi chieu them tu phia Odoo: Kho hang ^> kho tuong ung ^> field
echo   "Watchdog: lan cuoi nhan tin hieu" phai khop voi gio o phan [4].
echo(
pause
endlocal
