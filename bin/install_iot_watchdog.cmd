@echo off
:: =====================================================================================
::  install_iot_watchdog.cmd — BAM DOI VAO FILE NAY de cai watchdog + in tu dong len
::  MAY KHO (may Windows noi may in, dang chay service Odoo IoT).
:: =====================================================================================
::  Chi la vo boc: no goi install_iot_watchdog.ps1 nam cung thu muc. Can file .cmd nay vi
::  Windows khong cho bam doi chay thang .ps1, va mac dinh chan script chua ky
::  (ExecutionPolicy) — o day mo khoa dung cho mot lan chay, khong doi cai dat cua may.
::
::  Script .ps1 tu xin quyen Administrator, khong can bam chuot phai "Run as administrator".
:: =====================================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_iot_watchdog.ps1" %*
