# -*- coding: utf-8 -*-
import logging
import os
import re
import time
import pytz
from collections import defaultdict
from markupsafe import Markup
from odoo import http
from odoo.http import request
from .picking_export_helper import build_picking_summary_xlsx

_SKIP_MSG_RE = re.compile(
    r'Lệnh chuyển hàng được tạo'
    r'|lệnh chuyển hàng đã được tạo ra từ'
    r'|Đồng bộ \(xoá .{0,5} tạo lại\) thành công'
    r'|This transfer has been created from'
    r'|Transfer created'
    r'|Sales Order created'
    r'|Quotation created'
    r'|has been created from'
    r'|Đơn hàng được tạo',
    re.IGNORECASE
)

_logger = logging.getLogger(__name__)

SESSION_KEY_OK = "inv_pw_ok"
PW_PARAM_KEY = "website_public_inventory_18.search_password"

_FAIL_LOG = defaultdict(list)
_RL_MAX = 5
_RL_WINDOW = 600

_ALLOWED_CHAT_ATTACHMENT_MIMES = {
  'application/msword',
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'text/csv',
}
_ALLOWED_CHAT_ATTACHMENT_EXTS = {'.doc', '.docx', '.pdf', '.xls', '.xlsx', '.csv'}
_ALLOWED_CHAT_MEDIA_EXTS = {
  '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic', '.heif',
  '.jfif', '.svg', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.3gp'
}
_MAX_CHAT_ATTACHMENT_BYTES = 20 * 1024 * 1024


def _is_rate_limited(ip):
    now = time.time()
    recent = [t for t in _FAIL_LOG[ip] if now - t < _RL_WINDOW]
    _FAIL_LOG[ip] = recent
    return len(recent) >= _RL_MAX


def _record_failure(ip):
    _FAIL_LOG[ip].append(time.time())


def _is_allowed_chat_attachment(name, mimetype):
  mt = (mimetype or '').lower()
  if mt.startswith('image/') or mt.startswith('video/'):
    return True
  if mt in _ALLOWED_CHAT_ATTACHMENT_MIMES:
    return True
  ext = os.path.splitext(name or '')[1].lower()
  if ext in _ALLOWED_CHAT_ATTACHMENT_EXTS:
    return True
  return ext in _ALLOWED_CHAT_MEDIA_EXTS


def _normalize_preview_text(text, limit=140):
  plain = re.sub(r'<[^>]+>', ' ', text or '')
  plain = re.sub(r'\s+', ' ', plain).strip()
  if not plain:
    return ''
  return plain[:limit] + ('...' if len(plain) > limit else '')


_H = [
    ("Content-Type", "text/html; charset=utf-8"),
    # Chống browser/proxy cache nguyên trang HTML chứa inline JS.
    # Nếu thiếu, sau khi server cập nhật _PAGE, client cũ chạy JS lệch
    # với backend → search "không ra" cho đến khi user Ctrl+F5.
    ("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"),
    ("Pragma", "no-cache"),
    ("Expires", "0"),
]

_ERR_PW = '<div class="alert alert-danger mb-3">Mật khẩu không đúng.</div>'
_ERR_RATE = '<div class="alert alert-danger mb-3">Quá nhiều lần thử sai. Vui lòng thử lại sau 10 phút.</div>'

_LOGIN = """<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"/>
<title>Tình trạng Đơn hàng</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
</head>
<body class="bg-light d-flex align-items-center justify-content-center" style="min-height:100vh">
<div class="card shadow p-4" style="max-width:400px;width:100%;border-radius:4px">
  <h4 class="fw-bold text-center text-primary mb-3">&#128666; Tình trạng Đơn hàng</h4>
  {err}
  <form method="post" action="/sale_plan">
    <input type="hidden" name="csrf_token" value="{csrf}"/>
    <label class="form-label fw-bold">Mật khẩu</label>
    <input type="password" name="inv_password" class="form-control form-control-lg mb-3" autofocus required/>
    <button type="submit" class="btn btn-primary w-100 btn-lg">Xác nhận</button>
  </form>
</div></body></html>"""

_PAGE = r"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"/>
<title>Tình trạng đơn hàng</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
*{box-sizing:border-box}
body{font-family:'Inter',system-ui,-apple-system,sans-serif;background:#f7f8f9;color:#0f172a;-webkit-font-smoothing:antialiased;font-size:14px}
.card,.form-control,.form-select,.badge,.list-group-item,.alert,.modal-content,
.input-group-text,.dropdown-menu{border-radius:3px!important}
/* Navbar */
.navbar.bg-primary{background:#0f172a!important;border-bottom:1px solid #1e293b}
/* KPI row 1 */
.kpi-main{padding:16px 18px;color:#fff;position:relative;overflow:hidden;border:0;transition:.2s;box-shadow:none}
.kpi-main:hover{transform:translateY(-1px);box-shadow:0 4px 14px rgba(0,0,0,.15)}
.kpi-main .kpi-icon{position:absolute;right:14px;top:50%;transform:translateY(-50%);font-size:2rem;opacity:.18}
.kpi-main .kpi-label{font-size:.68rem;text-transform:uppercase;font-weight:600;letter-spacing:.6px;opacity:.8}
.kpi-main .kpi-val{font-size:1.85rem;font-weight:800;line-height:1.1;letter-spacing:-.025em}
.kpi-bg-total{background:#1e293b}
.kpi-bg-ready{background:#16a34a}
.kpi-bg-partial{background:#d97706}
.kpi-bg-out{background:#dc2626}
/* KPI row 2 */
.kpi-pack{padding:11px 13px;border:1px solid #e5e7eb;cursor:pointer;transition:.15s;display:flex;align-items:center;gap:11px;background:#fff;box-shadow:none}
.kpi-pack:hover{border-color:#a5b4fc;box-shadow:0 0 0 3px rgba(99,102,241,.08)}
.kpi-pack.active{border-color:#6366f1;box-shadow:0 0 0 3px rgba(99,102,241,.12);background:#faf5ff}
.kpi-pack-icon{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:.9rem;flex-shrink:0}
.kpi-pack .kpi-pack-label{font-size:.68rem;color:#6b7280;text-transform:uppercase;font-weight:600;letter-spacing:.5px}
.kpi-pack .kpi-pack-val{justify-content:center;align-items:center;text-align:center;width:100%;font-size:1.45rem;font-weight:700;line-height:1.2;color:#111827;letter-spacing:-.02em}
/* Badges — Linear-style minimal status chips with dot */
.badge-del-pending,.badge-del-partial,.badge-del-full,
.badge-stk-ready,.badge-stk-partial,.badge-stk-out,
.badge-pack-waiting,.badge-pack-unpacked,.badge-pack-printed,
.badge-pack-packed,.badge-pack-deltoday,.badge-pack-shipping,.badge-pack-done,
.badge-po-pending,.badge-po-partial,.badge-po-full{
  display:inline-flex;align-items:center;gap:4px;font-size:.68rem;font-weight:600;
  padding:2px 7px 2px 5px;border-radius:20px;letter-spacing:.15px;line-height:1.4}
/* Dot via ::before */
.badge-del-pending::before,.badge-pack-waiting::before,.badge-po-pending::before,
.badge-del-partial::before,.badge-stk-partial::before,.badge-pack-unpacked::before,
.badge-del-full::before,.badge-stk-ready::before,.badge-pack-done::before,
.badge-pack-shipping::before,.badge-po-full::before,
.badge-stk-out::before,
.badge-pack-printed::before,.badge-po-partial::before,
.badge-pack-packed::before,
.badge-pack-deltoday::before{content:'';width:6px;height:6px;border-radius:50%;flex-shrink:0}
/* Grey — pending/waiting */
.badge-del-pending,.badge-pack-waiting,.badge-po-pending{color:#6b7280;background:#f3f4f6;border:1px solid #e5e7eb}
.badge-del-pending::before,.badge-pack-waiting::before,.badge-po-pending::before{background:#9ca3af}
/* Amber — partial */
.badge-del-partial,.badge-stk-partial,.badge-pack-unpacked{color:#92400e;background:#fffbeb;border:1px solid #fde68a}
.badge-del-partial::before,.badge-stk-partial::before,.badge-pack-unpacked::before{background:#f59e0b}
/* Green — full/done/shipping */
.badge-del-full,.badge-stk-ready,.badge-pack-done,.badge-pack-shipping,.badge-po-full{color:#14532d;background:#f0fdf4;border:1px solid #bbf7d0}
.badge-del-full::before,.badge-stk-ready::before,.badge-pack-done::before,.badge-pack-shipping::before,.badge-po-full::before{background:#22c55e}
/* Red — out of stock */
.badge-stk-out{color:#991b1b;background:#fef2f2;border:1px solid #fecaca}
.badge-stk-out::before{background:#ef4444}
/* Sky — printed/po-partial */
.badge-pack-printed,.badge-po-partial{color:#075985;background:#f0f9ff;border:1px solid #bae6fd}
.badge-pack-printed::before,.badge-po-partial::before{background:#38bdf8}
/* Indigo — packed */
.badge-pack-packed{color:#3730a3;background:#eef2ff;border:1px solid #c7d2fe}
.badge-pack-packed::before{background:#818cf8}
/* Teal — delivered today */
.badge-pack-deltoday{color:#155e75;background:#ecfeff;border:1px solid #a5f3fc}
.badge-pack-deltoday::before{background:#22d3ee}
/* Card row highlights */
.so-card-new{background:#fffbeb!important}
.so-card-deltoday{background:#f0f9ff!important}
.so-card-ready{background:#f0fdf4!important}
.cursor-pointer{cursor:pointer}
/* Filter chips */
.filter-chip{font-size:.65rem;padding:3px 7px 3px 9px;display:inline-flex;align-items:center;gap:5px;cursor:default;border-radius:20px}
.filter-chip .chip-x{background:none;border:none;color:inherit;font-size:.9rem;line-height:1;padding:0 2px;cursor:pointer;opacity:.65}
.filter-chip .chip-x:hover{opacity:1}
/* Kanban */
.kanban-col{min-width:278px;max-width:380px;flex:0 1 auto}
.kanban-col .card-header{font-size:.7rem;font-weight:700;letter-spacing:.5px;text-transform:uppercase;background:#fff;border-bottom:1px solid #e5e7eb;color:#374151;padding:9px 12px}
.kanban-wrapper{width:100%;overflow-x:auto;margin-left:-1rem;margin-right:-1rem;padding-left:1rem;padding-right:1rem;-webkit-overflow-scrolling:touch}
#kanban-view{display:flex;flex-wrap:nowrap;gap:.75rem;width:fit-content}
/* SO Cards */
.so-card{border:1px solid #e5e7eb!important;transition:.15s;box-shadow:none!important}
.so-card:hover{border-color:#a5b4fc!important;box-shadow:0 2px 8px rgba(99,102,241,.1)!important}
/* Drawer */
#drawer{position:fixed;top:0;right:-1020px;width:1000px;height:100vh;background:#fff;
  border-left:1px solid #e5e7eb;box-shadow:-8px 0 32px rgba(0,0,0,.06);z-index:1060;transition:right .3s;overflow-y:auto}
#drawer.open{right:0}
#drawer-overlay{display:none;position:fixed;inset:0;background:rgba(15,23,42,.2);z-index:1055}
#drawer-overlay.open{display:block}
/* Drawer table */
.table-lines td,.table-lines th{font-size:.7rem;vertical-align:middle}
.table-lines thead th{background:#f9fafb;color:#6b7280;font-weight:600;text-transform:uppercase;font-size:.65rem;letter-spacing:.6px;padding:9px 8px;border-bottom:1px solid #e5e7eb}
.table-lines td{padding:7px 8px;border-color:#f3f4f6}
.table-lines tbody tr:hover{background:#fafafa}
.table-lines .cell-packed-full{color:#16a34a;font-weight:600}
.table-lines .cell-packed-partial{color:#0891b2;font-weight:600}
.table-lines .cell-packed-zero{color:#d1d5db}
.table-lines .cell-stock-ok{color:#16a34a;font-weight:600}
.table-lines .cell-stock-zero{color:#dc2626}
.table-lines .cell-shortage{color:#dc2626;font-weight:600}
.table-lines .cell-delivered{color:#4f46e5}
.row-pending{background:#fffbeb}
.row-delivered{background:#f0fdf4}
/* Kanban col load more */
.btn-col-more{font-size:.65rem;padding:7px 0;width:100%;background:#fafafa;border:1px dashed #e5e7eb;color:#6b7280;cursor:pointer;transition:.15s;font-weight:500}
.btn-col-more:hover{background:#f3f4f6;border-color:#d1d5db;color:#374151}
/* Loading */
.loading-overlay{position:fixed;inset:0;background:rgba(255,255,255,.8);z-index:2000;
  display:flex;align-items:center;justify-content:center}
.loading-overlay .spinner-border{width:2.5rem;height:2.5rem}
/* Load more */
#btn-load-more{font-weight:600;padding:5px 32px}
@media(max-width:1024px){#drawer{width:100%!important;right:-105%!important}} @media(max-width:768px){.kanban-col{min-width:100%}}
/* Report button */
.btn-report{font-size:.68rem;padding:2px 8px;border:1px solid #fecaca;color:#dc2626;background:#fef2f2;border-radius:4px;cursor:pointer;transition:.15s;line-height:1.4;font-weight:500}
.btn-report:hover{background:#fee2e2;border-color:#dc2626}
/* Report modal */
#report-modal{display:none;position:fixed;inset:0;z-index:2000;background:rgba(0,0,0,.4);align-items:center;justify-content:center}
/* Messages section */
.msg-section{margin-top:16px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden}
.msg-header{padding:10px 14px;background:#fafafa;border-bottom:1px solid #e5e7eb;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:8px;font-weight:600;font-size:.82rem;color:#374151;user-select:none}
.msg-header i.fa-chevron-right{transition:transform .2s;font-size:.65rem;color:#9ca3af}
.msg-header.open i.fa-chevron-right{transform:rotate(90deg)}
.msg-list{max-height:500px;overflow-y:auto;padding:0}
.msg-item{padding:10px 14px;border-bottom:1px solid #f3f4f6;font-size:.8rem}
.msg-item:last-child{border-bottom:none}
.msg-meta{display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap}
.msg-author{font-weight:600;color:#111827}
.msg-date{color:#9ca3af;font-size:.65rem}
.msg-origin{font-size:.65rem;background:#f3f4f6;color:#6b7280;padding:1px 6px;border-radius:4px}
.msg-body{color:#4b5563;line-height:1.55;word-break:break-word}
.msg-body p{margin:0 0 4px}
.msg-body img{max-width:100%;border-radius:4px;margin:4px 0}
.msg-attachments{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.msg-att{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:4px;font-size:.76rem;color:#4b5563;text-decoration:none;transition:.15s}
.msg-att:hover{background:#f3f4f6;border-color:#d1d5db;color:#111827}
.msg-att-img{width:60px;height:60px;object-fit:cover;border-radius:4px;border:1px solid #e5e7eb;cursor:pointer}
.msg-att-img:hover{opacity:.85}
.msg-empty{padding:20px;text-align:center;color:#9ca3af;font-size:.8rem}
.msg-compose-files{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.msg-compose-file{display:inline-flex;align-items:center;gap:6px;padding:3px 8px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:4px;font-size:.65rem;color:#4b5563}
.msg-compose-file button{border:none;background:transparent;color:#dc2626;padding:0;line-height:1}
#report-modal .rmod-card{background:#fff;max-width:440px;width:90%;border-radius:8px;padding:24px;box-shadow:0 8px 24px rgba(0,0,0,.12)}
/* ========================================================
   DRAWER HEADER — remove solid blue, premium white panel
   ======================================================== */
#drawer .bg-primary{background:#fff!important}
#drawer .bg-primary.text-white{color:#0f172a!important}
#drawer .bg-primary *{color:#0f172a!important}
#drawer #dr-title{font-size:1rem;font-weight:700;letter-spacing:-.02em;color:#0f172a!important}
#drawer .bg-primary .btn-light{background:#f1f5f9!important;border:1px solid #e2e8f0!important;color:#475569!important}
#drawer .bg-primary .btn-light:hover{background:#e2e8f0!important}
/* Drawer footer strip */
#dr-footer{background:#f8fafc!important;border-color:#e2e8f0!important;font-size:.88rem;color:#374151}
/* ========================================================
   TABLE — strip yellow/green Bootstrap contextual colors
   ======================================================== */
.table-lines tr.table-warning,.table-lines tr.table-success{
  --bs-table-bg:#fff;--bs-table-color:#0f172a;--bs-table-striped-bg:#fff;background-color:#fff!important}
.table-lines tr.table-warning>*,.table-lines tr.table-success>*{
  background-color:#fff!important;color:#0f172a}
/* ========================================================
   TABLE — remove all vertical borders, hairline rows only
   ======================================================== */
.table-lines.table-bordered{border:0!important}
.table-lines.table-bordered>:not(caption)>*{border-width:0!important}
.table-lines>:not(caption)>*>*{
  border-bottom:1px solid #e2e8f0!important;border-top:0!important;
  border-left:0!important;border-right:0!important}
.table-lines>:not(:first-child){border-top:0!important}
/* ========================================================
   TABLE HEADER — clean SaaS-style <thead>
   ======================================================== */
.table-lines thead.table-light>tr>th,.table-lines .table-light th{
  background:#f8fafc!important;color:#64748b!important;
  font-size:.65rem!important;text-transform:uppercase!important;
  font-weight:600!important;letter-spacing:.5px!important;
  border-bottom:1px solid #e2e8f0!important}
/* ========================================================
   TABLE CELLS — Tailwind-calibrated semantic colors
   ======================================================== */
.table-lines td{color:#0f172a}
/* Subtotal col (text-success fw-bold) → emerald-600 */
.table-lines td.text-success{color:#059669!important}
/* VAT col (text-warning) → amber-700 */
.table-lines td.text-warning{color:#b45309!important}
.text-warning{color:#b45309!important}
/* Total+VAT col (text-primary fw-bold) → indigo-600 */
.table-lines td.text-primary{color:#4f46e5!important}
/* Delivered qty (cell-delivered) → indigo-500 */
.table-lines .cell-delivered{color:#6366f1!important}
/* Stock ok → emerald; zero → rose */
.table-lines .cell-stock-ok{color:#059669!important}
.table-lines .cell-stock-zero{color:#e11d48!important}
/* Shortage → rose-600 */
.table-lines .cell-shortage{color:#e11d48!important;font-weight:700}
/* Packed full → emerald; partial → sky */
.table-lines .cell-packed-full{color:#059669!important}
.table-lines .cell-packed-partial{color:#0284c7!important}
/* Muted text in table */
.table-lines td.text-muted,.table-lines .text-muted.small{color:#64748b!important}
/* ========================================================
   MISC — count badge, alert strip, transfer table
   ======================================================== */
#count-info{background:#1e293b!important;font-size:.65rem!important;padding:5px 12px!important;font-weight:500!important;border-radius:20px!important}
.alert-warning{background:rgba(245,158,11,.05)!important;border:1px solid #fde68a!important;color:#92400e!important}
.alert-warning h6{color:#92400e!important;font-size:.75rem}
.table-lines .badge.bg-warning.text-dark{background:rgba(245,158,11,.12)!important;color:#b45309!important;border:1px solid #fde68a!important;font-weight:600}
.table-lines .badge.bg-info.bg-opacity-25.text-dark{background:rgba(14,165,233,.1)!important;color:#075985!important;border:1px solid #bae6fd!important}
/* Second table (transfer suggestions) */
.table-bordered:not(.table-lines){border:1px solid #e2e8f0!important}
.table-bordered:not(.table-lines) thead.table-light th{background:#f8fafc!important;color:#64748b!important;font-size:.65rem!important;text-transform:uppercase!important;font-weight:600!important;border-color:#e2e8f0!important}
/* ========================================================
   LIQUID GLASS BUTTONS — premium modern style
   ======================================================== */
/* Base — all .btn elements */
.btn{
  border-radius:3px!important;
  font-weight:500;font-size:.82rem;letter-spacing:.01em;
  transition:all .2s cubic-bezier(.4,0,.2,1)!important;
  position:relative;overflow:hidden}
.btn-sm{border-radius:3px!important;font-size:.78rem;padding:5px 13px}
/* btn-group: flatten inner corners, keep outer 3px */
.btn-group>.btn:not(:first-child),.btn-group>.btn-group:not(:first-child)>.btn{
  border-top-left-radius:0!important;border-bottom-left-radius:0!important;margin-left:-1px}
.btn-group>.btn:not(:last-child):not(.dropdown-toggle),.btn-group>.btn-group:not(:last-child)>.btn{
  border-top-right-radius:0!important;border-bottom-right-radius:0!important}
/* Primary — indigo glow */
.btn-primary{
  background:linear-gradient(135deg,#4f46e5 0%,#6366f1 60%,#818cf8 100%)!important;
  border:1px solid rgba(99,102,241,.35)!important;color:#fff!important;
  box-shadow:0 2px 10px rgba(99,102,241,.35),inset 0 1px 0 rgba(255,255,255,.22)!important}
.btn-primary:hover{
  background:linear-gradient(135deg,#4338ca 0%,#4f46e5 60%,#6366f1 100%)!important;
  box-shadow:0 4px 18px rgba(99,102,241,.45),inset 0 1px 0 rgba(255,255,255,.22)!important;
  transform:translateY(-1px)}
.btn-primary:active{transform:translateY(0);box-shadow:0 1px 4px rgba(99,102,241,.3)!important}
/* Outline-primary — glass tab */
.btn-outline-primary{
  background:rgba(238,242,255,.7)!important;
  backdrop-filter:blur(8px) saturate(1.5);
  border:1px solid rgba(99,102,241,.3)!important;color:#4f46e5!important;
  box-shadow:0 1px 4px rgba(99,102,241,.12),inset 0 1px 0 rgba(255,255,255,.8)!important}
.btn-outline-primary:hover{
  background:rgba(238,242,255,.95)!important;
  box-shadow:0 2px 10px rgba(99,102,241,.2),inset 0 1px 0 rgba(255,255,255,.9)!important;
  color:#3730a3!important;transform:translateY(-1px)}
.btn-outline-primary.active,.btn-outline-primary:active{
  background:linear-gradient(135deg,#4f46e5,#6366f1)!important;
  color:#fff!important;border-color:transparent!important;
  box-shadow:0 2px 10px rgba(99,102,241,.35),inset 0 1px 0 rgba(255,255,255,.2)!important}
/* Secondary outline — frosted glass */
.btn-outline-secondary{
  background:rgba(255,255,255,.75)!important;
  backdrop-filter:blur(10px) saturate(1.3);
  border:1px solid #e2e8f0!important;color:#475569!important;
  box-shadow:0 1px 3px rgba(0,0,0,.07),inset 0 1px 0 rgba(255,255,255,.95)!important}
.btn-outline-secondary:hover{
  background:rgba(241,245,249,.95)!important;color:#1e293b!important;
  border-color:#cbd5e1!important;
  box-shadow:0 2px 8px rgba(0,0,0,.1),inset 0 1px 0 rgba(255,255,255,.9)!important;
  transform:translateY(-1px)}
/* Success — emerald glow */
.btn-success{
  background:linear-gradient(135deg,#059669 0%,#10b981 60%,#34d399 100%)!important;
  border:1px solid rgba(5,150,105,.3)!important;color:#fff!important;
  box-shadow:0 2px 10px rgba(5,150,105,.32),inset 0 1px 0 rgba(255,255,255,.22)!important}
.btn-success:hover{
  background:linear-gradient(135deg,#047857 0%,#059669 60%,#10b981 100%)!important;
  box-shadow:0 4px 18px rgba(5,150,105,.42),inset 0 1px 0 rgba(255,255,255,.22)!important;
  color:#fff!important;transform:translateY(-1px)}
/* Warning — amber glow */
.btn-warning{
  background:linear-gradient(135deg,#b45309 0%,#d97706 55%,#f59e0b 100%)!important;
  border:1px solid rgba(180,83,9,.3)!important;color:#fff!important;
  box-shadow:0 2px 10px rgba(217,119,6,.32),inset 0 1px 0 rgba(255,255,255,.2)!important}
.btn-warning:hover{
  background:linear-gradient(135deg,#92400e 0%,#b45309 55%,#d97706 100%)!important;
  box-shadow:0 4px 18px rgba(180,83,9,.4),inset 0 1px 0 rgba(255,255,255,.2)!important;
  color:#fff!important;transform:translateY(-1px)}
/* Info — sky glow */
.btn-info{
  background:linear-gradient(135deg,#0284c7 0%,#0ea5e9 60%,#38bdf8 100%)!important;
  border:1px solid rgba(2,132,199,.3)!important;color:#fff!important;
  box-shadow:0 2px 10px rgba(2,132,199,.3),inset 0 1px 0 rgba(255,255,255,.22)!important}
.btn-info:hover{
  background:linear-gradient(135deg,#0369a1 0%,#0284c7 60%,#0ea5e9 100%)!important;
  box-shadow:0 4px 18px rgba(2,132,199,.4),inset 0 1px 0 rgba(255,255,255,.22)!important;
  color:#fff!important;transform:translateY(-1px)}
/* Danger — rose glow */
.btn-danger{
  background:linear-gradient(135deg,#dc2626 0%,#ef4444 60%,#f87171 100%)!important;
  border:1px solid rgba(220,38,38,.3)!important;color:#fff!important;
  box-shadow:0 2px 10px rgba(220,38,38,.3),inset 0 1px 0 rgba(255,255,255,.18)!important}
.btn-danger:hover{
  background:linear-gradient(135deg,#b91c1c 0%,#dc2626 60%,#ef4444 100%)!important;
  box-shadow:0 4px 18px rgba(220,38,38,.4),inset 0 1px 0 rgba(255,255,255,.18)!important;
  transform:translateY(-1px)}
/* Light — close button & misc */
.btn-light{
  background:rgba(248,250,252,.9)!important;
  backdrop-filter:blur(6px);
  border:1px solid #e2e8f0!important;color:#475569!important;
  box-shadow:0 1px 3px rgba(0,0,0,.06),inset 0 1px 0 rgba(255,255,255,.95)!important}
.btn-light:hover{background:rgba(241,245,249,.95)!important;border-color:#cbd5e1!important}
/* Load-more pill */
#btn-load-more{border-radius:20px!important;padding:5px 18px;font-size:.78rem}
</style>
</head><body>
<div id="loading" class="loading-overlay d-none"><div class="spinner-border text-primary"></div></div>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary mb-3" style="border-radius:0!important">
<div class="container-fluid">
  <a class="navbar-brand fw-bold" href="/sale_plan">&#128666; Tình trạng đơn hàng</a>
  <button class="navbar-toggler" data-bs-toggle="collapse" data-bs-target="#nav1"><span class="navbar-toggler-icon"></span></button>
  <div class="collapse navbar-collapse" id="nav1">
    <ul class="navbar-nav ms-auto">
      <li class="nav-item"><a class="nav-link" href="/search_stock">Tồn kho</a></li>
      <li class="nav-item"><a class="nav-link" href="/search_order">Chứng từ mua</a></li>
      <li class="nav-item"><a class="nav-link active" href="/sale_plan">Tình trạng đơn</a></li>
      <li class="nav-item"><a class="nav-link" href="/search_invoice">Hóa đơn MISA</a></li>
    </ul>
  </div>
</div></nav>
<div class="px-3">
<!-- KPI row 1 -->
<div class="row g-2 mb-2">
  <div class="col-6 col-md-3"><div class="card kpi-main kpi-bg-total"><div class="kpi-label">Đơn hàng</div><div class="kpi-val" id="kpi-total">0</div><i class="fa fa-boxes-stacked kpi-icon"></i></div></div>
  <div class="col-6 col-md-3"><div class="card kpi-main kpi-bg-ready"><div class="kpi-label">Sẵn sàng xuất đủ</div><div class="kpi-val" id="kpi-ready">0</div><i class="fa fa-circle-check kpi-icon"></i></div></div>
  <div class="col-6 col-md-3"><div class="card kpi-main kpi-bg-partial"><div class="kpi-label">Có hàng 1 phần</div><div class="kpi-val" id="kpi-partial">0</div><i class="fa fa-exclamation-circle kpi-icon"></i></div></div>
  <div class="col-6 col-md-3"><div class="card kpi-main kpi-bg-out"><div class="kpi-label">Chưa có hàng / Thiếu</div><div class="kpi-val" id="kpi-outstock">0</div><i class="fa fa-xmark-circle kpi-icon"></i></div></div>
</div>
<!-- KPI row 2 - packing -->
<div class="d-flex flex-wrap gap-2 mb-3">
  <div style="flex:1 1 0;min-width:130px"><div class="card kpi-pack" id="kpi-pack-waiting" data-filter="waiting_stock">
    <div class="kpi-pack-icon" style="background:#fed7d7;color:#c53030"><i class="fa fa-circle-xmark"></i></div>
    <div><div class="kpi-pack-label">Không có hàng đóng</div><div class="kpi-pack-val" id="kpi-pw">0</div></div>
  </div></div>
  <div style="flex:1 1 0;min-width:130px"><div class="card kpi-pack" id="kpi-pack-unpacked" data-filter="unpacked">
    <div class="kpi-pack-icon" style="background:#fefcbf;color:#b7791f"><i class="fa fa-box-open"></i></div>
    <div><div class="kpi-pack-label">Có hàng chưa gói</div><div class="kpi-pack-val" id="kpi-pu">0</div></div>
  </div></div>
  <div style="flex:1 1 0;min-width:130px"><div class="card kpi-pack" id="kpi-pack-printed" data-filter="printed_waiting">
    <div class="kpi-pack-icon" style="background:#d1ecf1;color:#0c5460"><i class="fa fa-print"></i></div>
    <div><div class="kpi-pack-label">Đã in, chờ gói</div><div class="kpi-pack-val" id="kpi-pp">0</div></div>
  </div></div>
  <div style="flex:1 1 0;min-width:130px"><div class="card kpi-pack" id="kpi-pack-done" data-filter="packed_waiting_ship">
    <div class="kpi-pack-icon" style="background:#cce5ff;color:#004085"><i class="fa fa-archive"></i></div>
    <div><div class="kpi-pack-label">Đã gói, chờ giao</div><div class="kpi-pack-val" id="kpi-pf">0</div></div>
  </div></div>
  <div style="flex:1 1 0;min-width:130px"><div class="card kpi-pack" id="kpi-pack-shipping" data-filter="shipping">
    <div class="kpi-pack-icon" style="background:#c6f6d5;color:#276749"><i class="fa fa-truck"></i></div>
    <div><div class="kpi-pack-label">Đang giao</div><div class="kpi-pack-val" id="kpi-ps">0</div></div>
  </div></div>
  <div style="flex:1 1 0;min-width:130px"><div class="card kpi-pack" id="kpi-pack-deltoday" data-filter="delivered_today">
    <div class="kpi-pack-icon" style="background:#d4edda;color:#155724"><i class="fa fa-calendar-check"></i></div>
    <div><div class="kpi-pack-label">Đã giao trong ngày</div><div class="kpi-pack-val" id="kpi-pdt">0</div></div>
  </div></div>
</div>
<!-- Active Filters -->
<div id="active-filters" class="mb-2 d-none d-flex flex-wrap gap-1 align-items-center"></div>
<!-- Filters -->
<div class="card mb-3 shadow-sm" style="border:1px solid #e2e8f0">
<div class="card-body px-4 py-3">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h6 class="mb-0 fw-bold text-muted"><i class="fa fa-sliders me-2"></i>Bộ lọc nâng cao</h6>
    <div class="d-flex gap-2">
      <button id="btn-filter" class="btn btn-primary btn-sm px-4"><i class="fa fa-search me-1"></i>Tìm kiếm</button>
      <button id="btn-refresh" class="btn btn-outline-secondary btn-sm px-3"><i class="fa fa-refresh me-1"></i>Làm mới</button>
    </div>
  </div>
  <div class="row g-3 mb-3">
    <div class="col-md-3"><label class="form-label small fw-semibold text-muted mb-1">Tìm Kiếm</label><input id="f-q" class="form-control form-control-sm" placeholder="SO / Khách hàng..."/></div>
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Kho Cung Cấp</label><select id="f-wh" class="form-select form-select-sm"><option value="all">Tất cả</option></select></div>
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Tiến Độ Giao</label>
      <select id="f-del" class="form-select form-select-sm">
        <option value="pending_partial">Chưa giao &amp; Giao 1 phần</option>
        <option value="all" selected>Tất cả</option><option value="pending">Chưa giao</option>
        <option value="partial">Giao 1 phần</option><option value="full">Đã giao đủ</option>
      </select></div>
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Tình Trạng Kho</label>
      <select id="f-stk" class="form-select form-select-sm">
        <option value="all">Tất cả</option><option value="ready">Đủ hàng</option>
        <option value="partial_ready">Có hàng 1 phần</option><option value="out_of_stock">Không có hàng</option>
      </select></div>
    <div class="col-md-3"><label class="form-label small fw-semibold text-muted mb-1">Đóng Gói</label>
      <select id="f-pack" class="form-select form-select-sm">
        <option value="all">Tất cả</option><option value="waiting_stock">Không có hàng đóng</option>
        <option value="unpacked">Có hàng chưa đóng gói</option>
        <option value="printed_waiting">Đã in, chờ đóng gói</option>
        <option value="packed_waiting_ship">Đã gói, chờ nhận giao</option>
        <option value="shipping">Đang giao</option>
        <option value="delivered_today">Đã giao trong ngày</option>
      </select></div>
  </div>
  <div class="row g-3 mb-3">
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Mã NV MISA</label><input id="f-saler" class="form-control form-control-sm" placeholder="VD: NV001"/></div>
    <div class="col-md-3"><label class="form-label small fw-semibold text-muted mb-1">HTGH <small class="text-secondary fw-normal">(phẩy=OR, !=loại trừ)</small></label>
      <div class="input-group input-group-sm">
        <input id="f-htgh" class="form-control" placeholder="VD: ghn,cpn hoặc !ghn,!j&amp;t"/>
        <button type="button" class="btn btn-outline-secondary" id="btn-htgh-save" title="Lưu làm gợi ý"><i class="fa fa-plus"></i></button>
      </div>
      <div id="htgh-presets" class="mt-1 d-flex flex-wrap gap-1"></div>
    </div>
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Loại vận chuyển</label>
      <select id="f-dtype" class="form-select form-select-sm">
        <option value="all">Tất cả</option>
        <option value="HLV vận chuyển">HLV vận chuyển</option>
        <option value="GHN">GHN</option>
        <option value="J&T">J&amp;T</option>
      </select></div>
    <div class="col-md-3"><label class="form-label small fw-semibold text-muted mb-1">Tag <small class="text-muted fw-normal">(Ctrl+click chọn nhiều)</small></label><select id="f-tag" multiple class="form-select form-select-sm" style="max-height:80px"></select></div>
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Trạng Thái Mua hàng</label>
      <select id="f-po-status" class="form-select form-select-sm">
        <option value="all">Tất cả</option><option value="pending">Chưa nhận hàng</option>
        <option value="partial">Nhận 1 phần</option><option value="full">Đã nhận đủ</option>
      </select></div>
  </div>
  <div class="row g-3 mb-2">
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Hẹn giao từ</label><input type="date" id="f-date-from" class="form-control form-control-sm"/></div>
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Hẹn giao đến</label><input type="date" id="f-date-to" class="form-control form-control-sm"/></div>
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Hoàn thành từ</label><input type="date" id="f-done-from" class="form-control form-control-sm"/></div>
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Hoàn thành đến</label><input type="date" id="f-done-to" class="form-control form-control-sm"/></div>
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Nhận hàng từ</label><input type="date" id="f-po-date-from" class="form-control form-control-sm"/></div>
    <div class="col-md-2"><label class="form-label small fw-semibold text-muted mb-1">Nhận hàng đến</label><input type="date" id="f-po-date-to" class="form-control form-control-sm"/></div>
  </div>
  <div class="d-flex gap-4 pt-1">
    <div class="form-check form-switch">
      <input class="form-check-input" type="checkbox" id="f-need-transfer">
      <label class="form-check-label small fw-bold" for="f-need-transfer"><i class="fa fa-exchange text-danger me-1"></i>Cần chuyển kho</label>
    </div>
    <div class="form-check form-switch">
      <input class="form-check-input" type="checkbox" id="f-show-completed" checked>
      <label class="form-check-label small fw-bold" for="f-show-completed"><i class="fa fa-check-circle text-success me-1"></i>Hiện đơn đã giao</label>
    </div>
  </div>
</div>


</div>
<!-- View toggle -->
<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div class="d-flex gap-1 flex-wrap align-items-center">
    <span class="text-muted small fw-bold me-1"><i class="fa fa-layer-group"></i> PHÂN NHÓM:</span>
    <button id="grp-packing" class="btn btn-sm btn-outline-primary active">&#128230; Đóng gói</button>
    <button id="grp-delivery" class="btn btn-sm btn-outline-primary">&#128666; Tiến độ giao</button>
    <button id="grp-stock" class="btn btn-sm btn-outline-primary">&#128230; Tình trạng kho</button>
  </div>
  <div class="d-flex align-items-center gap-2">
    <div class="btn-group btn-group-sm" role="group">
      <button id="btn-export-excel" class="btn btn-sm btn-success" title="Xuất Excel"><i class="fa fa-file-excel-o"></i> Xuất Excel</button>
      <button type="button" class="btn btn-sm btn-success dropdown-toggle dropdown-toggle-split" data-bs-toggle="dropdown" aria-expanded="false"><span class="visually-hidden">Mở rộng</span></button>
      <ul class="dropdown-menu">
        <li><a class="dropdown-item" id="btn-export-picking-excel" href="#" title="Xuất phiếu xuất kho (OUT đã xong)"><i class="fa fa-truck me-2"></i> Xuất phiếu XK</a></li>
        <li><a class="dropdown-item" id="btn-export-picking-simple-excel" href="#" title="Xuất phiếu XK giản lược (không in dòng sản phẩm)"><i class="fa fa-file-text-o me-2"></i> Xuất phiếu XK (tóm tắt)</a></li>
      </ul>
    </div>
    <div class="btn-group btn-group-sm" role="group">
      <button id="btn-kanban" class="btn btn-sm btn-primary"><i class="fa fa-th"></i> Kanban</button>
      <button id="btn-list" class="btn btn-sm btn-outline-secondary"><i class="fa fa-list"></i> Danh sách</button>
    </div>
    <span class="vr"></span>
    <button id="btn-load-more" class="btn btn-sm btn-outline-primary d-none"><i class="fa fa-plus"></i> Tải thêm 100</button>
    <span class="badge bg-primary" style="font-size:.85rem;padding:9px 12px" id="count-info">0 / 0 đơn hàng</span>
  </div>
</div>
<!-- Kanban -->
<div class="kanban-wrapper">
<div id="kanban-view" class="pb-3"></div>
</div>
<!-- List -->
<div id="list-view" class="d-none">
<div class="table-responsive"><table class="table table-hover table-sm table-bordered table-lines align-middle">
<thead class="table-light"><tr>
  <th>Đơn hàng</th><th>Khách hàng</th><th>Kho</th><th>Ngày đặt</th> 
  <th>Giao dự kiến</th><th>Tổng tiền</th><th>Giao hàng</th><th>Tồn kho</th><th>Đóng kiện</th>
</tr></thead><tbody id="tbl-body"></tbody>
</table></div></div>
</div>
<!-- Drawer overlay -->
<div id="drawer-overlay"></div>
<div id="drawer">
  <div class="p-3 border-bottom d-flex justify-content-between align-items-center bg-primary text-white">
    <h5 class="mb-0" id="dr-title"></h5>
    <button id="dr-close" class="btn btn-sm btn-light">&times;</button>
  </div>
  <div id="dr-body" class="p-3"></div>
  <div class="p-3 border-top bg-light fw-bold" id="dr-footer"></div>
</div>
<!-- Report modal -->
<div id="report-modal">
  <div class="rmod-card">
    <h6 class="fw-bold mb-1"><i class="fa fa-flag text-danger me-1"></i> Báo cáo đơn hàng</h6>
    <p class="text-muted small mb-3" id="report-so-name"></p>
    <textarea id="report-reason" class="form-control mb-3" rows="3" placeholder="Mô tả vấn đề (tùy chọn)..."></textarea>
    <div class="d-flex gap-2">
      <button class="btn btn-danger btn-sm flex-fill" id="report-submit"><i class="fa fa-flag me-1"></i>Gửi báo cáo</button>
      <button class="btn btn-outline-secondary btn-sm" id="report-cancel">Hủy</button>
    </div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
(function(){
"use strict";
var S={limit:100,total:0,viewMode:'kanban',kanbanGroupBy:'packing_status',
  orders:[],warehouses:[],stats:{},whSig:'',kanbanColPageSize:{},reportedIds:{},tagsSig:''};

var DL={unshipped:'Chưa giao',pending:'Chưa giao',partial:'Giao 1 phần',full:'Đã giao đủ'};
var DC={unshipped:'badge-del-pending',pending:'badge-del-pending',partial:'badge-del-partial',full:'badge-del-full'};
var SL={ready:'Đủ hàng xuất',partial_ready:'Có hàng 1 phần',out_of_stock:'Không có hàng'};
var SC={ready:'badge-stk-ready',partial_ready:'badge-stk-partial',out_of_stock:'badge-stk-out'};
var PL={waiting_stock:'Không Có Hàng Đóng',unpacked:'Có Hàng Chưa Đóng Gói',printed_waiting:'Đã In, Chờ Đóng Gói',packed_waiting_ship:'Đã Gói, Chờ Nhận Giao',delivered_today:'Đã Giao Trong Ngày',shipping:'Đang Giao',fully_packed:'Đã Đóng Gói Đủ'};
var PC={waiting_stock:'badge-pack-waiting',unpacked:'badge-pack-unpacked',printed_waiting:'badge-pack-printed',packed_waiting_ship:'badge-pack-packed',delivered_today:'badge-pack-deltoday',shipping:'badge-pack-shipping',fully_packed:'badge-pack-done'};
var POL={pending:'Chưa nhận',partial:'Nhận 1 phần',full:'Đã nhận đủ'};
var POC={pending:'badge-po-pending',partial:'badge-po-partial',full:'badge-po-full'};

function $(id){return document.getElementById(id)}
function fd(s){if(!s)return'';var d=new Date(s);if(isNaN(d))return s;return('0'+d.getDate()).slice(-2)+'/'+('0'+(d.getMonth()+1)).slice(-2)+'/'+d.getFullYear()}
function fm(v){return(v||0).toLocaleString('vi-VN')+'₫'}
function fq(v){var n=parseFloat(v)||0;return n%1===0?n.toLocaleString('vi-VN'):n.toLocaleString('vi-VN',{minimumFractionDigits:0,maximumFractionDigits:2})}
function b(cls,label){return'<span class="badge '+cls+' me-1">'+label+'</span>'}
function esc(s){if(!s)return'';var d=document.createElement('div');d.textContent=s;return d.innerHTML}
function gv(id){var e=$(id);return e?e.value:'';}
function showLoading(){var l=$('loading');if(l)l.classList.remove('d-none');}
function hideLoading(){var l=$('loading');if(l)l.classList.add('d-none');}
function getTagIds(){var e=$('f-tag');if(!e)return'';return Array.from(e.selectedOptions).map(function(o){return o.value;}).filter(Boolean).join(',');}
var TAG_BG=['#adb5bd','#dc3545','#fd7e14','#ffc107','#20c997','#6610f2','#d63384','#0d6efd','#6f42c1','#e91e63','#198754','#0dcaf0'];
var TAG_FG=[0,0,0,1,1,0,0,0,0,0,0,1]; // 1=dark text
function tagBadge(tag){var c=tag[2]||0;var bg=TAG_BG[c]||TAG_BG[0];var fg=TAG_FG[c]?'#000':'#fff';return'<span class="badge me-1" style="background-color:'+bg+';color:'+fg+'">'+esc(tag[1])+'</span>';}
function groupLines(lines){
  var map={},order=[];
  lines.forEach(function(l){
    var pid=l.product_id?l.product_id[0]:0;
    if(map[pid]){
      map[pid].product_uom_qty+=l.product_uom_qty||0;
      map[pid].qty_delivered+=l.qty_delivered||0;
      map[pid].qty_reserved_here+=(l.qty_reserved_here||0); // sum reservations across lines
      // qty_warehouse_free: keep first (product-level, same for all lines of same product/wh)
      map[pid].delivered_subtotal+=(l.delivered_subtotal||0);
      map[pid].delivered_tax+=(l.delivered_tax||0);
      map[pid].delivered_total+=(l.delivered_total||0);
    } else {
      map[pid]={product_id:l.product_id,product_uom_qty:l.product_uom_qty||0,
        qty_delivered:l.qty_delivered||0,qty_packed:l.qty_packed||0,
        qty_available:l.qty_available||0,qty_warehouse_free:l.qty_warehouse_free||0,
        qty_reserved_here:l.qty_reserved_here||0,is_kit:l.is_kit||false,
        price_unit:l.price_unit||0,discount:l.discount||0,
        delivered_subtotal:l.delivered_subtotal||0,
        delivered_tax:l.delivered_tax||0,
        delivered_total:l.delivered_total||0};
      order.push(pid);
    }
  });
  return order.map(function(pid){return map[pid];});
}

function partnerName(o){return o.partner_id?o.partner_id[1]:'';}
function whName(o){return o.warehouse_id?o.warehouse_id[1]:''}

// --- IndexedDB cache ---
var _SP_CACHE_TTL=5*60*1000;
function _spFilterKey(){
  return JSON.stringify([gv('f-q'),gv('f-wh'),gv('f-del'),gv('f-stk'),gv('f-pack'),
    gv('f-date-from'),gv('f-date-to'),gv('f-po-date-from'),gv('f-po-date-to'),
    gv('f-done-from'),gv('f-done-to'),gv('f-po-status'),gv('f-saler'),
    gv('f-htgh'),gv('f-dtype'),getTagIds(),$('f-show-completed').checked]);
}
function _spOpenDB(){
  return new Promise(function(resolve,reject){
    var req=indexedDB.open('hlv_sp_cache',1);
    req.onupgradeneeded=function(){var db=req.result;if(!db.objectStoreNames.contains('data'))db.createObjectStore('data');};
    req.onsuccess=function(){resolve(req.result);};
    req.onerror=function(){reject(req.error);};
  });
}
function _spSaveCache(result){
  _spOpenDB().then(function(db){
    var tx=db.transaction('data','readwrite');
    tx.objectStore('data').put({ts:Date.now(),fk:_spFilterKey(),data:result},'latest');
    tx.oncomplete=function(){db.close();};
    tx.onerror=function(){db.close();};
  }).catch(function(){});
}
function _spLoadCache(){
  return _spOpenDB().then(function(db){
    return new Promise(function(resolve){
      var tx=db.transaction('data','readonly');
      var req=tx.objectStore('data').get('latest');
      req.onsuccess=function(){
        db.close();
        var c=req.result;
        if(!c)return resolve(null);
        if(Date.now()-c.ts>_SP_CACHE_TTL)return resolve(null);
        if(c.fk!==_spFilterKey())return resolve(null);
        resolve(c.data);
      };
      req.onerror=function(){db.close();resolve(null);};
    });
  }).catch(function(){return null;});
}
var _spCacheRestored=false;

function load(append,silent){
  if(!_spCacheRestored&&!silent)showLoading();
  _spCacheRestored=false;
  var offset=append?S.orders.length:0;
  var lim=append?100:S.limit;
  var body={search:gv('f-q'),warehouse_id:gv('f-wh'),delivery_status:gv('f-del'),
    stock_status:gv('f-stk'),packing_status:gv('f-pack'),
    date_from:gv('f-date-from'),date_to:gv('f-date-to'),
    po_date_from:gv('f-po-date-from'),po_date_to:gv('f-po-date-to'),
    done_date_from:gv('f-done-from'),done_date_to:gv('f-done-to'),
    po_status:gv('f-po-status'),saler_code:gv('f-saler'),
    htgh:gv('f-htgh'),delivery_type:gv('f-dtype'),tag_ids:getTagIds(),
    show_completed:$('f-show-completed').checked,
    limit:lim,offset:offset};
  fetch('/api/sale_plan/data',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',method:'call',params:body})})
  .then(function(r){return r.json()})
  .then(function(j){
    hideLoading();
    if(!j.result||j.result.status!=='success'){console.error('API error',j);return;}
    var d=j.result.data;
    if(append){
      S.orders=S.orders.concat(d.orders||[]);
    } else {
      S.orders=d.orders||[];
      S.kanbanColPageSize={};
    }
    S.total=d.total_count||0;
    S.stats=d.dashboard_stats||{};
    // Compute effective_packing on each order (same logic as delivery_planner.js)
    var today=new Date().toISOString().slice(0,10);
    (append?d.orders||[]:S.orders).forEach(function(o){
      var ep=o.packing_status;
      var rd=o.real_delivery_status||o.delivery_status;
      // Đơn đã giao trong ngày (kể cả partial) VÀ không có PICK nào assigned sẵn hàng
      if(o.has_delivered_today&&(rd==='full'||!o.has_assigned_pick)) ep='delivered_today';
      else if(o.has_shipper_received) ep='shipping';
      else if(ep==='fully_packed') ep='packed_waiting_ship';
      else if(o.has_active_pick_printed&&ep!=='delivered') ep='printed_waiting';
      else if(ep==='partial_packed') ep='unpacked';
      o.effective_packing=ep;
      // Shipper name from pickings
      o._shipper_names=[];
      if(o.pickings){o.pickings.forEach(function(p){if(p.shipper_received&&p.shipper_user)o._shipper_names.push(p.shipper_user[1]);});}
      // New order flag
      var od=o.misa_order_date||(o.date_order?o.date_order.slice(0,10):'');
      o._is_new=(od===today);
    });
    // Refresh dropdown kho/tag mỗi khi backend trả danh sách khác → tránh stale
    if(d.warehouses){
      var whSig=d.warehouses.map(function(w){return w.id;}).join(',');
      if(whSig!==S.whSig){
        var sel=$('f-wh');var cur=sel.value;
        while(sel.options.length>1) sel.remove(1);
        d.warehouses.forEach(function(w){
          var o=document.createElement('option');o.value=w.id;o.textContent=w.name;sel.appendChild(o);
        });
        if(cur) sel.value=cur;
        S.whSig=whSig;S.warehouses=d.warehouses;
      }
    }
    if(d.tags){
      var tagSig=d.tags.map(function(t){return t.id;}).join(',');
      if(tagSig!==S.tagsSig){
        var tsel=$('f-tag');var curT=tsel.value;
        while(tsel.options.length>1) tsel.remove(1);
        S.tagsMap={};
        d.tags.forEach(function(t){
          S.tagsMap[t.id]=t;
          var o=document.createElement('option');o.value=t.id;o.textContent=t.name;tsel.appendChild(o);
        });
        if(curT) tsel.value=curT;
        S.tagsSig=tagSig;
      }
    }
    if(!append)_spSaveCache(d);
    updKPI();render();updLoadMore();updFilters();
  }).catch(function(e){hideLoading();console.error(e);});
}

function updKPI(){
  var s=S.stats;
  $('kpi-total').textContent=s.total||S.total||0;
  $('kpi-ready').textContent=s.ready||0;
  $('kpi-partial').textContent=s.partial||0;
  $('kpi-outstock').textContent=s.out_of_stock||0;
  // Count effective packing from client-side computed values
  var epCounts={waiting_stock:0,unpacked:0,printed_waiting:0,packed_waiting_ship:0,delivered_today:0,shipping:0};
  S.orders.forEach(function(o){var ep=o.effective_packing;if(epCounts[ep]!==undefined)epCounts[ep]++;});
  $('kpi-pw').textContent=epCounts.waiting_stock;
  $('kpi-pu').textContent=epCounts.unpacked;
  $('kpi-pp').textContent=epCounts.printed_waiting;
  $('kpi-pf').textContent=epCounts.packed_waiting_ship;
  $('kpi-pdt').textContent=epCounts.delivered_today;
  $('kpi-ps').textContent=epCounts.shipping;
  // Sync active state trên KPI pack cards với filter hiện tại
  var curPack=gv('f-pack');
  document.querySelectorAll('.kpi-pack').forEach(function(el){el.classList.remove('active');});
  if(curPack&&curPack!=='all'){
    var activeCard=document.querySelector('.kpi-pack[data-filter="'+curPack+'"]');
    if(activeCard)activeCard.classList.add('active');
  }
}

function updLoadMore(){
  var btn=$('btn-load-more');
  var remaining=S.total-S.orders.length;
  if(remaining>0){
    btn.classList.remove('d-none');
    btn.innerHTML='<i class="fa fa-plus"></i> Tải thêm '+(remaining>=100?100:remaining);
  } else {
    btn.classList.add('d-none');
  }
  $('count-info').textContent=S.orders.length+' / '+S.total+' đơn hàng';
}

function render(){
  if(S.viewMode==='kanban') renderKanban(); else renderList();
  $('kanban-view').classList.toggle('d-none',S.viewMode!=='kanban');
  $('list-view').classList.toggle('d-none',S.viewMode!=='list');
  ['grp-packing','grp-delivery','grp-stock'].forEach(function(id){
    $(id).style.display=S.viewMode==='kanban'?'':'none';
  });
}

function renderKanban(){
  var cols,gb=S.kanbanGroupBy;
  if(gb==='packing_status') cols=[
    {key:'waiting_stock',lbl:'KHÔNG CÓ HÀNG ĐÓNG',cls:'text-secondary'},
    {key:'unpacked',lbl:'CÓ HÀNG CHƯA ĐÓNG GÓI',cls:'text-warning'},
    {key:'printed_waiting',lbl:'ĐÃ IN, CHỜ ĐÓNG GÓI',cls:'text-info'},
    {key:'packed_waiting_ship',lbl:'ĐÃ GÓI, CHỜ NHẬN GIAO',cls:'text-primary'},
    {key:'shipping',lbl:'ĐANG GIAO',cls:'text-success'},
    {key:'delivered_today',lbl:'ĐÃ GIAO TRONG NGÀY',cls:'text-success'}
  ];
  else if(gb==='delivery_status') cols=[
    {key:'unshipped',lbl:'CHƯA GIAO',cls:'text-secondary'},
    {key:'partial',lbl:'GIAO 1 PHẦN',cls:'text-warning'},
    {key:'full',lbl:'ĐÃ GIAO ĐỦ',cls:'text-success'}
  ];
  else cols=[
    {key:'out_of_stock',lbl:'KHÔNG CÓ HÀNG',cls:'text-danger'},
    {key:'partial_ready',lbl:'CÓ HÀNG 1 PHẦN',cls:'text-warning'},
    {key:'ready',lbl:'ĐỦ HÀNG',cls:'text-success'}
  ];

  var wrap=$('kanban-view');wrap.innerHTML='';
  cols.forEach(function(c){
    var field=(gb==='delivery_status')?'real_delivery_status':(gb==='packing_status'?'effective_packing':gb);
    var needTransfer=$('f-need-transfer').checked;
    var items=S.orders.filter(function(o){
      if(needTransfer&&!(o.transfer_suggestions&&o.transfer_suggestions.length)) return false;
      return o[field]===c.key;
    });
    var pageSize=S.kanbanColPageSize[c.key]||15;
    var visible=items.slice(0,pageSize);
    var remaining=items.length-pageSize;
    var col=document.createElement('div');col.className='kanban-col';
    col.innerHTML='<div class="card"><div class="card-header d-flex justify-content-between align-items-center '+c.cls+' py-2">'
      +'<strong>'+c.lbl+'</strong><span class="badge bg-secondary rounded-pill">'+items.length+'</span></div>'
      +'<div class="card-body p-2 d-flex flex-column gap-2"></div></div>';
    wrap.appendChild(col);
    var body=col.querySelector('.card-body');
    visible.forEach(function(o){
      var card=document.createElement('div');
      card.innerHTML=renderSOCard(o);
      body.appendChild(card.firstChild);
    });
    if(remaining>0){
      var btn=document.createElement('button');
      btn.className='btn-col-more mt-1';
      btn.innerHTML='<i class="fa fa-chevron-down"></i> Tải thêm ('+remaining+' còn lại)';
      btn.setAttribute('data-col-key',c.key);
      body.appendChild(btn);
    }
  });
}

function getCardBorderClass(o){
  var rd=o.real_delivery_status||o.delivery_status;
  if(rd==='full')return'border-success';
  if(o.stock_status==='ready')return'border-primary';
  if(o.stock_status==='partial_ready')return'border-warning';
  return'border-danger';
}

function renderSOCard(o){
  var bc=getCardBorderClass(o);
  var rd=o.real_delivery_status||o.delivery_status;
  var reported=S.reportedIds&&S.reportedIds[o.id];
  var ep=o.effective_packing||o.packing_status;
  var bgCls=o.has_delivered_today?' so-card-deltoday':(o.stock_status==='ready'?' so-card-ready':(o._is_new?' so-card-new':''));
  var h='<div class="card so-card cursor-pointer '+bc+(reported?' opacity-75':'')+bgCls+'" data-so-id="'+o.id+'">'
    +'<div class="card-header py-2">'
    +'<div class="d-flex flex-wrap gap-1 mb-1">'
    +b(DC[rd]||'badge-del-pending',DL[rd]||rd)
    +b(SC[o.stock_status]||'badge-stk-out',SL[o.stock_status]||o.stock_status)
    +b(PC[ep]||'badge-pack-waiting',PL[ep]||ep)
    +'</div>'
    +'<h6 class="'+(o._is_new?'fw-bold mb-0':'text-primary fw-bold mb-0')+'" style="'+(o._is_new?'color:#d63384':'')+'">'+esc(o.name)
    +(o.misa_order_date?' <small class="text-muted fw-normal" style="font-size:.65rem">('+esc(o.misa_order_date)+')</small>':'')
    +(o._is_new?' <span class="badge" style="background:#d63384;color:#fff;font-size:.6rem">\u2605 M\u1edaI</span>':'')
    +'</h6>'
    +'<small class="text-muted"><i class="fa fa-user"></i> '+esc(partnerName(o))+'</small>'
    +'</div><div class="card-body py-2">';
  if(o.commitment_date) h+='<small class="text-muted"><i class="fa fa-calendar"></i> '+fd(o.commitment_date)+'</small><br>';
  if(o.x_studio_delivery_type) h+='<small class="text-muted"><i class="fa fa-truck me-1"></i>'+esc(o.x_studio_delivery_type)+'</small><br>';
  if(o.x_studio_htgh) h+='<small class="text-muted"><i class="fa fa-info-circle me-1"></i>'+esc(o.x_studio_htgh)+'</small><br>';
  if(o.x_studio_ghi_ch_odoo) h+='<small class="text-primary" style="font-size:.7rem"><i class="fa fa-pencil me-1"></i>'+esc(o.x_studio_ghi_ch_odoo)+'</small><br>';
  if(o.x_studio_misa_saler_code) h+='<small class="text-muted"><i class="fa fa-id-badge me-1"></i>NV: '+esc(o.x_studio_misa_saler_code)+'</small><br>';
  if(o.origin) h+='<small class="text-muted" style="font-size:.7rem"><i class="fa fa-sticky-note-o me-1 text-warning"></i><b>Ghi ch\u00fa:</b> '+esc(o.origin)+'</small><br>';
  if(o.misa_shipping_address) h+='<small class="text-muted" style="font-size:.7rem"><i class="fa fa-map-marker me-1 text-danger"></i>'+esc(o.misa_shipping_address)+'</small><br>';
  if(o._shipper_names&&o._shipper_names.length) h+='<small class="text-success fw-bold" style="font-size:.65rem"><i class="fa fa-motorcycle me-1"></i>T\u00e0i x\u1ebf: '+o._shipper_names.map(esc).join(', ')+'</small><br>';
  if(o.tag_ids&&o.tag_ids.length) h+='<div class="mt-1">'+o.tag_ids.map(tagBadge).join('')+'</div>';
  if(o.transfer_suggestions&&o.transfer_suggestions.length){
    var tsWhs={};o.transfer_suggestions.forEach(function(s){s.sources.forEach(function(src){tsWhs[src.from_warehouse_id]=1;});});
    var nWh=Object.keys(tsWhs).length;
    h+='<div class="mt-1"><span class="badge bg-danger bg-opacity-75 text-white" style="font-size:.68rem"><i class="fa fa-exchange me-1"></i>C\u1ea7n chuy\u1ec3n '+o.transfer_suggestions.length+' SP t\u1eeb '+nWh+' kho kh\u00e1c</span></div>';
  }
  h+='<div class="d-flex justify-content-between align-items-center">'
    +'<span class="fw-bold">'+fm(o.amount_total)+'</span>';
  var pc=o.pos?o.pos.length:0;
  if(pc>0) h+='<span class="badge bg-info text-dark">'+pc+' DMH</span>';
  h+='</div>';
  h+='<div class="d-flex justify-content-end mt-2">';
  if(reported){
    h+='<span class="text-muted" style="font-size:.65rem"><i class="fa fa-flag text-danger me-1"></i>Đã báo cáo</span>';
  } else {
    h+='<button class="btn-report" data-so-id="'+o.id+'" data-so-name="'+esc(o.name)+'"><i class="fa fa-flag me-1"></i>Báo cáo</button>';
  }
  h+='</div></div></div>';
  return h;
}

function renderList(){
  var tb=$('tbl-body');tb.innerHTML='';
  var needTransfer=$('f-need-transfer').checked;
  var filtered=S.orders.filter(function(o){
    if(needTransfer&&!(o.transfer_suggestions&&o.transfer_suggestions.length)) return false;
    return true;
  });
  filtered.forEach(function(o){
    var rd=o.real_delivery_status||o.delivery_status;
    var tr=document.createElement('tr');
    tr.className='cursor-pointer';
    tr.setAttribute('data-so-id',o.id);
    var isReported=S.reportedIds&&S.reportedIds[o.id];
    var reportCell=isReported
      ?'<td><span class="text-muted" style="font-size:.65rem"><i class="fa fa-flag text-danger"></i></span></td>'
      :'<td><button class="btn-report" data-so-id="'+o.id+'" data-so-name="'+esc(o.name)+'"><i class="fa fa-flag"></i></button></td>';
    tr.innerHTML='<td class="fw-bold text-primary">'+esc(o.name)+'</td>'
      +'<td>'+esc(partnerName(o))+'</td>'
      +'<td>'+esc(whName(o))+'</td>'
      +'<td>'+fd(o.date_order)+'</td>'
      +'<td>'+fd(o.commitment_date)+'</td>'
      +'<td class="text-end">'+fm(o.amount_total)+'</td>'
      +'<td>'+b(DC[rd]||'',DL[rd]||'')+'</td>'
      +'<td>'+b(SC[o.stock_status]||'',SL[o.stock_status]||'')+'</td>'
      +'<td>'+b(PC[o.effective_packing||o.packing_status]||'',PL[o.effective_packing||o.packing_status]||'')+'</td>'
      +reportCell;
    tb.appendChild(tr);
  });
}

var _currentDrawerOrderId=null;
var _currentMsgFiles=[];

function fmtFileSize(sz){
  if(sz>=1048576) return (sz/1048576).toFixed(1)+'MB';
  if(sz>=1024) return Math.round(sz/1024)+'KB';
  return sz+'B';
}

function renderPublicFileQueue(){
  var wrap=$('dr-msg-files');
  if(!wrap) return;
  if(!_currentMsgFiles.length){wrap.innerHTML='';return;}
  var html='';
  _currentMsgFiles.forEach(function(f,idx){
    html+='<span class="msg-compose-file"><i class="fa fa-paperclip"></i> '
      +esc(f.name)+' <small>('+fmtFileSize(f.size||0)+')</small>'
      +'<button type="button" data-file-idx="'+idx+'"><i class="fa fa-times"></i></button></span>';
  });
  wrap.innerHTML=html;
  wrap.querySelectorAll('button[data-file-idx]').forEach(function(btn){
    btn.addEventListener('click',function(ev){
      ev.preventDefault();
      var idx=parseInt(this.getAttribute('data-file-idx'),10);
      if(!isNaN(idx)){
        _currentMsgFiles.splice(idx,1);
        renderPublicFileQueue();
      }
    });
  });
}

function readFileAsBase64(file){
  return new Promise(function(resolve,reject){
    var reader=new FileReader();
    reader.onload=function(){
      var out=String(reader.result||'');
      var p=out.indexOf(',');
      resolve(p>=0?out.slice(p+1):out);
    };
    reader.onerror=reject;
    reader.readAsDataURL(file);
  });
}

function guessMimeTypeByName(name){
  var lower=(name||'').toLowerCase();
  var ext=lower.indexOf('.')>=0?lower.slice(lower.lastIndexOf('.')):'';
  var map={
    '.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.gif':'image/gif',
    '.webp':'image/webp','.bmp':'image/bmp','.heic':'image/heic','.heif':'image/heif',
    '.jfif':'image/jpeg','.svg':'image/svg+xml',
    '.mp4':'video/mp4','.mov':'video/quicktime','.avi':'video/x-msvideo','.mkv':'video/x-matroska',
    '.webm':'video/webm','.m4v':'video/x-m4v','.3gp':'video/3gpp',
    '.doc':'application/msword',
    '.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls':'application/vnd.ms-excel',
    '.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.csv':'text/csv'
  };
  return map[ext]||'';
}

async function onPublicFilesSelected(ev){
  var input=ev.target;
  var files=Array.from(input.files||[]);
  if(!files.length) return;
  var docExt=['.pdf','.doc','.docx','.xls','.xlsx','.csv'];
  var imageExt=['.jpg','.jpeg','.png','.gif','.webp','.bmp','.heic','.heif','.jfif','.svg'];
  var videoExt=['.mp4','.mov','.avi','.mkv','.webm','.m4v','.3gp'];
  var maxSize=20*1024*1024;

  for(var i=0;i<files.length;i++){
    var file=files[i];
    var lower=(file.name||'').toLowerCase();
    var ext=lower.indexOf('.')>=0?lower.slice(lower.lastIndexOf('.')):'';
    var mt=(file.type||'').toLowerCase();
    var isImg=mt.indexOf('image/')===0||imageExt.indexOf(ext)>=0;
    var isVideo=mt.indexOf('video/')===0||videoExt.indexOf(ext)>=0;
    var isPdf=mt==='application/pdf'||ext==='.pdf';
    var isDoc=docExt.indexOf(ext)>=0;
    if(!isImg&&!isVideo&&!isDoc&&!isPdf){
      alert('File '+file.name+' không thuộc định dạng hỗ trợ.');
      continue;
    }
    if((file.size||0)>maxSize){
      alert('File '+file.name+' vượt quá 20MB.');
      continue;
    }
    try{
      var datas=await readFileAsBase64(file);
      _currentMsgFiles.push({
        name:file.name,
        mimetype:mt||guessMimeTypeByName(file.name)||'application/octet-stream',
        size:file.size||0,
        datas:datas,
      });
    }catch(_e){
      alert('Không đọc được file '+file.name);
    }
  }
  input.value='';
  renderPublicFileQueue();
}

function loadMessages(orderId){
  if(orderId) _currentDrawerOrderId=orderId;
  var oid=orderId||_currentDrawerOrderId;
  if(!oid)return;
  $('dr-msg-list').innerHTML='<div class="msg-empty"><i class="fa fa-spinner fa-spin me-1"></i> Đang tải...</div>';
  fetch('/api/sale_plan/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{order_id:oid}})})
  .then(function(r){return r.json();})
  .then(function(resp){
    var d=resp.result||{};
    if(d.status!=='success'){$('dr-msg-list').innerHTML='<div class="msg-empty text-danger">Lỗi tải tin nhắn</div>';return;}
    var msgs=d.messages||[];
    var visibleMsgs=msgs.filter(function(m){return (m.body&&m.body.trim())||( m.attachments&&m.attachments.length);});
    $('dr-msg-count').textContent=visibleMsgs.length?'('+visibleMsgs.length+')':'';
    if(!visibleMsgs.length){$('dr-msg-list').innerHTML='<div class="msg-empty"><i class="fa fa-inbox me-1"></i> Chưa có tin nhắn</div>';return;}
    var html='';
    visibleMsgs.forEach(function(m){
      html+='<div class="msg-item">';
      html+='<div class="msg-meta">';
      if(m.author) html+='<span class="msg-author"><i class="fa fa-user-circle me-1"></i>'+esc(m.author)+'</span>';
      if(m.date) html+='<span class="msg-date">'+esc(m.date)+'</span>';
      if(m.origin) html+='<span class="msg-origin"><i class="fa fa-truck me-1"></i>'+esc(m.origin)+'</span>';
      html+='</div>';
      if(m.body&&m.body.trim()){
        var bodyClean=m.body.replace(/<\/?(html|head|body)[^>]*>/gi,'');
        html+='<div class="msg-body">'+bodyClean+'</div>';
      }
      if(m.attachments&&m.attachments.length){
        html+='<div class="msg-attachments">';
        m.attachments.forEach(function(a){
          var isImg=a.mimetype&&a.mimetype.indexOf('image/')===0;
          var isVideo=a.mimetype&&a.mimetype.indexOf('video/')===0;
          var url='/api/sale_plan/attachment/'+a.id;
          if(isImg){
            html+='<a href="'+url+'" target="_blank"><img class="msg-att-img" src="'+url+'" alt="'+esc(a.name)+'" loading="lazy"></a>';
          }else if(isVideo){
            var vSz=a.file_size>1048576?(a.file_size/1048576).toFixed(1)+'MB':(a.file_size>1024?(a.file_size/1024).toFixed(0)+'KB':a.file_size+'B');
            html+='<a class="msg-att" href="'+url+'" target="_blank"><i class="fa fa-video-camera"></i> '+esc(a.name)+' <small>('+vSz+')</small></a>';
          }else{
            var sz=a.file_size>1048576?(a.file_size/1048576).toFixed(1)+'MB':(a.file_size>1024?(a.file_size/1024).toFixed(0)+'KB':a.file_size+'B');
            html+='<a class="msg-att" href="'+url+'" target="_blank"><i class="fa fa-paperclip"></i> '+esc(a.name)+' <small>('+sz+')</small></a>';
          }
        });
        html+='</div>';
      }
      html+='</div>';
    });
    $('dr-msg-list').innerHTML=html;
  })
  .catch(function(){
    $('dr-msg-list').innerHTML='<div class="msg-empty text-danger">Lỗi kết nối</div>';
  });
}
function sendPublicMessage(){
  var body=($('dr-msg-input').value||'').trim();
  if((!body&&!_currentMsgFiles.length)||!_currentDrawerOrderId)return;
  var authorName=($('dr-msg-author').value||'').trim();
  if(!authorName){$('dr-msg-author').focus();$('dr-msg-author').classList.add('is-invalid');return;}
  $('dr-msg-author').classList.remove('is-invalid');
  localStorage.setItem('hlv_msg_author',authorName);
  var btn=$('dr-msg-send');btn.disabled=true;
  fetch('/api/sale_plan/send_message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{order_id:_currentDrawerOrderId,body:body,author_name:authorName,attachments:_currentMsgFiles.map(function(f){return {name:f.name,mimetype:f.mimetype,datas:f.datas};})}})})
  .then(function(r){return r.json();})
  .then(function(resp){
    btn.disabled=false;
    var d=resp.result||{};
    if(d.status==='success'){$('dr-msg-input').value='';_currentMsgFiles=[];renderPublicFileQueue();loadMessages();}
    else{alert(d.message||'Lỗi gửi tin nhắn');}
  })
  .catch(function(){btn.disabled=false;alert('Lỗi kết nối');});
}

function openDrawer(id){
  var o=S.orders.find(function(x){return x.id===id;});
  if(!o)return;
  $('dr-title').textContent=o.name;
  var rd=o.real_delivery_status||o.delivery_status;
  var ep=o.effective_packing||o.packing_status;
  var h='<div class="mb-3">'
    +'<div class="d-flex flex-wrap gap-1 mb-2">'
    +b(DC[rd]||'badge-del-pending',DL[rd]||rd)
    +b(SC[o.stock_status]||'badge-stk-out',SL[o.stock_status]||o.stock_status)
    +b(PC[ep]||'badge-pack-waiting',PL[ep]||ep)
    +'</div>'
    +'<div class="d-flex flex-column gap-2 mt-2 p-3 rounded" style="background:#f7fafc;border:1px solid #e2e8f0">'
    +'<div><i class="fa fa-user text-primary me-2"></i><strong>'+esc(partnerName(o))+'</strong></div>'
    +'<div><i class="fa fa-warehouse text-muted me-2"></i><span class="text-muted">'+esc(whName(o))+'</span></div>'
    +(o.commitment_date?'<div><i class="fa fa-calendar text-muted me-2"></i><span class="text-muted">Hẹn giao: '+fd(o.commitment_date)+'</span></div>':'')
    +(o.x_studio_delivery_type?'<div><i class="fa fa-truck text-muted me-2"></i><span class="text-muted">'+esc(o.x_studio_delivery_type)+'</span></div>':'')
    +(o.x_studio_htgh?'<div><i class="fa fa-info-circle text-muted me-2"></i><span class="text-muted">HTGH: '+esc(o.x_studio_htgh)+'</span></div>':'')
    +(o.x_studio_ghi_ch_odoo?'<div><i class="fa fa-pencil text-primary me-2"></i><span class="text-primary">Ghi Chú Odoo: '+esc(o.x_studio_ghi_ch_odoo)+'</span></div>':'')
    +(o.x_studio_misa_saler_code?'<div><i class="fa fa-id-badge text-muted me-2"></i><span class="text-muted">NV MISA: '+esc(o.x_studio_misa_saler_code)+'</span></div>':'')
    +(o.misa_shipping_address?'<div><i class="fa fa-map-marker text-muted me-2"></i><span class="text-muted">'+esc(o.misa_shipping_address)+'</span></div>':'')
    +(o._shipper_names&&o._shipper_names.length?'<div><i class="fa fa-motorcycle text-success me-2"></i><strong class="text-success">Tài xế: '+o._shipper_names.map(esc).join(', ')+'</strong></div>':'')
    +(o.origin?'<div><i class="fa fa-sticky-note text-muted me-2"></i><span class="text-muted">Ghi chú: '+esc(o.origin)+'</span></div>':'')
    +(o.tag_ids&&o.tag_ids.length?'<div><i class="fa fa-tags text-muted me-2"></i>'+o.tag_ids.map(tagBadge).join('')+'</div>':'')
    +'</div>'
    +'</div>';
  h+='<table class="table table-sm table-bordered table-lines"><thead class="table-light"><tr>'
    +'<th>Sản phẩm</th><th class="text-end">Chốt Bán</th><th class="text-end">Đóng Gói</th>'
    +'<th class="text-end">Tồn Kho</th><th class="text-end">Đã Giao</th>'
    +'<th class="text-end">Đơn Giá</th><th class="text-end">TT Thực Xuất</th><th class="text-end">VAT</th><th class="text-end">TT + VAT</th>'
    +'<th class="text-end">Thiếu</th></tr></thead><tbody>';
  var grouped=groupLines(o.lines||[]);
  var totalSubtotal=0,totalTax=0,totalTotal=0;
  grouped.forEach(function(l){
    var pname=l.product_id?l.product_id[1]:'Unknown';
    var wfree=(l.qty_warehouse_free||0)+(l.qty_reserved_here||0);
    var shortage=Math.max((l.product_uom_qty||0)-(l.qty_delivered||0)-(l.qty_packed||0)-wfree,0);
    var pending=(l.product_uom_qty||0)-(l.qty_delivered||0);
    var rc=pending>0?'table-warning':'table-success';
    var packCls=l.qty_packed>=l.product_uom_qty&&l.qty_packed>0?'cell-packed-full':(l.qty_packed>0?'cell-packed-partial':'cell-packed-zero');
    var stkCls=wfree>0?'cell-stock-ok':'cell-stock-zero';
    var packHtml=l.qty_packed>0?'<i class="fa fa-cube me-1"></i>'+fq(l.qty_packed)+(l.qty_packed>=l.product_uom_qty?' <i class="fa fa-check-circle"></i>':''):fq(0);
    h+='<tr class="'+rc+'"><td>'+esc(pname)+(l.is_kit?' <span class="badge bg-warning bg-opacity-25 text-dark" style="font-size:10px"><i class="fa fa-gift"></i> Combo</span>':'')+'</td>'
      +'<td class="text-end fw-bold">'+fq(l.product_uom_qty)+'</td>'
      +'<td class="text-end '+packCls+'">'+packHtml+'</td>'
      +'<td class="text-end '+stkCls+'">'+fq(wfree)+'</td>'
      +'<td class="text-end cell-delivered">'+fq(l.qty_delivered)+'</td>'
      +'<td class="text-end text-muted small">'+fm(l.price_unit||0)+(l.discount?'<div class="text-danger" style="font-size:0.7rem">-'+l.discount+'%</div>':'')+'</td>'
      +'<td class="text-end fw-bold text-success">'+fm(l.delivered_subtotal||0)+'</td>'
      +'<td class="text-end text-warning" style="font-size:0.82rem">'+fm(l.delivered_tax||0)+'</td>'
      +'<td class="text-end fw-bold text-primary">'+fm(l.delivered_total||0)+'</td>'
      +'<td class="text-end '+(shortage>0?'cell-shortage':'text-muted opacity-50')+'">'+fq(shortage)+'</td></tr>';
    totalSubtotal+=(l.delivered_subtotal||0);
    totalTax+=(l.delivered_tax||0);
    totalTotal+=(l.delivered_total||0);
  });
  h+='</tbody>'
    +'<tfoot><tr style="background:#f8fafc;border-top:2px solid #e2e8f0">'
    +'<td colspan="6" class="text-end text-muted small fw-semibold py-2">Tổng</td>'
    +'<td class="text-end fw-bold text-success py-2">'+fm(totalSubtotal)+'</td>'
    +'<td class="text-end fw-bold py-2" style="color:#b45309">'+fm(totalTax)+'</td>'
    +'<td class="text-end fw-bold text-primary py-2">'+fm(totalTotal)+'</td>'
    +'<td></td>'
    +'</tr></tfoot></table>';
  // Đề xuất chuyển kho
  if(o.transfer_suggestions&&o.transfer_suggestions.length){
    h+='<div class="alert alert-warning border-warning mt-3 p-3" style="background:rgba(255,193,7,.08)">'
      +'<h6 class="text-uppercase small mb-2"><i class="fa fa-exchange me-1"></i> Đề Xuất Chuyển Kho</h6>'
      +'<div class="small text-muted mb-2"><i class="fa fa-info-circle me-1"></i>Hàng chưa bị giữ bởi đơn khác</div>'
      +'<table class="table table-sm table-bordered table-hover text-center align-middle bg-white mb-0">'
      +'<thead class="table-light"><tr><th class="text-start">Sản phẩm</th><th>Từ kho</th><th>Khả dụng</th><th>Thiếu</th><th>Đề xuất</th></tr></thead><tbody>';
    o.transfer_suggestions.forEach(function(s){
      s.sources.forEach(function(src,idx){
        h+='<tr>';
        if(idx===0) h+='<td class="text-start small align-middle" rowspan="'+s.sources.length+'">'+esc(s.product_name)+'</td>';
        h+='<td><span class="badge bg-info bg-opacity-25 text-dark"><i class="fa fa-building me-1"></i>'+esc(src.from_warehouse_name)+'</span></td>'
          +'<td class="text-success fw-bold">'+fq(src.available_qty)+'</td>';
        if(idx===0) h+='<td class="text-danger fw-bold align-middle" rowspan="'+s.sources.length+'">'+fq(s.shortage)+'</td>';
        h+='<td><span class="badge bg-warning text-dark fw-bold"><i class="fa fa-arrow-right me-1"></i>'+fq(src.suggested_qty)+'</span></td></tr>';
      });
    });
    h+='</tbody></table></div>';
  }
  if(o.pos&&o.pos.length){
    h+='<h6 class="mt-3"><i class="fa fa-truck"></i> Đơn mua hàng ('+o.pos.length+')</h6>'
      +'<ul class="list-group list-group-flush">';
    o.pos.forEach(function(p){
      var st=p.receipt_status||'pending';
      h+='<li class="list-group-item py-2">'
        +'<div class="d-flex justify-content-between align-items-center">'
        +'<span>'+esc(p.name)
        +(p.date_planned?' <small class="text-muted">('+fd(p.date_planned)+')</small>':'')
        +(p.partner_id?' <small class="text-muted">- '+esc(p.partner_id[1])+'</small>':'')
        +'</span>'
        +b(POC[st]||'badge-po-pending',POL[st]||st)
        +'</div>';
      if(p.odoo_note){
        h+='<div class="small text-muted fst-italic border-start border-3 border-warning ps-2 mt-1" style="font-size:.75rem;white-space:pre-wrap;">'
          +'<i class="fa fa-sticky-note-o text-warning me-1"></i>'
          +esc(p.odoo_note)
          +'</div>';
      }
      h+='</li>';
    });
    h+='</ul>';
  }
  h+='<div class="msg-section" id="dr-msg-section">'
    +'<div class="msg-header open" id="dr-msg-toggle"><i class="fa fa-chevron-right me-1"></i><i class="fa fa-comments me-1"></i> Tin nhắn &amp; Chat <span class="text-muted" id="dr-msg-count" style="font-weight:400;font-size:.8rem"></span>'
    +'<button id="dr-msg-refresh" class="btn btn-sm btn-outline-secondary ms-auto px-2 py-0" title="Tải lại tin nhắn"><i class="fa fa-refresh"></i></button></div>'
    +'<div style="padding:10px 14px 6px;border-bottom:1px solid #e2e8f0;background:#f7fafc">'
    +'<div class="d-flex gap-2 mb-2"><input id="dr-msg-author" class="form-control form-control-sm" placeholder="Tên của bạn..." style="max-width:160px" value="'+esc(localStorage.getItem('hlv_msg_author')||'')+'"/>'
    +'<input id="dr-msg-files-input" type="file" multiple accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,application/pdf,image/*,video/*" style="display:none"/>'
    +'<button id="dr-msg-attach" class="btn btn-sm btn-outline-secondary px-2" title="Đính kèm PDF, Word, Excel, ảnh, video"><i class="fa fa-paperclip"></i></button>'
    +'<input id="dr-msg-input" class="form-control form-control-sm" placeholder="Nhập tin nhắn..."/>'
    +'<button id="dr-msg-send" class="btn btn-sm btn-primary px-3"><i class="fa fa-paper-plane"></i></button></div>'
    +'<div id="dr-msg-files" class="msg-compose-files"></div>'
    +'</div>'
    +'<div class="msg-list" id="dr-msg-list"><div class="msg-empty"><i class="fa fa-spinner fa-spin me-1"></i> Đang tải...</div></div>'
    +'</div>';
  $('dr-body').innerHTML=h;
  $('dr-footer').innerHTML='Trị giá: <span class="text-primary fs-5">'+fm(o.amount_total)+'</span>';
  $('dr-msg-toggle').addEventListener('click',function(e){
    if(e.target.closest('button'))return;
    this.classList.toggle('open');
    var list=$('dr-msg-list');
    var sendBox=this.nextElementSibling;
    var isOpen=this.classList.contains('open');
    list.style.display=isOpen?'':'none';
    if(sendBox&&sendBox.style)sendBox.style.display=isOpen?'':'none';
  });
  $('dr-msg-refresh').addEventListener('click',function(e){e.stopPropagation();loadMessages();});
  $('dr-msg-attach').addEventListener('click',function(e){e.preventDefault();e.stopPropagation();$('dr-msg-files-input').click();});
  $('dr-msg-files-input').addEventListener('change',onPublicFilesSelected);
  $('dr-msg-send').addEventListener('click',function(){sendPublicMessage();});
  $('dr-msg-input').addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();sendPublicMessage();}});
  $('dr-msg-input').addEventListener('paste',function(e){
    var items=e.clipboardData&&e.clipboardData.items;
    if(!items)return;
    var imgs=Array.from(items).filter(function(it){return it.type.indexOf('image/')===0;});
    if(!imgs.length)return;
    e.preventDefault();
    imgs.forEach(async function(item){
      var file=item.getAsFile();
      if(!file)return;
      if((file.size||0)>20*1024*1024){alert('\u1ea2nh d\u00e1n qu\u00e1 20MB.');return;}
      var extMap={'image/png':'.png','image/jpeg':'.jpg','image/gif':'.gif','image/webp':'.webp','image/bmp':'.bmp'};
      var ext=extMap[file.type]||'.png';
      var name='paste_'+Date.now()+ext;
      try{
        var datas=await readFileAsBase64(file);
        _currentMsgFiles.push({name:name,mimetype:file.type,size:file.size||0,datas:datas});
        renderPublicFileQueue();
      }catch(err){alert('Kh\u00f4ng \u0111\u1ecdc \u0111\u01b0\u1ee3c \u1ea3nh d\u00e1n.');}
    });
  });
  _currentMsgFiles=[];
  renderPublicFileQueue();
  loadMessages(o.id);
  $('drawer').classList.add('open');
  $('drawer-overlay').classList.add('open');
}

function closeDrawer(){
  $('drawer').classList.remove('open');
  $('drawer-overlay').classList.remove('open');
}

function updFilters(){
  var box=$('active-filters'),chips=[];
  if(gv('f-q')) chips.push({k:'f-q',v:'Tìm: '+gv('f-q'),reset:''});
  if(gv('f-wh')!=='all'){var s=$('f-wh');chips.push({k:'f-wh',v:'Kho: '+s.options[s.selectedIndex].text,reset:'all'});}
  if(gv('f-del')!=='all'){var s2=$('f-del');chips.push({k:'f-del',v:'Giao hàng: '+s2.options[s2.selectedIndex].text,reset:'all'});}
  if(gv('f-stk')!=='all'){var s3=$('f-stk');chips.push({k:'f-stk',v:'Kho: '+s3.options[s3.selectedIndex].text,reset:'all'});}
  if(gv('f-pack')!=='all'){var s4=$('f-pack');chips.push({k:'f-pack',v:'Đóng gói: '+s4.options[s4.selectedIndex].text,reset:'all'});}
  if(gv('f-date-from')) chips.push({k:'f-date-from',v:'Hẹn giao từ: '+gv('f-date-from'),reset:''});
  if(gv('f-date-to')) chips.push({k:'f-date-to',v:'Hẹn giao đến: '+gv('f-date-to'),reset:''});
  if(gv('f-done-from')) chips.push({k:'f-done-from',v:'HT từ: '+gv('f-done-from'),reset:''});
  if(gv('f-done-to')) chips.push({k:'f-done-to',v:'HT đến: '+gv('f-done-to'),reset:''});
  if(gv('f-po-date-from')) chips.push({k:'f-po-date-from',v:'Nhận từ: '+gv('f-po-date-from'),reset:''});
  if(gv('f-po-date-to')) chips.push({k:'f-po-date-to',v:'Nhận đến: '+gv('f-po-date-to'),reset:''});
  if(gv('f-po-status')!=='all'){var s5=$('f-po-status');chips.push({k:'f-po-status',v:'Mua hàng: '+s5.options[s5.selectedIndex].text,reset:'all'});}
  if(gv('f-saler')) chips.push({k:'f-saler',v:'NV MISA: '+gv('f-saler'),reset:''});
  if(gv('f-htgh')) chips.push({k:'f-htgh',v:'HTGH: '+gv('f-htgh'),reset:''});
  if(gv('f-dtype')!=='all'){var s6=$('f-dtype');chips.push({k:'f-dtype',v:'Vận chuyển: '+s6.options[s6.selectedIndex].text,reset:'all'});}
  // per-tag chips
  var tsel=$('f-tag');
  if(tsel){Array.from(tsel.selectedOptions).forEach(function(opt){
    chips.push({k:'f-tag-'+opt.value,v:'Tag: '+opt.text,tagId:opt.value});
  });}
  if(!chips.length){box.classList.add('d-none');return;}
  box.classList.remove('d-none');
  box.innerHTML='<i class="fa fa-filter text-muted small"></i> <small class="text-muted">Bộ lọc đang chọn:</small> '
    +chips.map(function(c){
      var attr=c.tagId!==undefined?'data-tag-id="'+c.tagId+'"':'data-fk="'+c.k+'" data-fr="'+(c.reset||'')+'"';
      return '<span class="badge bg-success filter-chip" '+attr+'>'
        +esc(c.v)+' <span class="chip-x" '+attr+'>&times;</span></span>';
    }).join('')
    +' <a href="#" id="clear-all-filters" class="small text-danger ms-1"><i class="fa fa-trash"></i> Xóa tất cả bộ lọc</a>';
}

document.addEventListener('click',function(e){
  var chipX=e.target.closest('.chip-x');
  if(chipX){
    e.preventDefault();e.stopPropagation();
    if(chipX.dataset.tagId){
      var tsel=$('f-tag');
      if(tsel){Array.from(tsel.options).forEach(function(o){if(o.value===chipX.dataset.tagId)o.selected=false;});}
    } else {
      var el=$(chipX.dataset.fk);
      if(el){el.value=chipX.dataset.fr||'';}
    }
    load(false);return;
  }
  var rBtn=e.target.closest('.btn-report');
  if(rBtn){e.stopPropagation();e.preventDefault();openReportModal(parseInt(rBtn.dataset.soId,10),rBtn.dataset.soName);return;}
  if(e.target.closest('#clear-all-filters')){e.preventDefault();clearAll();return;}
  var colMore=e.target.closest('.btn-col-more');
  if(colMore){
    e.preventDefault();
    var ck=colMore.getAttribute('data-col-key');
    S.kanbanColPageSize[ck]=(S.kanbanColPageSize[ck]||15)+15;
    renderKanban();return;
  }
  var card=e.target.closest('[data-so-id]');
  if(card){openDrawer(parseInt(card.dataset.soId,10));}
});

function clearAll(){
  ['f-q','f-date-from','f-date-to','f-po-date-from','f-po-date-to','f-saler','f-htgh','f-done-from','f-done-to'].forEach(function(id){var e=$(id);if(e)e.value='';});
  ['f-wh','f-stk','f-pack','f-po-status','f-dtype'].forEach(function(id){var e=$(id);if(e)e.value='all';});
  $('f-del').value='all';
  var ft=$('f-tag');if(ft){Array.from(ft.options).forEach(function(o){o.selected=false;});}
  $('f-show-completed').checked=true;
  S.kanbanColPageSize={};
  load(false);
}

$('btn-filter').addEventListener('click',function(){S.kanbanColPageSize={};load(false);});
$('f-need-transfer').addEventListener('change',function(){render();});
$('f-show-completed').addEventListener('change',function(){S.kanbanColPageSize={};load(false);});
$('f-q').addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();S.kanbanColPageSize={};load(false);}});
$('f-saler').addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();S.kanbanColPageSize={};load(false);}});
$('f-htgh').addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();S.kanbanColPageSize={};load(false);}});

// HTGH presets (localStorage)
var HTGH_LS_KEY='hlv_htgh_presets';
var defaultHtghPresets=[
  {label:'Hãng VC',value:'ghn,cpn,chuyển phát nhanh,giao hàng nhanh,j&t'},
  {label:'Trừ hãng VC',value:'!ghn,!cpn,!chuyển phát nhanh,!giao hàng nhanh,!j&t'},
];
function loadHtghPresets(){
  try{return JSON.parse(localStorage.getItem(HTGH_LS_KEY))||defaultHtghPresets;}
  catch(e){return defaultHtghPresets;}
}
function saveHtghPresetsLS(arr){
  localStorage.setItem(HTGH_LS_KEY,JSON.stringify(arr));
}
function renderHtghPresets(){
  var container=$('htgh-presets');
  if(!container)return;
  var presets=loadHtghPresets();
  container.innerHTML='';
  presets.forEach(function(p,idx){
    var span=document.createElement('span');
    span.className='badge border d-inline-flex align-items-center gap-1 px-2 py-1';
    span.style.cssText='font-size:.65rem;background:#f8f9fa;color:#495057;border-color:#dee2e6;cursor:default';
    var lbl=document.createElement('span');
    lbl.style.cursor='pointer';
    lbl.title=p.value;
    lbl.textContent=p.label;
    lbl.addEventListener('click',function(){$('f-htgh').value=p.value;S.kanbanColPageSize={};load(false);});
    var del=document.createElement('i');
    del.className='fa fa-times ms-1';
    del.style.cssText='cursor:pointer;opacity:.5';
    del.title='Xóa gợi ý này';
    del.addEventListener('click',function(){
      var arr=loadHtghPresets();arr.splice(idx,1);saveHtghPresetsLS(arr);renderHtghPresets();
    });
    span.appendChild(lbl);span.appendChild(del);
    container.appendChild(span);
  });
}
$('btn-htgh-save').addEventListener('click',function(){
  var val=$('f-htgh').value.trim();
  if(!val)return;
  var label=prompt('Tên gợi ý:',val.slice(0,30));
  if(!label)return;
  var arr=loadHtghPresets();arr.push({label:label,value:val});saveHtghPresetsLS(arr);renderHtghPresets();
});
renderHtghPresets();
$('btn-load-more').addEventListener('click',function(){load(true);});
$('btn-refresh').addEventListener('click',function(){S.kanbanColPageSize={};load(false);});
$('btn-export-excel').addEventListener('click',function(){
  var params=new URLSearchParams({
    search_query:gv('f-q'),filter_warehouse_id:gv('f-wh'),filter_delivery_status:gv('f-del'),
    filter_stock_status:gv('f-stk'),filter_packing_status:gv('f-pack'),
    filter_date_from:gv('f-date-from'),filter_date_to:gv('f-date-to'),
    filter_po_date_from:gv('f-po-date-from'),filter_po_date_to:gv('f-po-date-to'),
    filter_done_date_from:gv('f-done-from'),filter_done_date_to:gv('f-done-to'),
    filter_po_status:gv('f-po-status'),filter_saler_code:gv('f-saler'),
    filter_htgh:gv('f-htgh'),filter_delivery_type:gv('f-dtype'),filter_tag_ids:getTagIds(),
    show_completed:$('f-show-completed').checked?'1':''
  });
  window.open('/api/sale_plan/export_excel?'+params.toString(),'_blank');
});
$('btn-export-picking-excel').addEventListener('click',function(){
  var params=new URLSearchParams({
    search_query:gv('f-q'),filter_warehouse_id:gv('f-wh'),filter_delivery_status:gv('f-del'),
    filter_stock_status:gv('f-stk'),filter_packing_status:gv('f-pack'),
    filter_date_from:gv('f-date-from'),filter_date_to:gv('f-date-to'),
    filter_po_date_from:gv('f-po-date-from'),filter_po_date_to:gv('f-po-date-to'),
    filter_done_date_from:gv('f-done-from'),filter_done_date_to:gv('f-done-to'),
    filter_po_status:gv('f-po-status'),filter_saler_code:gv('f-saler'),
    filter_htgh:gv('f-htgh'),filter_delivery_type:gv('f-dtype'),filter_tag_ids:getTagIds(),
    show_completed:$('f-show-completed').checked?'1':''
  });
  window.open('/api/sale_plan/export_picking_excel?'+params.toString(),'_blank');
});
$('btn-export-picking-simple-excel').addEventListener('click',function(){
  var params=new URLSearchParams({
    search_query:gv('f-q'),filter_warehouse_id:gv('f-wh'),filter_delivery_status:gv('f-del'),
    filter_stock_status:gv('f-stk'),filter_packing_status:gv('f-pack'),
    filter_date_from:gv('f-date-from'),filter_date_to:gv('f-date-to'),
    filter_po_date_from:gv('f-po-date-from'),filter_po_date_to:gv('f-po-date-to'),
    filter_done_date_from:gv('f-done-from'),filter_done_date_to:gv('f-done-to'),
    filter_po_status:gv('f-po-status'),filter_saler_code:gv('f-saler'),
    filter_htgh:gv('f-htgh'),filter_delivery_type:gv('f-dtype'),filter_tag_ids:getTagIds(),
    show_completed:$('f-show-completed').checked?'1':''
  });
  window.open('/api/sale_plan/export_picking_simple_excel?'+params.toString(),'_blank');
});

$('btn-kanban').addEventListener('click',function(){
  S.viewMode='kanban';
  this.className='btn btn-sm btn-primary';
  $('btn-list').className='btn btn-sm btn-outline-secondary';
  render();
});
$('btn-list').addEventListener('click',function(){
  S.viewMode='list';
  this.className='btn btn-sm btn-primary';
  $('btn-kanban').className='btn btn-sm btn-outline-secondary';
  render();
});

['grp-packing','grp-delivery','grp-stock'].forEach(function(id){
  $(id).addEventListener('click',function(){
    var map={'grp-packing':'packing_status','grp-delivery':'delivery_status','grp-stock':'stock_status'};
    S.kanbanGroupBy=map[id];
    S.kanbanColPageSize={};
    ['grp-packing','grp-delivery','grp-stock'].forEach(function(g){$(g).classList.remove('active');});
    this.classList.add('active');
    render();
  });
});

['kpi-pack-waiting','kpi-pack-unpacked','kpi-pack-printed','kpi-pack-done','kpi-pack-deltoday','kpi-pack-shipping'].forEach(function(id){
  var el=$(id);if(!el)return;
  el.addEventListener('click',function(){
    var f=this.dataset.filter;
    var cur=gv('f-pack');
    $('f-pack').value=(cur===f)?'all':f;
    document.querySelectorAll('.kpi-pack').forEach(function(el){el.classList.remove('active');});
    if(cur!==f) this.classList.add('active');
    load(false);
  });
});

$('dr-close').addEventListener('click',closeDrawer);
$('drawer-overlay').addEventListener('click',closeDrawer);
document.addEventListener('keydown',function(e){if(e.key==='Escape'){closeDrawer();closeReportModal();}});

// --- Auto-refresh: poll for changes every 10s ---
var _lastFingerprint=null;
var _pollInterval=60000; // 10 seconds
var _pollTimer=null;
var _pollPaused=false;

function pollChanges(){
  if(_pollPaused)return;
  fetch('/api/sale_plan/check_changes',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})})
  .then(function(r){return r.json();})
  .then(function(j){
    if(!j.result||j.result.status!=='success')return;
    var fp=j.result.fingerprint;
    if(_lastFingerprint===null){_lastFingerprint=fp;return;}
    if(fp!==_lastFingerprint){
      _lastFingerprint=fp;
      load(false,true);
      // Show a brief toast notification
      var t=document.createElement('div');
      t.style.cssText='position:fixed;bottom:24px;left:24px;z-index:3000;background:#3182ce;color:#fff;padding:10px 18px;border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,.2);font-size:.85rem;font-weight:600;transition:opacity .3s';
      t.innerHTML='<i class="fa fa-refresh me-1"></i>Dữ liệu đã được cập nhật tự động';
      document.body.appendChild(t);
      setTimeout(function(){t.style.opacity='0';setTimeout(function(){t.remove();},400);},3000);
    }
  })
  .catch(function(){/* silent */});
}

function startPolling(){
  if(_pollTimer)clearInterval(_pollTimer);
  _pollTimer=setInterval(pollChanges,_pollInterval);
}

// Pause polling when tab is hidden to save resources
document.addEventListener('visibilitychange',function(){
  if(document.hidden){_pollPaused=true;}
  else{_pollPaused=false;pollChanges();}
});

// Start polling after initial load completes
var _origLoad=load;
var _firstLoadDone=false;
// We hook into the existing load callback by overriding:
// After the first successful load, start polling
(function(){
  var origFetch=window.fetch;
  var pendingDataReq=false;
  window.fetch=function(url,opts){
    var isDataReq=(typeof url==='string'&&url.indexOf('/api/sale_plan/data')!==-1);
    if(isDataReq)pendingDataReq=true;
    return origFetch.apply(this,arguments).then(function(resp){
      if(isDataReq&&pendingDataReq){
        pendingDataReq=false;
        if(!_firstLoadDone){
          _firstLoadDone=true;
          // Set initial fingerprint from a check right after first load
          pollChanges();
          startPolling();
        }
      }
      return resp;
    });
  };
})();

// --- Report modal ---
var _reportSoId=null;
function openReportModal(id,name){
  _reportSoId=id;
  $('report-so-name').textContent='Đơn hàng: '+name;
  $('report-reason').value='';
  var m=$('report-modal');m.style.display='flex';
  setTimeout(function(){$('report-reason').focus();},80);
}
function closeReportModal(){
  $('report-modal').style.display='none';
  _reportSoId=null;
}
$('report-cancel').addEventListener('click',closeReportModal);
$('report-modal').addEventListener('click',function(e){if(e.target===this)closeReportModal();});
$('report-submit').addEventListener('click',function(){
  if(!_reportSoId)return;
  var reason=$('report-reason').value.trim()||'(Không có mô tả)';
  var btn=this;btn.disabled=true;btn.innerHTML='<i class="fa fa-spinner fa-spin me-1"></i>Đang gửi...';
  fetch('/api/sale_plan/report_order',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{order_id:_reportSoId,reason:reason}})})
  .then(function(r){return r.json();})
  .then(function(j){
    btn.disabled=false;btn.innerHTML='<i class="fa fa-flag me-1"></i>Gửi báo cáo';
    if(j.result&&j.result.status==='success'){
      S.reportedIds[_reportSoId]=true;
      closeReportModal();
      render();
      var toast=document.createElement('div');
      toast.style.cssText='position:fixed;bottom:24px;right:24px;z-index:3000;background:#38a169;color:#fff;padding:12px 20px;border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,.2);font-weight:600';
      toast.innerHTML='<i class="fa fa-check me-1"></i>Đã gửi báo cáo cho admin';
      document.body.appendChild(toast);setTimeout(function(){toast.remove();},3500);
    } else {
      alert('Lỗi gửi báo cáo: '+(j.result&&j.result.message||'Lỗi không xác định'));
    }
  }).catch(function(){btn.disabled=false;btn.innerHTML='<i class="fa fa-flag me-1"></i>Gửi báo cáo';alert('Lỗi kết nối.');});
});

// Restore from IndexedDB cache for instant display, then refresh in background
_spLoadCache().then(function(_cachedData){
if(_cachedData){
  _spCacheRestored=true;
  S.orders=_cachedData.orders||[];
  S.total=_cachedData.total_count||0;
  S.stats=_cachedData.dashboard_stats||{};
  var today=new Date().toISOString().slice(0,10);
  S.orders.forEach(function(o){
    var ep=o.packing_status;
    var rd=o.real_delivery_status||o.delivery_status;
    if(o.has_delivered_today&&(rd==='full'||!o.has_assigned_pick)) ep='delivered_today';
    else if(o.has_shipper_received) ep='shipping';
    else if(ep==='fully_packed') ep='packed_waiting_ship';
    else if(o.has_active_pick_printed&&ep!=='delivered') ep='printed_waiting';
    else if(ep==='partial_packed') ep='unpacked';
    o.effective_packing=ep;
    o._shipper_names=[];
    if(o.pickings){o.pickings.forEach(function(p){if(p.shipper_received&&p.shipper_user)o._shipper_names.push(p.shipper_user[1]);});}
    var od=o.misa_order_date||(o.date_order?o.date_order.slice(0,10):'');
    o._is_new=(od===today);
  });
  if(_cachedData.warehouses){
    var sel=$('f-wh');
    _cachedData.warehouses.forEach(function(w){
      var opt=document.createElement('option');opt.value=w.id;opt.textContent=w.name;sel.appendChild(opt);
    });
    S.whSig=_cachedData.warehouses.map(function(w){return w.id;}).join(',');
    S.warehouses=_cachedData.warehouses;
  }
  if(_cachedData.tags){
    var tsel=$('f-tag');S.tagsMap={};
    _cachedData.tags.forEach(function(t){
      S.tagsMap[t.id]=t;
      var opt=document.createElement('option');opt.value=t.id;opt.textContent=t.name;tsel.appendChild(opt);
    });
    S.tagsSig=_cachedData.tags.map(function(t){return t.id;}).join(',');
  }
  updKPI();render();updLoadMore();updFilters();
  hideLoading();
}
load(false);
});
})();
</script>
</body></html>"""


class SalePlanPublicController(http.Controller):

    @http.route('/sale_plan', type='http', auth='public', methods=['GET', 'POST'])
    def sale_plan_page(self, **kwargs):
        ip = request.httprequest.remote_addr
        conf_pw = (
            request.env['ir.config_parameter'].sudo()
            .get_param(PW_PARAM_KEY, default='') or ''
        )
        if not request.session.get(SESSION_KEY_OK):
            if request.httprequest.method == 'POST':
                if _is_rate_limited(ip):
                    return request.make_response(
                        _LOGIN.format(csrf=request.csrf_token(), err=_ERR_RATE),
                        headers=_H)
                inp = (request.params.get('inv_password') or '').strip()
                if inp == conf_pw:
                    request.session[SESSION_KEY_OK] = True
                    _FAIL_LOG.pop(ip, None)
                    return request.redirect('/sale_plan')
                _record_failure(ip)
                return request.make_response(
                    _LOGIN.format(csrf=request.csrf_token(), err=_ERR_PW),
                    headers=_H)
            return request.make_response(
                _LOGIN.format(csrf=request.csrf_token(), err=''),
                headers=_H)
        return request.make_response(_PAGE, headers=_H)

    @http.route('/api/sale_plan/data', type='json', auth='public', methods=['POST'])
    def api_sale_plan_data(self, search='', warehouse_id='all', delivery_status='all',
                           stock_status='all', packing_status='all',
                           date_from='', date_to='', po_date_from='', po_date_to='',
                           done_date_from='', done_date_to='',
                           po_status='all', saler_code='', htgh='', delivery_type='all',
                           tag_ids='', limit=250, offset=0, show_completed=False, **kwargs):
        if not request.session.get(SESSION_KEY_OK):
            return {'status': 'error', 'message': 'Unauthorized'}
        try:
            result = request.env['hlv.delivery.planner.service'].sudo().get_dashboard_data(
                search_query=search,
                filter_warehouse_id=warehouse_id,
                filter_delivery_status=delivery_status,
                filter_stock_status=stock_status,
                filter_packing_status=packing_status,
                filter_date_from=date_from,
                filter_date_to=date_to,
                filter_po_date_from=po_date_from,
                filter_po_date_to=po_date_to,
                filter_done_date_from=done_date_from,
                filter_done_date_to=done_date_to,
                filter_po_status=po_status,
                filter_saler_code=saler_code,
                filter_htgh=htgh,
                filter_delivery_type=delivery_type,
                filter_tag_ids=tag_ids,
                limit=int(limit),
                offset=int(offset),
                show_completed=bool(show_completed),
            )
            return {'status': 'success', 'data': result}
        except Exception as e:
            _logger.exception('sale_plan API error')
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/sale_plan/check_changes', type='json', auth='public', methods=['POST'])
    def api_check_changes(self, **kwargs):
        """Lightweight endpoint: returns a fingerprint (max write_date + record count)
        so the frontend can detect changes without reloading heavy data."""
        if not request.session.get(SESSION_KEY_OK):
            return {'status': 'error', 'message': 'Unauthorized'}
        try:
            SaleOrder = request.env['sale.order'].sudo()
            domain = [('state', 'in', ['sale', 'done'])]
            result = SaleOrder.search_read(domain, fields=['write_date'], order='write_date desc', limit=1)
            max_write = result[0]['write_date'].isoformat() if result else ''
            count = SaleOrder.search_count(domain)
            # Also check stock.picking changes (packing/delivery status changes)
            Picking = request.env['stock.picking'].sudo()
            pick_result = Picking.search_read(
                [('sale_id', '!=', False)],
                fields=['write_date'], order='write_date desc', limit=1
            )
            pick_write = pick_result[0]['write_date'].isoformat() if pick_result else ''
            fingerprint = f"{max_write}|{count}|{pick_write}"
            return {'status': 'success', 'fingerprint': fingerprint}
        except Exception as e:
            _logger.exception('check_changes error')
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/sale_plan/report_order', type='json', auth='public', methods=['POST'])
    def api_report_order(self, order_id=None, reason='', **kwargs):
        if not request.session.get(SESSION_KEY_OK):
            return {'status': 'error', 'message': 'Unauthorized'}
        try:
            so = request.env['sale.order'].sudo().browse(int(order_id))
            if not so.exists():
                return {'status': 'error', 'message': 'Order not found'}
            safe_reason = Markup.escape(reason or '(Không có mô tả)')
            body = Markup(
                '<p>🚩 <strong>Báo cáo từ trang công khai (sale_plan):</strong></p>'
                '<blockquote>%s</blockquote>'
            ) % safe_reason
            so.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note')
            so.x_plan_need_cancel = True
            return {'status': 'success'}
        except Exception as e:
            _logger.exception('report_order error')
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/sale_plan/messages', type='json', auth='public', methods=['POST'])
    def api_sale_plan_messages(self, order_id=None, **kwargs):
        if not request.session.get(SESSION_KEY_OK):
            return {'status': 'error', 'message': 'Unauthorized'}
        try:
            so = request.env['sale.order'].sudo().browse(int(order_id))
            if not so.exists():
                return {'status': 'error', 'message': 'Order not found'}
            # Public page không có user login → mail.message.date lưu UTC, phải
            # convert sang TZ VN để hiển thị đúng giờ thực tế (tránh lệch 7h).
            try:
                user_tz = pytz.timezone('Asia/Ho_Chi_Minh')
            except Exception:
                user_tz = pytz.UTC
            picking_ids = so.picking_ids.ids
            domain = [
                '|',
                '&', ('model', '=', 'sale.order'), ('res_id', '=', so.id),
                '&', ('model', '=', 'stock.picking'), ('res_id', 'in', picking_ids),
            ]
            messages = request.env['mail.message'].sudo().search(domain, order='date desc', limit=200)
            result = []
            picking_name_map = {p.id: p.name for p in so.picking_ids}
            for msg in messages:
                # Skip system/automated messages by body content
                plain = re.sub(r'<[^>]+>', '', msg.body or '').strip()
                has_att = bool(msg.attachment_ids)
                if not plain and not has_att:
                    continue
                if plain and _SKIP_MSG_RE.search(plain):
                    continue
                attachments = []
                for att in msg.attachment_ids:
                    attachments.append({
                        'id': att.id,
                        'name': att.name or '',
                        'mimetype': att.mimetype or 'application/octet-stream',
                        'file_size': att.file_size or 0,
                    })
                origin = ''
                if msg.model == 'stock.picking':
                    origin = picking_name_map.get(msg.res_id, '')
                date_str = ''
                if msg.date:
                    try:
                        local_dt = msg.date.replace(tzinfo=pytz.UTC).astimezone(user_tz)
                        date_str = local_dt.strftime('%d/%m/%Y %H:%M')
                    except Exception:
                        date_str = msg.date.strftime('%d/%m/%Y %H:%M')
                result.append({
                    'id': msg.id,
                    'date': date_str,
                    'author': msg.author_id.name if msg.author_id else (msg.email_from or ''),
                    'body': msg.body or '',
                    'message_type': msg.message_type,
                    'subtype': msg.subtype_id.name if msg.subtype_id else '',
                    'origin': origin,
                    'attachments': attachments,
                })
            return {'status': 'success', 'messages': result}
        except Exception as e:
            _logger.exception('sale_plan messages error')
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/sale_plan/send_message', type='json', auth='public', methods=['POST'])
    def api_sale_plan_send_message(self, order_id=None, body='', author_name='', attachments=None, **kwargs):
        if not request.session.get(SESSION_KEY_OK):
            return {'status': 'error', 'message': 'Unauthorized'}
        try:
            body = (body or '').strip()
            attachments = attachments or []
            so = request.env['sale.order'].sudo().browse(int(order_id))
            if not so.exists():
                return {'status': 'error', 'message': 'Order not found'}
            author_name = (author_name or '').strip()

            attachment_ids = []
            skipped_attachments = []
            for att in attachments:
              if not isinstance(att, dict):
                skipped_attachments.append({'reason': 'invalid_payload'})
                continue
              name = (att.get('name') or 'file').strip()[:255]
              mimetype = (att.get('mimetype') or 'application/octet-stream').strip().lower()
              datas = (att.get('datas') or '').strip()
              if not datas:
                skipped_attachments.append({'name': name, 'mimetype': mimetype, 'reason': 'empty_datas'})
                continue
              if not _is_allowed_chat_attachment(name, mimetype):
                skipped_attachments.append({'name': name, 'mimetype': mimetype, 'reason': 'blocked_by_whitelist'})
                continue
              estimated_size = int(len(datas) * 0.75)
              if estimated_size > _MAX_CHAT_ATTACHMENT_BYTES:
                skipped_attachments.append({'name': name, 'mimetype': mimetype, 'reason': 'too_large', 'estimated_size': estimated_size})
                continue
              new_att = request.env['ir.attachment'].sudo().create({
                    'name': name,
                    'datas': datas,
                    'mimetype': mimetype,
                    'res_model': 'sale.order',
                    'res_id': so.id,
                    'type': 'binary',
              })
              attachment_ids.append(new_att.id)

            if skipped_attachments:
                _logger.info('sale_plan/send_message skipped attachments=%s', skipped_attachments)

            if not body and not attachment_ids:
                return {'status': 'error', 'message': 'Empty message'}

            if body:
                if author_name:
                    safe_body = Markup('<p><strong>[%s]</strong> %s</p>') % (
                        Markup.escape(author_name), Markup.escape(body))
                else:
                    safe_body = Markup('<p>%s</p>') % Markup.escape(body)
            elif author_name:
                safe_body = Markup('<p><strong>[%s]</strong> gửi tệp đính kèm</p>') % Markup.escape(author_name)
            else:
                safe_body = Markup('<p>Gửi tệp đính kèm</p>')

            posted_msg = so.message_post(
                body=safe_body,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
                attachment_ids=attachment_ids,
            )
            # Edge/engine variations can cause attachment_ids to be ignored by message_post in some flows.
            # Enforce the link to the created mail.message as a safety net.
            if attachment_ids and posted_msg:
                missing_ids = [aid for aid in attachment_ids if aid not in posted_msg.attachment_ids.ids]
                if missing_ids:
                    posted_msg.sudo().write({'attachment_ids': [(4, aid) for aid in missing_ids]})
            preview = _normalize_preview_text(body or 'Tệp đính kèm')
            request.env['hlv.sale.plan.message'].sudo().upsert_for_sale_order(
              so,
              author_name=author_name or 'Khách hàng',
              preview=preview,
              message_type='customer',
            )
            # Kích hoạt trạng thái nháy đỏ Notification FB 
            if hasattr(so, 'x_plan_unread_message'):
                so.sudo().write({'x_plan_unread_message': True})
            
            # Send real-time bus notification to the delivery planner dashboard
            try:
              payload = {
                'so_id': so.id,
                'so_name': so.name,
                'author_name': author_name or 'Khách hàng',
                'body': body,
              }
              bus = request.env['bus.bus'].sudo()

              # Primary: channel notification for dashboard subscribers.
              # Odoo on this server expects _sendone(channel, type, message).
              bus._sendone('delivery_planner_channel', 'new_portal_message', payload)

              # Fallback: push directly to all internal users (share=False).
              internal_partners = request.env['res.users'].sudo().search([
                ('share', '=', False),
                ('active', '=', True),
              ]).mapped('partner_id')
              if internal_partners:
                try:
                  bus._sendmany([
                    (partner, 'new_portal_message', payload)
                    for partner in internal_partners
                  ])
                except Exception:
                  for partner in internal_partners:
                    bus._sendone(partner, 'new_portal_message', payload)
            except Exception as e:
                _logger.warning(f"Delivery Planner Bus send error: {e}")

            return {'status': 'success'}
        except Exception as e:
            _logger.exception('send_message error')
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/sale_plan/attachment/<int:att_id>', type='http', auth='public', methods=['GET'], csrf=False)
    def api_sale_plan_attachment(self, att_id, **kwargs):
        if not request.session.get(SESSION_KEY_OK):
            return request.redirect('/sale_plan')
        import base64
        att = request.env['ir.attachment'].sudo().browse(att_id)
        if not att.exists() or not att.datas:
            return request.not_found()
        data = base64.b64decode(att.datas)
        headers = [
            ('Content-Type', att.mimetype or 'application/octet-stream'),
            ('Content-Disposition', 'inline; filename="%s"' % (att.name or 'file')),
            ('Content-Length', len(data)),
        ]
        return request.make_response(data, headers)

    @http.route('/api/sale_plan/export_excel', type='http', auth='public', methods=['GET'], csrf=False)
    def api_export_excel(self, **kwargs):
        if not request.session.get(SESSION_KEY_OK):
            return request.redirect('/sale_plan')

        import io
        try:
            import xlsxwriter
        except ImportError:
            from odoo.tools.misc import xlsxwriter

        STATUS_LABELS = {
            'stock_status': {
                'ready': 'Đủ hàng xuất',
                'partial_ready': 'Có hàng 1 phần',
                'out_of_stock': 'Không có hàng',
            },
            'packing_status': {
                'fully_packed': 'Đã đóng gói đủ',
                'unpacked': 'Có hàng chưa đóng gói',
                'waiting_stock': 'Không có hàng đóng',
                'printed_waiting': 'Đã in, chờ đóng gói',
                'packed_waiting_ship': 'Đã gói, chờ nhận giao',
                'delivered_today': 'Đã giao trong ngày',
                'shipping': 'Đang giao',
            },
            'delivery_status': {
                'full': 'Hoàn thành',
                'partial': 'Giao 1 phần',
                'pending': 'Chưa giao',
            },
            'real_delivery_status': {
                'full': 'Hoàn thành',
                'partial': 'Giao 1 phần',
                'pending': 'Chưa giao',
            },
        }

        try:
            result = request.env['hlv.delivery.planner.service'].sudo().get_dashboard_data(
                search_query=kwargs.get('search_query', ''),
                filter_warehouse_id=kwargs.get('filter_warehouse_id', 'all'),
                filter_delivery_status=kwargs.get('filter_delivery_status', 'all'),
                filter_stock_status=kwargs.get('filter_stock_status', 'all'),
                filter_packing_status=kwargs.get('filter_packing_status', 'all'),
                filter_date_from=kwargs.get('filter_date_from', ''),
                filter_date_to=kwargs.get('filter_date_to', ''),
                filter_po_date_from=kwargs.get('filter_po_date_from', ''),
                filter_po_date_to=kwargs.get('filter_po_date_to', ''),
                filter_po_status=kwargs.get('filter_po_status', 'all'),
                filter_done_date_from=kwargs.get('filter_done_date_from', ''),
                filter_done_date_to=kwargs.get('filter_done_date_to', ''),
                filter_saler_code=kwargs.get('filter_saler_code', ''),
                filter_htgh=kwargs.get('filter_htgh', ''),
                filter_delivery_type=kwargs.get('filter_delivery_type', 'all'),
                filter_tag_ids=kwargs.get('filter_tag_ids', ''),
                show_completed=bool(kwargs.get('show_completed', '')),
                limit=100000,
                offset=0,
            )

            orders = result.get('orders', [])

            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            sheet = workbook.add_worksheet('Tình trạng đơn hàng')

            header_fmt = workbook.add_format({
                'bold': True, 'bg_color': '#4472C4', 'font_color': '#FFFFFF',
                'border': 1, 'align': 'center', 'valign': 'vcenter',
                'font_size': 11, 'text_wrap': True,
            })
            cell_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10})
            money_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10, 'num_format': '#,##0'})
            date_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10, 'num_format': 'dd/mm/yyyy'})

            headers = [
                ('STT', 5), ('Đơn hàng', 15), ('Khách hàng', 25), ('Kho', 15),
                ('Mã NV MISA', 12), ('Ngày đặt hàng', 14), ('Ngày hẹn giao', 14),
                ('Tổng tiền', 15), ('Tình trạng kho', 18), ('Đóng gói', 18),
                ('Tiến độ giao', 18), ('TT giao thực tế', 18), ('HTGH', 15),
                ('Loại vận chuyển', 15), ('Địa chỉ giao', 30),
                ('Ghi Chú Odoo', 30), ('Đề xuất chuyển kho', 30), ('Tags', 20),
            ]

            for col, (name, width) in enumerate(headers):
                sheet.write(0, col, name, header_fmt)
                sheet.set_column(col, col, width)
            sheet.freeze_panes(1, 0)

            for row_idx, order in enumerate(orders, start=1):
                col = 0
                sheet.write(row_idx, col, row_idx, cell_fmt); col += 1
                sheet.write(row_idx, col, order.get('name', ''), cell_fmt); col += 1
                partner = order.get('partner_id')
                sheet.write(row_idx, col, partner[1] if partner else '', cell_fmt); col += 1
                wh = order.get('warehouse_id')
                sheet.write(row_idx, col, wh[1] if wh else '', cell_fmt); col += 1
                sheet.write(row_idx, col, order.get('x_studio_misa_saler_code', ''), cell_fmt); col += 1
                date_order = order.get('date_order', '')
                sheet.write(row_idx, col, date_order[:10] if date_order else '', date_fmt if date_order else cell_fmt); col += 1
                commit_date = order.get('commitment_date', '')
                sheet.write(row_idx, col, commit_date[:10] if commit_date else '', date_fmt if commit_date else cell_fmt); col += 1
                sheet.write(row_idx, col, order.get('amount_total', 0), money_fmt); col += 1
                stock_st = order.get('stock_status', '')
                sheet.write(row_idx, col, STATUS_LABELS['stock_status'].get(stock_st, stock_st), cell_fmt); col += 1
                pack_st = order.get('packing_status', '')
                sheet.write(row_idx, col, STATUS_LABELS['packing_status'].get(pack_st, pack_st), cell_fmt); col += 1
                del_st = order.get('delivery_status', '')
                sheet.write(row_idx, col, STATUS_LABELS['delivery_status'].get(del_st, del_st), cell_fmt); col += 1
                real_del = order.get('real_delivery_status', '')
                sheet.write(row_idx, col, STATUS_LABELS['real_delivery_status'].get(real_del, real_del), cell_fmt); col += 1
                sheet.write(row_idx, col, order.get('x_studio_htgh', ''), cell_fmt); col += 1
                sheet.write(row_idx, col, order.get('x_studio_delivery_type', ''), cell_fmt); col += 1
                sheet.write(row_idx, col, order.get('misa_shipping_address', ''), cell_fmt); col += 1
                sheet.write(row_idx, col, order.get('x_studio_ghi_ch_odoo', ''), cell_fmt); col += 1
                suggestions = order.get('transfer_suggestions', [])
                if suggestions:
                    parts = []
                    for s in suggestions:
                        src_names = ', '.join(
                            f"{src['from_warehouse_name']}({src['suggested_qty']})"
                            for src in s.get('sources', [])
                        )
                        parts.append(f"{s['product_name']} thiếu {s['shortage']}: {src_names}")
                    sheet.write(row_idx, col, '; '.join(parts), cell_fmt)
                else:
                    sheet.write(row_idx, col, '', cell_fmt)
                col += 1
                tags = order.get('tag_ids', [])
                tag_names = ', '.join(t[1] for t in tags) if tags else ''
                sheet.write(row_idx, col, tag_names, cell_fmt)

            workbook.close()
            output.seek(0)
            xlsx_data = output.read()

            return request.make_response(
                xlsx_data,
                headers=[
                    ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                    ('Content-Disposition', 'attachment; filename="Tinh_trang_don_hang.xlsx"'),
                    ('Content-Length', len(xlsx_data)),
                ],
            )
        except Exception as e:
            _logger.exception('sale_plan export_excel error')
            return request.make_response(
                f'Lỗi khi xuất Excel: {str(e)}',
                headers=[('Content-Type', 'text/plain; charset=utf-8')],
            )

    @http.route('/api/sale_plan/export_picking_excel', type='http', auth='public', methods=['GET'], csrf=False)
    def api_export_picking_excel(self, **kwargs):
        """Export OUT pickings (state=done) of the filtered sale orders.
        Bao gồm phiếu đã xuất kho hoàn toàn hoặc xuất kho 1 phần (tạo backorder)
        — tức là tất cả stock.picking có picking_type_code='outgoing' và state='done'
        thuộc các đơn hàng trong bộ lọc hiện tại.
        """
        if not request.session.get(SESSION_KEY_OK):
            return request.redirect('/sale_plan')

        import io
        try:
            import xlsxwriter
        except ImportError:
            from odoo.tools.misc import xlsxwriter

        try:
            # Lấy danh sách đơn hàng theo bộ lọc (dùng lại service hiện có)
            result = request.env['hlv.delivery.planner.service'].sudo().get_dashboard_data(
                search_query=kwargs.get('search_query', ''),
                filter_warehouse_id=kwargs.get('filter_warehouse_id', 'all'),
                filter_delivery_status=kwargs.get('filter_delivery_status', 'all'),
                filter_stock_status=kwargs.get('filter_stock_status', 'all'),
                filter_packing_status=kwargs.get('filter_packing_status', 'all'),
                filter_date_from=kwargs.get('filter_date_from', ''),
                filter_date_to=kwargs.get('filter_date_to', ''),
                filter_po_date_from=kwargs.get('filter_po_date_from', ''),
                filter_po_date_to=kwargs.get('filter_po_date_to', ''),
                filter_po_status=kwargs.get('filter_po_status', 'all'),
                filter_done_date_from=kwargs.get('filter_done_date_from', ''),
                filter_done_date_to=kwargs.get('filter_done_date_to', ''),
                filter_saler_code=kwargs.get('filter_saler_code', ''),
                filter_htgh=kwargs.get('filter_htgh', ''),
                filter_delivery_type=kwargs.get('filter_delivery_type', 'all'),
                filter_tag_ids=kwargs.get('filter_tag_ids', ''),
                show_completed=bool(kwargs.get('show_completed', '')),
                limit=100000,
                offset=0,
            )

            orders = result.get('orders', [])
            so_ids = [o['id'] for o in orders if o.get('id')]
            so_name_map = {o['id']: o.get('name', '') for o in orders}
            so_partner_map = {
                o['id']: (o['partner_id'][1] if o.get('partner_id') else '')
                for o in orders
            }
            so_delivery_map = {o['id']: (o.get('real_delivery_status') or o.get('delivery_status') or '') for o in orders}

            if not so_ids:
                return request.make_response(
                    'Không có đơn hàng nào phù hợp bộ lọc.',
                    headers=[('Content-Type', 'text/plain; charset=utf-8')],
                )

            # Truy vấn phiếu xuất kho (OUT) đã hoàn thành của các đơn hàng này.
            # Nếu người dùng chọn "Hoàn thành từ/đến", filter thêm trực tiếp
            # trên date_done của picking (input là giờ VN UTC+7 → chuyển sang UTC).
            Picking = request.env['stock.picking'].sudo()
            picking_domain = [
                ('sale_id', 'in', so_ids),
                ('picking_type_code', '=', 'outgoing'),
                ('state', '=', 'done'),
            ]
            done_from_raw = kwargs.get('filter_done_date_from', '') or ''
            done_to_raw = kwargs.get('filter_done_date_to', '') or ''
            if done_from_raw or done_to_raw:
                try:
                    import pytz as _pytz2
                    from datetime import datetime as _dt
                    _vn_tz = _pytz2.timezone('Asia/Ho_Chi_Minh')
                    if done_from_raw:
                        # VN 00:00:00 → UTC (trừ 7 tiếng)
                        _from_local = _vn_tz.localize(_dt.strptime(done_from_raw, '%Y-%m-%d'))
                        _from_utc = _from_local.astimezone(_pytz2.UTC)
                        picking_domain.append(('date_done', '>=', _from_utc.strftime('%Y-%m-%d %H:%M:%S')))
                    if done_to_raw:
                        # VN 23:59:59 → UTC (trừ 7 tiếng)
                        _to_local = _vn_tz.localize(_dt.strptime(done_to_raw + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
                        _to_utc = _to_local.astimezone(_pytz2.UTC)
                        picking_domain.append(('date_done', '<=', _to_utc.strftime('%Y-%m-%d %H:%M:%S')))
                except Exception as _tz_err:
                    _logger.warning('export_picking_excel: lỗi chuyển đổi timezone date_done: %s', _tz_err)
            pickings = Picking.search(picking_domain, order='date_done, sale_id, name')

            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            sheet = workbook.add_worksheet('Phiếu xuất kho')

            # Formats
            header_fmt = workbook.add_format({
                'bold': True, 'bg_color': '#C55A11', 'font_color': '#FFFFFF',
                'border': 1, 'align': 'center', 'valign': 'vcenter',
                'font_size': 11, 'text_wrap': True,
            })
            picking_hdr_fmt = workbook.add_format({
                'bold': True, 'bg_color': '#FFF2CC', 'font_color': '#7F6000',
                'border': 1, 'valign': 'vcenter', 'font_size': 10,
            })
            cell_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10})
            num_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10, 'num_format': '#,##0.##'})
            date_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10, 'num_format': 'dd/mm/yyyy hh:mm'})
            date_only_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10, 'num_format': 'dd/mm/yyyy'})

            SO_STATE_LABELS = {
                'draft': 'Nháp',
                'sent': 'Đã gửi báo giá',
                'sale': 'Đơn hàng',
                'done': 'Đã khóa',
                'cancel': 'Đã hủy',
            }
            DELIVERY_STATUS_LABELS = {
                'pending': 'Chưa giao',
                'unshipped': 'Chưa giao',
                'started': 'Đã bắt đầu',
                'partial': 'Giao 1 phần',
                'full': 'Đã giao đủ',
            }
            cancelled_fmt = workbook.add_format({
                'border': 1, 'valign': 'vcenter', 'font_size': 10,
                'font_color': '#C00000', 'bold': True,
            })

            money_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 10, 'num_format': '#,##0'})

            col_headers = [
                ('STT', 5),
                ('Mã phiếu XK', 16),
                ('Đơn hàng', 15),
                ('Trạng thái ĐH', 14),
                ('Tiến độ giao', 16),
                ('Khách hàng', 25),
                ('Kho', 15),
                ('Ngày hoàn thành', 17),
                ('Sản phẩm', 35),
                ('Mã sản phẩm', 16),
                ('ĐVT', 8),
                ('SL thực xuất', 12),
                ('Đơn giá', 14),
                ('TT thực xuất', 16),
                ('VAT', 12),
                ('TT + VAT', 16),
                ('Ghi chú phiếu', 25),
            ]

            for col_idx, (name, width) in enumerate(col_headers):
                sheet.write(0, col_idx, name, header_fmt)
                sheet.set_column(col_idx, col_idx, width)
            sheet.freeze_panes(1, 0)

            row = 1
            stt = 0

            try:
                user_tz = __import__('pytz').timezone('Asia/Ho_Chi_Minh')
                import pytz as _pytz
                utc_tz = _pytz.UTC
            except Exception:
                user_tz = None
                utc_tz = None

            for picking in pickings:
                # Lấy move lines đã done
                done_moves = picking.move_ids.filtered(lambda m: m.state == 'done')
                if not done_moves:
                    continue

                # Ngày hoàn thành picking
                date_done = picking.date_done
                date_done_str = ''
                if date_done:
                    try:
                        local_dt = date_done.replace(tzinfo=utc_tz).astimezone(user_tz)
                        date_done_str = local_dt.strftime('%d/%m/%Y %H:%M')
                    except Exception:
                        date_done_str = str(date_done)

                so_id = picking.sale_id.id if picking.sale_id else False
                so_name = so_name_map.get(so_id, picking.sale_id.name if picking.sale_id else '')
                so_state_raw = picking.sale_id.state if picking.sale_id else ''
                so_state_label = SO_STATE_LABELS.get(so_state_raw, so_state_raw)
                del_status_raw = so_delivery_map.get(so_id, '')
                del_status_label = DELIVERY_STATUS_LABELS.get(del_status_raw, del_status_raw)
                partner_name = so_partner_map.get(so_id, '')
                wh_name = picking.location_id.warehouse_id.name if picking.location_id.warehouse_id else ''
                note = picking.note or ''

                for move in done_moves:
                    stt += 1
                    product = move.product_id
                    product_name = product.name if product else ''
                    product_code = product.default_code or '' if product else ''
                    uom_name = move.product_uom.name if move.product_uom else ''
                    qty_demand = move.product_uom_qty or 0
                    qty_done = getattr(move, 'quantity', None) or getattr(move, 'quantity_done', None) or 0

                    # Price / financial from sale order line
                    sol = move.sale_line_id
                    if sol:
                        price_unit = sol.price_unit
                        discount = sol.discount
                        price_after_disc = price_unit * (1.0 - discount / 100.0)
                        if qty_done > 0:
                            if sol.tax_id:
                                _tax_res = sol.tax_id.with_context(round=False).compute_all(
                                    price_after_disc,
                                    currency=sol.order_id.currency_id,
                                    quantity=qty_done,
                                    product=sol.product_id,
                                    partner=sol.order_id.partner_shipping_id,
                                )
                                line_subtotal = _tax_res['total_excluded']
                                line_tax = sum(t['amount'] for t in _tax_res['taxes'])
                                line_total = _tax_res['total_included']
                            else:
                                line_subtotal = price_after_disc * qty_done
                                line_tax = 0.0
                                line_total = line_subtotal
                        else:
                            price_unit = discount = line_subtotal = line_tax = line_total = 0.0
                    else:
                        price_unit = discount = line_subtotal = line_tax = line_total = 0.0

                    c = 0
                    sheet.write(row, c, stt, cell_fmt); c += 1
                    sheet.write(row, c, picking.name or '', cell_fmt); c += 1
                    sheet.write(row, c, so_name, cell_fmt); c += 1
                    _state_fmt = cancelled_fmt if so_state_raw == 'cancel' else cell_fmt
                    sheet.write(row, c, so_state_label, _state_fmt); c += 1
                    sheet.write(row, c, del_status_label, cell_fmt); c += 1
                    sheet.write(row, c, partner_name, cell_fmt); c += 1
                    sheet.write(row, c, wh_name, cell_fmt); c += 1
                    sheet.write(row, c, date_done_str, cell_fmt); c += 1
                    sheet.write(row, c, product_name, cell_fmt); c += 1
                    sheet.write(row, c, product_code, cell_fmt); c += 1
                    sheet.write(row, c, uom_name, cell_fmt); c += 1
                    sheet.write(row, c, qty_done, num_fmt); c += 1
                    sheet.write(row, c, round(price_unit, 0), money_fmt); c += 1
                    sheet.write(row, c, round(line_subtotal, 0), money_fmt); c += 1
                    sheet.write(row, c, round(line_tax, 0), money_fmt); c += 1
                    sheet.write(row, c, round(line_total, 0), money_fmt); c += 1
                    sheet.write(row, c, note, cell_fmt)
                    row += 1

            workbook.close()
            output.seek(0)
            xlsx_data = output.read()

            return request.make_response(
                xlsx_data,
                headers=[
                    ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                    ('Content-Disposition', 'attachment; filename="Phieu_xuat_kho.xlsx"'),
                    ('Content-Length', len(xlsx_data)),
                ],
            )
        except Exception as e:
            _logger.exception('sale_plan export_picking_excel error')
            return request.make_response(
                f'Lỗi khi xuất phiếu xuất kho: {str(e)}',
                headers=[('Content-Type', 'text/plain; charset=utf-8')],
            )

    @http.route('/api/sale_plan/export_picking_simple_excel', type='http', auth='public', methods=['GET'], csrf=False)
    def api_export_picking_simple_excel(self, **kwargs):
        """Export giản lược OUT pickings (state=done) — mỗi hàng = 1 phiếu, không có dòng sản phẩm.
        Columns: Mã phiếu XK, Đơn hàng, Trạng thái phiếu, Trạng thái ĐH,
                 Kho, Ngày hoàn thành, Tổng tiền trước thuế, Tổng tiền sau thuế.
        """
        if not request.session.get(SESSION_KEY_OK):
            return request.redirect('/sale_plan')

        try:
            result = request.env['hlv.delivery.planner.service'].sudo().get_dashboard_data(
                search_query=kwargs.get('search_query', ''),
                filter_warehouse_id=kwargs.get('filter_warehouse_id', 'all'),
                filter_delivery_status=kwargs.get('filter_delivery_status', 'all'),
                filter_stock_status=kwargs.get('filter_stock_status', 'all'),
                filter_packing_status=kwargs.get('filter_packing_status', 'all'),
                filter_date_from=kwargs.get('filter_date_from', ''),
                filter_date_to=kwargs.get('filter_date_to', ''),
                filter_po_date_from=kwargs.get('filter_po_date_from', ''),
                filter_po_date_to=kwargs.get('filter_po_date_to', ''),
                filter_po_status=kwargs.get('filter_po_status', 'all'),
                filter_done_date_from=kwargs.get('filter_done_date_from', ''),
                filter_done_date_to=kwargs.get('filter_done_date_to', ''),
                filter_saler_code=kwargs.get('filter_saler_code', ''),
                filter_htgh=kwargs.get('filter_htgh', ''),
                filter_delivery_type=kwargs.get('filter_delivery_type', 'all'),
                filter_tag_ids=kwargs.get('filter_tag_ids', ''),
                show_completed=bool(kwargs.get('show_completed', '')),
                limit=100000,
                offset=0,
            )

            orders = result.get('orders', [])
            so_ids = [o['id'] for o in orders if o.get('id')]
            so_name_map = {o['id']: o.get('name', '') for o in orders}
            so_state_map = {o['id']: o.get('state', '') for o in orders}

            if not so_ids:
                return request.make_response(
                    'Không có đơn hàng nào phù hợp bộ lọc.',
                    headers=[('Content-Type', 'text/plain; charset=utf-8')],
                )

            picking_domain = [
                ('sale_id', 'in', so_ids),
                ('picking_type_code', '=', 'outgoing'),
                ('state', '=', 'done'),
            ]
            done_from_raw = kwargs.get('filter_done_date_from', '') or ''
            done_to_raw = kwargs.get('filter_done_date_to', '') or ''
            if done_from_raw or done_to_raw:
                try:
                    import pytz as _pytz2
                    from datetime import datetime as _dt
                    _vn_tz = _pytz2.timezone('Asia/Ho_Chi_Minh')
                    if done_from_raw:
                        _from_local = _vn_tz.localize(_dt.strptime(done_from_raw, '%Y-%m-%d'))
                        _from_utc = _from_local.astimezone(_pytz2.UTC)
                        picking_domain.append(('date_done', '>=', _from_utc.strftime('%Y-%m-%d %H:%M:%S')))
                    if done_to_raw:
                        _to_local = _vn_tz.localize(_dt.strptime(done_to_raw + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
                        _to_utc = _to_local.astimezone(_pytz2.UTC)
                        picking_domain.append(('date_done', '<=', _to_utc.strftime('%Y-%m-%d %H:%M:%S')))
                except Exception as _tz_err:
                    _logger.warning('export_picking_simple_excel: lỗi chuyển đổi timezone: %s', _tz_err)

            pickings = request.env['stock.picking'].sudo().search(
                picking_domain, order='date_done, sale_id, name'
            )

            xlsx_data = build_picking_summary_xlsx(pickings, so_name_map, so_state_map)

            return request.make_response(
                xlsx_data,
                headers=[
                    ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                    ('Content-Disposition', 'attachment; filename="Phieu_xuat_kho_tom_tat.xlsx"'),
                    ('Content-Length', len(xlsx_data)),
                ],
            )
        except Exception as e:
            _logger.exception('sale_plan export_picking_simple_excel error')
            return request.make_response(
                f'Lỗi khi xuất phiếu xuất kho (tóm tắt): {str(e)}',
                headers=[('Content-Type', 'text/plain; charset=utf-8')],
            )
