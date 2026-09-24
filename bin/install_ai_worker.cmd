@echo off
:: =====================================================================================
::  install_ai_worker.cmd — BAM DOI VAO FILE NAY de cai worker AI len may.
:: =====================================================================================
::  Chi la vo boc: no goi install_ai_worker.ps1 nam cung thu muc. Can file .cmd nay vi
::  Windows khong cho bam doi chay thang file .ps1, va mac dinh con chan script chua ky
::  (ExecutionPolicy) — o day mo khoa dung cho mot lan chay, khong doi cai dat cua may.
::
::  Khong can quyen Administrator.
:: =====================================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_ai_worker.ps1" %*
