' =====================================================================================
'  run_watchdog_hidden.vbs - Chay iot_watchdog_windows.ps1 HOAN TOAN AN
' =====================================================================================
'  Van de: neu Task Scheduler goi thang powershell.exe thi cua so console nhay len moi
'  lan chay (2 phut/lan) -> khong lam viec gi khac duoc tren may kho.
'  File nay dung WScript.Shell.Run voi window style = 0 => KHONG co cua so nao hien ra,
'  ke ca nhay 1 giay. Popup canh bao van hien binh thuong vi tien trinh chay trong dung
'  phien dang nhap cua nguoi dung (khac voi chay duoi SYSTEM la khong hien popup duoc).
'
'  Cach dung (tham so truyen vao se day nguyen sang script PowerShell):
'    wscript.exe C:\hlv\run_watchdog_hidden.vbs -LoopSeconds 120
'    wscript.exe C:\hlv\run_watchdog_hidden.vbs            ' mac dinh -LoopSeconds 120
'
'  Dat trong Task Scheduler (chay moi 10 phut de tu hoi sinh neu tien trinh cu chet;
'  script PowerShell co mutex chong chay trung nen khong bao gio co 2 tien trinh):
'    schtasks /Create /TN "HLV IoT Watchdog" /SC MINUTE /MO 10 /RL HIGHEST /IT /F ^
'      /TR "wscript.exe C:\hlv\run_watchdog_hidden.vbs -LoopSeconds 120"
'
'  Luu y: file .vbs nay phai nam CUNG THU MUC voi iot_watchdog_windows.ps1.
' =====================================================================================

Option Explicit

Dim fso, sh, scriptDir, ps1Path, extraArgs, i, cmd

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1Path = scriptDir & "\iot_watchdog_windows.ps1"

If Not fso.FileExists(ps1Path) Then
    ' Truong hop nay chi xay ra khi copy thieu file - bao ro thay vi im lang.
    MsgBox "Khong tim thay file: " & ps1Path, 16, "HLV IoT Watchdog"
    WScript.Quit 1
End If

extraArgs = ""
For i = 0 To WScript.Arguments.Count - 1
    extraArgs = extraArgs & " " & WScript.Arguments(i)
Next
If Len(Trim(extraArgs)) = 0 Then
    extraArgs = " -LoopSeconds 120"
End If

cmd = "powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File """ & ps1Path & """" & extraArgs

' 0 = an cua so hoan toan; False = khong cho doi tien trinh ket thuc.
sh.Run cmd, 0, False
