# -*- coding: utf-8 -*-
import base64
import json
import logging
import os
import re
import time
import pytz
from markupsafe import Markup
from odoo import http, fields
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
    r'|Đơn hàng được tạo'
    r'|Đơn hàng tách kiện'
    r'|Assign người đóng gói'
    r'|Đổi người đóng gói'
    r'|In phiếu lấy hàng'
    r'|Nhu cầu ban đầu đã được cập nhật'
    r'|Nhu cầu ban đầu đã được'
    r'|The initial demand has'
    r'|The ordered quantity has been updated'
    r'|extra line with'
    r'|Đồng bộ MISA thành công'
    r'|Đã đồng bộ SO lines'
    r'|Odoo sẽ tự tạo picking'
    r'|Đã đồng bộ MISA tại chỗ; giữ nguyên SO và các phiếu kho hiện có'
    r'|Kho \([^)]+\) đã duyệt thay đổi số lượng MISA cho đơn'
    r'|thay đổi số lượng trên MISA và đang chờ kho duyệt'
    r'|Sale bắt đầu chỉnh sửa đơn .+ trên CRM\. Phiếu OUT tạm khóa xác nhận'
    r'|Đã đồng bộ MISA và tạo lại chuỗi phiếu kho theo kho'
    r'|🖨️'
    r'|👤'
    r'|🔄'
    r'|Lá»‡nh chuyá»ƒn hÃ ng Ä‘Æ°á»£c táº¡o'
    r'|lá»‡nh chuyá»ƒn hÃ ng Ä‘Ã£ Ä‘Æ°á»£c táº¡o ra tá»«'
    r'|Äá»“ng bá»™ \(xoÃ¡ .{0,5} táº¡o láº¡i\) thÃ nh cÃ´ng'
    r'|ÄÆ¡n hÃ ng Ä‘Æ°á»£c táº¡o'
    r'|ÄÆ¡n hÃ ng tÃ¡ch kiá»‡n'
    r'|Nhu cáº§u ban Ä‘áº§u Ä‘Ã£ Ä‘Æ°á»£c'
    r'|Äá»“ng bá»™ MISA thÃ nh cÃ´ng'
    r'|ðŸ–¨ï¸'
    r'|ðŸ‘¤'
    r'|ðŸ”„',
    re.IGNORECASE
)
_logger = logging.getLogger(__name__)

WEBPUSH_PUBLIC_PARAM = 'hlv_sale_delivery_planning.webpush_vapid_public_key'
WEBPUSH_PRIVATE_PARAM = 'hlv_sale_delivery_planning.webpush_vapid_private_key'
WEBPUSH_SUBJECT_PARAM = 'hlv_sale_delivery_planning.webpush_vapid_subject'


def _webpush_b64url(data):
  return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _get_or_create_webpush_vapid(env):
  ICP = env['ir.config_parameter'].sudo()
  public_key = ICP.get_param(WEBPUSH_PUBLIC_PARAM, '') or ''
  private_key = ICP.get_param(WEBPUSH_PRIVATE_PARAM, '') or ''
  if public_key and private_key:
    return public_key, private_key
  try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
  except Exception:
    _logger.warning('Web Push disabled: cryptography is not installed')
    return '', ''
  key = ec.generate_private_key(ec.SECP256R1())
  public_key = _webpush_b64url(key.public_key().public_bytes(
    serialization.Encoding.X962,
    serialization.PublicFormat.UncompressedPoint,
  ))
  private_key = key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
  ).decode('ascii')
  ICP.set_param(WEBPUSH_PUBLIC_PARAM, public_key)
  ICP.set_param(WEBPUSH_PRIVATE_PARAM, private_key)
  ICP.set_param(WEBPUSH_SUBJECT_PARAM, ICP.get_param(WEBPUSH_SUBJECT_PARAM, '') or 'mailto:admin@example.com')
  return public_key, private_key


def _send_sale_plan_webpush(env, subscriptions, payload):
  subscriptions = subscriptions.sudo().filtered(lambda s: s.active and s.subscription_json)
  if not subscriptions:
    return 0
  public_key, private_key = _get_or_create_webpush_vapid(env)
  if not public_key or not private_key:
    return 0
  try:
    from pywebpush import WebPushException, webpush
  except Exception:
    _logger.warning('Web Push disabled: pywebpush is not installed')
    return 0
  subject = env['ir.config_parameter'].sudo().get_param(WEBPUSH_SUBJECT_PARAM, '') or 'mailto:admin@example.com'
  data = json.dumps(payload, ensure_ascii=False)
  sent = 0
  seen_endpoints = set()
  for sub in subscriptions:
    endpoint_key = sub.endpoint_hash or sub.endpoint or str(sub.id)
    if endpoint_key in seen_endpoints:
      continue
    seen_endpoints.add(endpoint_key)
    try:
      webpush(
        subscription_info=json.loads(sub.subscription_json or '{}'),
        data=data,
        vapid_private_key=private_key,
        vapid_claims={'sub': subject},
      )
      sent += 1
    except WebPushException as exc:
      status = getattr(getattr(exc, 'response', None), 'status_code', None)
      if status in (404, 410):
        sub.sudo().write({'active': False})
      else:
        _logger.warning('Sale Plan Web Push send failed: %s', exc)
    except Exception:
      _logger.exception('Sale Plan Web Push send error')
  return sent


def _push_public_mention_webpush(env, aliases, payload):
  aliases = [_normalize_mention_alias(a) for a in aliases if _normalize_mention_alias(a)]
  if not aliases:
    return 0
  subs = env['hlv.sale.plan.web.push.subscription'].sudo().search([
    ('active', '=', True),
    ('alias', 'in', aliases),
  ])
  return _send_sale_plan_webpush(env, subs, {
    'type': 'sale_plan_mention',
    'title': 'Có tin nhắn mới ' + (payload.get('author_name') or ''),
    'body': '%s: %s' % (payload.get('so_name') or 'Sale order', payload.get('preview') or ''),
    'url': '/sale_plan',
    'so_id': payload.get('so_id'),
    'so_name': payload.get('so_name'),
    'tag': 'sale-plan-mention-%s' % (payload.get('id') or int(time.time())),
  })


def _push_backend_message_webpush(env, payload):
  subs = env['hlv.sale.plan.web.push.subscription'].sudo().search([
    ('active', '=', True),
    ('backend_messages', '=', True),
  ])
  return _send_sale_plan_webpush(env, subs, {
    'type': 'new_portal_message',
    'title': 'Có tin nhắn mới ' + (payload.get('author_name') or ''),
    'body': 'Đơn hàng %s: %s' % (payload.get('so_name') or '', _normalize_preview_text(payload.get('body') or '', 100)),
    'url': '/web',
    'so_id': payload.get('so_id'),
    'so_name': payload.get('so_name'),
    'tag': 'delivery-planner-message-%s' % (payload.get('message_id') or payload.get('so_id') or int(time.time())),
  })

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


_PUBLIC_MENTION_SEQ = 0
_MENTION_RE = re.compile(r'@([^\s@,;:!?()\[\]{}<>]+)')


def _normalize_mention_alias(value):
  return (value or '').strip().lower().lstrip('@')


def _split_mention_aliases(value):
  aliases = []
  for part in (value or '').split(','):
    alias = _normalize_mention_alias(part)
    if alias and alias not in aliases:
      aliases.append(alias)
  return aliases


def _extract_configured_mentions(text, valid_aliases):
  text = text or ''
  valid_aliases = sorted({_normalize_mention_alias(a) for a in valid_aliases if _normalize_mention_alias(a)}, key=len, reverse=True)
  found = []
  used_spans = []
  lowered = text.lower()
  for alias in valid_aliases:
    pattern = re.compile(r'(^|\s)@' + re.escape(alias) + r'(?=$|[\s,;:!?()\[\]{}<>])', re.IGNORECASE)
    for match in pattern.finditer(lowered):
      start = match.start() + len(match.group(1))
      end = match.end()
      if any(not (end <= a or start >= b) for a, b in used_spans):
        continue
      used_spans.append((start, end))
      if alias not in found:
        found.append(alias)
  return found


def _format_message_body_with_mentions(text, valid_aliases=None):
  text = text or ''
  ranges = []
  if valid_aliases:
    aliases = sorted({_normalize_mention_alias(a) for a in valid_aliases if _normalize_mention_alias(a)}, key=len, reverse=True)
    lowered = text.lower()
    for alias in aliases:
      pattern = re.compile(r'(^|\s)@' + re.escape(alias) + r'(?=$|[\s,;:!?()\[\]{}<>])', re.IGNORECASE)
      for match in pattern.finditer(lowered):
        start = match.start() + len(match.group(1))
        end = match.end()
        if any(not (end <= a or start >= b) for a, b in ranges):
          continue
        ranges.append((start, end))
  else:
    ranges = [(m.start(), m.end()) for m in _MENTION_RE.finditer(text)]
  ranges.sort()
  parts = []
  last = 0
  for start, end in ranges:
    parts.append(Markup.escape(text[last:start]))
    parts.append(Markup('<strong class="sale-plan-mention">%s</strong>') % Markup.escape(text[start:end]))
    last = end
  parts.append(Markup.escape(text[last:]))
  return Markup('').join(parts)

def _get_sale_plan_alias_rows(env):
  users = env['res.users'].sudo().search([
    ('active', '=', True),
    ('x_sale_plan_mention_names', '!=', False),
  ])
  rows = []
  seen = set()
  for user in users:
    for part in (user.x_sale_plan_mention_names or '').split(','):
      display_alias = (part or '').strip().lstrip('@')
      alias = _normalize_mention_alias(display_alias)
      if not alias or alias in seen:
        continue
      seen.add(alias)
      rows.append({
        'alias': alias,
        'display_alias': display_alias,
        'user_id': user.id,
        'user_name': user.name or '',
      })
  rows.sort(key=lambda row: row['alias'])
  return rows


def _get_user_sale_plan_aliases(user):
  try:
    if not user or user._is_public():
      return []
  except Exception:
    return []
  return _split_mention_aliases(getattr(user, 'x_sale_plan_mention_names', '') or '')


def _push_public_mention_event(env, so, body, author_name=''):
  global _PUBLIC_MENTION_SEQ
  valid_aliases = {row['alias'] for row in _get_sale_plan_alias_rows(env)}
  matched = _extract_configured_mentions(body, valid_aliases)
  if not matched:
    return None
  _PUBLIC_MENTION_SEQ += 1
  notif_model = env['hlv.sale.plan.mention.notification'].sudo()
  records = notif_model.browse()
  preview = _normalize_preview_text(body or '')
  mentions_csv = ','.join(matched)
  for alias in matched:
    records |= notif_model.create({
      'alias': alias,
      'sale_order_id': so.id,
      'so_name': so.name or '',
      'author_name': author_name or '',
      'body': body or '',
      'preview': preview,
      'mentions': mentions_csv,
      'is_read': False,
    })
  payload = {
    'id': _PUBLIC_MENTION_SEQ,
    'type': 'sale_plan_mention',
    'notification_ids': records.ids,
    'notification_id_by_alias': {rec.alias: rec.id for rec in records},
    'so_id': so.id,
    'so_name': so.name or '',
    'author_name': author_name or '',
    'body': body or '',
    'preview': preview,
    'mentions': matched,
    'ts': int(time.time()),
  }
  try:
    env['bus.bus'].sudo()._sendone('sale_plan_public_channel', 'sale_plan_mention', payload)
  except Exception:
    _logger.exception('sale_plan public mention bus send error')
  try:
    _push_public_mention_webpush(env, matched, payload)
  except Exception:
    _logger.exception('sale_plan public mention webpush send error')
  return payload



_H = [
    ("Content-Type", "text/html; charset=utf-8"),
    # Chống browser/proxy cache nguyên trang HTML chứa inline JS.
    # Nếu thiếu, sau khi server cập nhật _PAGE, client cũ chạy JS lệch
    # với backend → search "không ra" cho đến khi user Ctrl+F5.
    ("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"),
    ("Pragma", "no-cache"),
    ("Expires", "0"),
]

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
.so-card{border:1px solid #e5e7eb!important;transition:.15s;box-shadow:none!important;position:relative;overflow:hidden}
.so-card:hover{border-color:#a5b4fc!important;box-shadow:0 2px 8px rgba(99,102,241,.1)!important}
.misa-lock-ribbon{position:absolute;top:0;left:0;right:0;z-index:3;padding:4px 8px;background:#b45309;color:#fff;text-align:center;font-size:.62rem;font-weight:700;letter-spacing:.35px;box-shadow:0 1px 4px rgba(0,0,0,.2)}
.so-card .misa-lock-card-header{padding-top:2rem!important}
/* Drawer */
#drawer{position:fixed;top:0;right:-1020px;width:1000px;height:100vh;background:#fff;
  border-left:1px solid #e5e7eb;box-shadow:-8px 0 32px rgba(0,0,0,.06);z-index:1060;transition:right .3s;overflow-y:auto}
#drawer.open{right:0}
#drawer-overlay{display:none;position:fixed;inset:0;background:rgba(15,23,42,.2);z-index:1055}
#drawer-overlay.open{display:block}
/* Print queue drawer (trái) */
#print-queue-drawer{position:fixed;top:0;left:-460px;width:440px;height:100vh;background:#fff;
  border-right:1px solid #e5e7eb;box-shadow:8px 0 32px rgba(0,0,0,.06);z-index:1065;transition:left .3s;overflow-y:auto;display:flex;flex-direction:column}
#print-queue-drawer.open{left:0}
#print-queue-drawer-overlay{display:none;position:fixed;inset:0;background:rgba(15,23,42,.2);z-index:1060}
#print-queue-drawer-overlay.open{display:block}
#print-queue-body{flex:1;overflow-y:auto}
.pq-item{padding:10px 14px;border-bottom:1px solid #f1f5f9;font-size:.8rem}
.pq-item .pq-title{font-weight:800;color:#0f172a}
.pq-item .pq-meta{color:#64748b;font-size:.74rem;margin-top:2px}
.pq-item .pq-error{color:#b91c1c;font-size:.74rem;margin-top:4px}
.pq-badge{font-size:.66rem;font-weight:800;border-radius:999px;padding:2px 8px;color:#fff}
.pq-badge.pending,.pq-badge.printing{background:#d97706}
.pq-badge.printed{background:#16a34a}
.pq-badge.error{background:#dc2626}
.pq-badge.cancelled{background:#64748b}
#print-queue-printer-status{padding:8px 14px;border-bottom:1px solid #f1f5f9;background:#f8fafc;
  display:flex;flex-wrap:wrap;gap:6px}
.pq-printer-chip{font-size:.7rem;font-weight:700;border-radius:999px;padding:3px 10px;
  display:inline-flex;align-items:center;gap:5px;border:1px solid transparent}
.pq-printer-chip.online{background:#dcfce7;color:#166534;border-color:#bbf7d0}
.pq-printer-chip.offline{background:#fee2e2;color:#991b1b;border-color:#fecaca}
.pq-printer-chip .dot{width:7px;height:7px;border-radius:50%;display:inline-block}
.pq-printer-chip.online .dot{background:#22c55e}
.pq-printer-chip.offline .dot{background:#ef4444}
@media(max-width:1024px){#print-queue-drawer{width:100%!important;left:-105%!important}}
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

.sale-plan-mention{color:#4f46e5;font-weight:800}
.mention-noti-wrap{position:relative;display:flex;align-items:center}
#mention-noti-button,#print-queue-button{border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.08);color:#fff;border-radius:6px;padding:6px 10px;font-size:.78rem;font-weight:700;line-height:1;display:inline-flex;align-items:center;gap:7px}
#mention-noti-button.has-unread{background:#4f46e5;border-color:#818cf8;color:#fff}
#print-queue-button.has-error{background:#dc2626;border-color:#f87171;color:#fff}
#print-queue-button.has-pending{background:#d97706;border-color:#fbbf24;color:#fff}
#mention-browser-noti-button{border:1px solid #cbd5e1;background:#fff;color:#475569;border-radius:6px;padding:5px 8px;font-size:.72rem;font-weight:800;line-height:1;display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
#mention-browser-noti-button.enabled{background:#f0fdf4;border-color:#bbf7d0;color:#166534}
#mention-browser-noti-button.blocked{background:#fff7ed;border-color:#fed7aa;color:#9a3412}
.mention-webpush-help{display:none;margin:8px 10px 0;padding:8px 10px;border:1px solid #fed7aa;background:#fff7ed;color:#7c2d12;border-radius:6px;font-size:.74rem;line-height:1.35}
.mention-webpush-help.open{display:block}
#mention-noti-count,#print-queue-count{min-width:18px;height:18px;border-radius:9px;background:#ef4444;color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:.68rem;font-weight:800;padding:0 5px}
#mention-noti-panel{position:absolute;right:0;top:calc(100% + 8px);z-index:3150;width:min(390px,calc(100vw - 32px));max-height:420px;overflow-y:auto;background:#fff;border:1px solid #e2e8f0;border-radius:8px;box-shadow:0 18px 40px rgba(15,23,42,.22);display:none;color:#0f172a}
#mention-noti-panel.open{display:block}
.mention-noti-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:.78rem;font-weight:800;color:#0f172a}
.mention-noti-actions{display:flex;align-items:center;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.mention-noti-actions button{border:0;background:transparent;color:#64748b;font-size:.72rem;font-weight:700;padding:2px 4px}
.mention-noti-item{padding:10px 12px;border-bottom:1px solid #f1f5f9;cursor:pointer;font-size:.8rem;text-align:left}
.mention-noti-item:hover{background:#f8fafc}
.mention-noti-item.unread{background:#eef2ff}
.mention-noti-item-title{font-weight:800;color:#0f172a;margin-bottom:3px}
.mention-noti-item-body{color:#475569;line-height:1.4;word-break:break-word}
.mention-noti-empty{padding:18px 12px;text-align:center;color:#94a3b8;font-size:.8rem}
.mention-noti-more{width:calc(100% - 20px);margin:8px 10px 10px;border:1px solid #c7d2fe;background:#eef2ff;color:#4338ca;border-radius:6px;padding:7px 10px;font-size:.76rem;font-weight:800}
.mention-noti-more:hover{background:#e0e7ff}

.mention-noti-tabs{display:flex;gap:6px;flex-wrap:wrap;padding:8px 10px;border-bottom:1px solid #e2e8f0;background:#f8fafc}
.mention-noti-alias-tab{border:1px solid #cbd5e1;background:#fff;color:#334155;border-radius:999px;padding:3px 8px;font-size:.7rem;font-weight:800;cursor:pointer}
.mention-noti-alias-tab.active{background:#4f46e5;border-color:#4f46e5;color:#fff}
.mention-noti-alias-tab .count{display:inline-flex;align-items:center;justify-content:center;min-width:16px;height:16px;border-radius:8px;background:#ef4444;color:#fff;font-size:.62rem;margin-left:4px;padding:0 4px}
.public-mention-suggest{position:absolute;left:0;right:0;top:calc(100% + 4px);z-index:3200;background:#fff;border:1px solid #c7d2fe;border-radius:6px;box-shadow:0 12px 30px rgba(15,23,42,.16);max-height:360px;overflow-y:auto;display:none}
.public-mention-suggest.open{display:block}
.public-mention-suggest-item{padding:8px 10px;font-size:.8rem;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:8px}
.public-mention-suggest-item:hover,.public-mention-suggest-item.active{background:#eef2ff}
.public-mention-suggest-item strong{color:#4f46e5}
.public-mention-suggest-item small{color:#64748b;font-size:.68rem}
.mention-toast-stack{position:fixed;right:16px;top:72px;z-index:3400;display:flex;flex-direction:column;gap:8px;width:min(360px,calc(100vw - 32px));pointer-events:none}
.mention-toast{pointer-events:auto;background:#fff;border-left:4px solid #4f46e5;border-radius:8px;box-shadow:0 14px 36px rgba(15,23,42,.22);padding:10px 12px;color:#0f172a;cursor:pointer;animation:mentionToastIn .16s ease-out}
.mention-toast-title{font-weight:800;font-size:.82rem;margin-bottom:3px}
.mention-toast-body{font-size:.78rem;color:#475569;line-height:1.35;word-break:break-word}
.mention-toast-close{float:right;border:0;background:transparent;color:#94a3b8;font-size:1rem;line-height:1;padding:0 0 4px 8px}
@keyframes mentionToastIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
/* Report button */
.btn-report{font-size:.68rem;padding:2px 8px;border:1px solid #fecaca;color:#dc2626;background:#fef2f2;border-radius:4px;cursor:pointer;transition:.15s;line-height:1.4;font-weight:500}
.btn-report:hover{background:#fee2e2;border-color:#dc2626}
/* Report modal */
#report-modal{display:none;position:fixed;inset:0;z-index:2000;background:rgba(0,0,0,.4);align-items:center;justify-content:center}
/* Picking detail modal (xem trước + xác nhận in) */
#pd-modal{display:none;position:fixed;inset:0;z-index:2100;background:rgba(0,0,0,.45);align-items:center;justify-content:center}
#pd-modal .pd-card{background:#fff;max-width:1200px;width:96%;max-height:96vh;border-radius:8px;box-shadow:0 12px 32px rgba(0,0,0,.18);display:flex;flex-direction:column;overflow:hidden}
#pd-modal .pd-header{padding:14px 18px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center}
#pd-modal .pd-tabs{display:flex;gap:4px;padding:8px 18px 0;border-bottom:1px solid #e5e7eb;background:#fafbfc}
#pd-modal .pd-tab{border:0;background:transparent;padding:8px 12px;font-size:.82rem;font-weight:700;color:#64748b;border-bottom:2px solid transparent;margin-bottom:-1px}
#pd-modal .pd-tab.active{color:#4f46e5;border-bottom-color:#4f46e5}
.pd-log-item{padding:8px 0;border-bottom:1px solid #f1f5f9;font-size:.8rem}
.pd-log-item .pd-log-meta{color:#94a3b8;font-size:.7rem;margin-bottom:2px}
.pd-log-item .pd-log-body{color:#334155}
#pd-modal .pd-body{padding:16px 18px;overflow-y:auto;flex:1}
#pd-modal .pd-footer{padding:12px 18px;border-top:1px solid #e5e7eb;display:flex;justify-content:flex-end;gap:8px}
/* PDF preview dialog — xem trước NGAY TRONG trang (đè lên pd-modal), không mở tab/điều hướng mới */
#pdfp-modal{display:none;position:fixed;inset:0;z-index:2200;background:rgba(0,0,0,.6);align-items:center;justify-content:center}
#pdfp-modal .pdfp-card{background:#fff;width:98%;max-width:1300px;height:97vh;border-radius:8px;box-shadow:0 12px 32px rgba(0,0,0,.25);display:flex;flex-direction:column;overflow:hidden}
#pdfp-modal .pdfp-header{padding:10px 14px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}
#pdfp-modal iframe{flex:1;border:0;width:100%}
#pdfp-modal .pdfp-footer{padding:10px 14px;border-top:1px solid #e5e7eb;display:flex;justify-content:flex-end;flex-shrink:0}
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
<iframe id="sale-plan-bus-frame" src="/sale_plan/bus_frame" style="display:none;width:0;height:0;border:0" aria-hidden="true"></iframe>
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
      <li class="nav-item ms-lg-2">
        <button id="print-queue-button" type="button" title="Yêu cầu in"><i class="fa fa-print"></i><span id="print-queue-count">0</span></button>
      </li>
      <li class="nav-item ms-lg-2 mention-noti-wrap">
        <button id="mention-noti-button" type="button" title="Thông báo"><i class="fa fa-bell"></i><span id="mention-noti-count">0</span></button>
        <div id="mention-noti-panel" aria-live="polite">
          <div class="mention-noti-head"><span>Thông báo</span><span class="mention-noti-actions"><button id="mention-browser-noti-button" type="button" title="Bật thông báo ngoài web"><i class="fa fa-bell"></i><span id="mention-browser-noti-label">Bật ngoài web</span></button><button id="mention-noti-read-all" type="button">Đã đọc hết</button><button id="mention-noti-clear" type="button">Xóa</button></span></div>
          <div id="mention-webpush-help" class="mention-webpush-help"></div>
          <div id="mention-noti-list"></div>
        </div>
      </li>
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
    <div class="col-md-3"><label class="form-label small fw-semibold text-muted mb-1">Tìm Kiếm</label><input id="f-q" class="form-control form-control-sm" placeholder="SO / Khách hàng / Tham chiếu Shopee..."/></div>
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
    <div class="form-check form-switch">
      <input class="form-check-input" type="checkbox" id="f-mine-only" checked>
      <label class="form-check-label small fw-bold" for="f-mine-only"><i class="fa fa-user text-primary me-1"></i>Đơn của tôi</label>
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
        <li><a class="dropdown-item" id="btn-export-picking-excel-dd" href="#" title="Xuất phiếu xuất kho (OUT đã xong)"><i class="fa fa-truck me-2"></i> Xuất phiếu XK</a></li>
        <li><a class="dropdown-item" id="btn-export-picking-simple-excel-dd" href="#" title="Xuất phiếu XK giản lược (không in dòng sản phẩm)"><i class="fa fa-file-text-o me-2"></i> Xuất phiếu XK (tóm tắt)</a></li>
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
  <th>Giao dự kiến</th><th>Tổng tiền</th><th>Giao hàng</th><th>Tồn kho</th><th>Đóng kiện</th><th>Thao tác</th>
</tr></thead><tbody id="tbl-body"></tbody>
</table></div></div>
</div>
<!-- Drawer overlay -->
<div id="mention-toast-stack" class="mention-toast-stack" aria-live="polite"></div>
<div id="drawer-overlay"></div>
<div id="drawer">
  <div class="p-3 border-bottom d-flex justify-content-between align-items-center bg-primary text-white">
    <h5 class="mb-0" id="dr-title"></h5>
    <div class="d-flex align-items-center gap-2">
      <button id="dr-close" class="btn btn-sm btn-light">&times;</button>
    </div>
  </div>
  <div id="dr-body" class="p-3"></div>
  <div class="p-3 border-top bg-light fw-bold" id="dr-footer"></div>
</div>
<!-- Print queue drawer -->
<div id="print-queue-drawer-overlay"></div>
<div id="print-queue-drawer">
  <div class="p-3 border-bottom d-flex justify-content-between align-items-center bg-info text-white">
    <h5 class="mb-0"><i class="fa fa-print me-2"></i>Yêu cầu in</h5>
    <button id="print-queue-close" class="btn btn-sm btn-light">&times;</button>
  </div>
  <div id="print-queue-printer-status"></div>
  <div class="mention-noti-tabs" id="print-queue-tabs"></div>
  <div id="print-queue-body"></div>
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
<!-- Picking detail modal: xem chi tiết phiếu PICK, xem trước rồi mới xác nhận in -->
<div id="pd-modal">
  <div class="pd-card">
    <div class="pd-header">
      <div>
        <h6 class="fw-bold mb-0" id="pd-title"></h6>
        <span class="badge mt-1" id="pd-state-badge"></span>
      </div>
      <button id="pd-close" class="btn btn-sm btn-light"><i class="fa fa-times"></i></button>
    </div>
    <div class="pd-tabs">
      <button type="button" class="pd-tab active" id="pd-tab-detail" data-pd-tab="detail">Chi tiết</button>
      <button type="button" class="pd-tab" id="pd-tab-log" data-pd-tab="log"><i class="fa fa-history me-1"></i>Nhật ký</button>
    </div>
    <div class="pd-body">
      <div id="pd-tabpane-detail">
        <div id="pd-lines"></div>
      </div>
      <div id="pd-tabpane-log" class="d-none"></div>
    </div>
    <div class="pd-footer" id="pd-footer-detail">
      <button class="btn btn-outline-primary btn-sm" id="pd-btn-preview"><i class="fa fa-eye me-1"></i>Xem trước</button>
      <button class="btn btn-success btn-sm d-none" id="pd-btn-confirm"><i class="fa fa-check me-1"></i>Gửi phiếu in cho kho</button>
    </div>
  </div>
</div>
<!-- PDF preview dialog: xem trước phiếu lấy hàng NGAY TRONG trang này (đè lên pd-modal), không
     mở tab mới, không điều hướng rời trang (giữ nguyên danh sách/tìm kiếm đang xem) -->
<div id="pdfp-modal">
  <div class="pdfp-card">
    <div class="pdfp-header">
      <h6 class="fw-bold mb-0">Xem trước phiếu lấy hàng</h6>
      <button id="pdfp-close" class="btn btn-sm btn-light"><i class="fa fa-times"></i></button>
    </div>
    <iframe id="pdfp-frame" src="about:blank"></iframe>
    <div class="pdfp-footer">
      <button class="btn btn-success btn-sm" id="pdfp-btn-confirm"><i class="fa fa-check me-1"></i>Gửi phiếu in cho kho</button>
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

var _sessionMentionAlias='';
var _sessionMentionAliases=[];
var _mentionLastId=0;
var _mentionSeen={};
var _mentionNotiItems=[];
var _mentionAliases=[];
var _mentionActiveIndex=0;
var _mentionActiveAlias='all';
var _mentionNotiVisible=20;
function normalizeMentionAlias(v){return String(v||'').trim().toLowerCase().replace(/^@+/,'');}
function getCurrentMentionAlias(){return normalizeMentionAlias(_sessionMentionAlias||'');}
function getCurrentMentionAliases(){return (_sessionMentionAliases||[]).map(normalizeMentionAlias).filter(Boolean);}
function aliasDisplay(alias){alias=normalizeMentionAlias(alias);var row=(_mentionAliases||[]).find(function(a){return normalizeMentionAlias(a.alias)===alias;});return (row&&(row.display_alias||row.alias))||alias;}
function eventMatchesCurrentAlias(ev){var aliases=getCurrentMentionAliases();if(!aliases.length)return false;var mentions=(ev&&ev.mentions)||[];return mentions.some(function(m){return aliases.indexOf(normalizeMentionAlias(m))!==-1;});}
function loadCurrentMentionAlias(){return fetch('/api/sale_plan/current_alias',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})}).then(function(r){return r.json();}).then(function(j){var d=j.result||{};_sessionMentionAliases=d.status==='success'?(d.aliases||[]):[];_sessionMentionAlias=_sessionMentionAliases[0]||'';}).catch(function(){_sessionMentionAlias='';_sessionMentionAliases=[];});}
function loadMentionNotiItems(){return fetch('/api/sale_plan/mention_notifications',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})}).then(function(r){return r.json();}).then(function(j){var d=j.result||{};_mentionNotiItems=d.status==='success'?(d.events||[]):[];_mentionSeen={};_mentionNotiItems.forEach(function(item){var id=String(item.notification_id||item.id||'');if(id)_mentionSeen[id]=true;});renderMentionNotiPanel();}).catch(function(){_mentionNotiItems=[];renderMentionNotiPanel();});}
function addMentionNotification(ev){if(!ev||!ev.id)return;var id=String(ev.notification_id||ev.id);var existing=_mentionNotiItems.find(function(x){return String(x.id)===id;});if(existing){existing.so_id=ev.so_id;existing.so_name=ev.so_name||existing.so_name||'';existing.author_name=ev.author_name||existing.author_name||'';existing.preview=ev.preview||ev.body||existing.preview||'';existing.mentions=ev.mentions||existing.mentions||[];existing.alias=ev.alias||existing.alias||'';existing.unread=ev.unread!==undefined?ev.unread:existing.unread;renderMentionNotiPanel();return;}var item={id:id,notification_id:ev.notification_id||ev.id,so_id:ev.so_id,so_name:ev.so_name||'',author_name:ev.author_name||'',preview:ev.preview||ev.body||'',mentions:ev.mentions||[],alias:ev.alias||'',unread:ev.unread!==undefined?ev.unread:true,ts:ev.ts||Date.now()};_mentionNotiItems.unshift(item);_mentionNotiItems=_mentionNotiItems.slice(0,100);renderMentionNotiPanel();}
function mentionItemHasAlias(item,alias){alias=normalizeMentionAlias(alias);var itemAlias=normalizeMentionAlias(item&&item.alias);if(itemAlias)return itemAlias===alias;return ((item&&item.mentions)||[]).map(normalizeMentionAlias).indexOf(alias)!==-1;}
function mentionUnreadCountForAlias(alias){return _mentionNotiItems.filter(function(x){return x.unread&&(alias==='all'||mentionItemHasAlias(x,alias));}).length;}
function renderMentionNotiPanel(){var btn=$('mention-noti-button'),cnt=$('mention-noti-count'),list=$('mention-noti-list');if(!btn||!cnt||!list)return;var aliases=getCurrentMentionAliases();if(_mentionActiveAlias!=='all'&&aliases.indexOf(_mentionActiveAlias)===-1)_mentionActiveAlias='all';var unread=mentionUnreadCountForAlias('all');cnt.textContent=String(unread||0);btn.classList.toggle('has-unread',unread>0);var tabs='<div class="mention-noti-tabs"><button type="button" class="mention-noti-alias-tab '+(_mentionActiveAlias==='all'?'active':'')+'" data-alias="all">Tất cả'+(unread?'<span class="count">'+unread+'</span>':'')+'</button>'+aliases.map(function(alias){var c=mentionUnreadCountForAlias(alias);return '<button type="button" class="mention-noti-alias-tab '+(_mentionActiveAlias===alias?'active':'')+'" data-alias="'+esc(alias)+'">@'+esc(aliasDisplay(alias))+(c?'<span class="count">'+c+'</span>':'')+'</button>';}).join('')+'</div>';var items=_mentionNotiItems.filter(function(item){return _mentionActiveAlias==='all'||mentionItemHasAlias(item,_mentionActiveAlias);});if(!items.length){list.innerHTML=tabs+'<div class="mention-noti-empty">Chua co thong bao</div>';return;}var visible=Math.max(20,_mentionNotiVisible||20);var shown=items.slice(0,visible);var moreCount=Math.max(0,items.length-shown.length);var html=tabs+shown.map(function(item){var tags=(item.mentions||[]).map(function(a){return '<span class="badge bg-light text-primary border me-1">@'+esc(aliasDisplay(a))+'</span>';}).join('');return '<div class="mention-noti-item '+(item.unread?'unread':'')+'" data-id="'+esc(item.id)+'" data-so-id="'+esc(item.so_id)+'" data-so-name="'+esc(item.so_name)+'"><div class="mention-noti-item-title">'+esc(item.so_name||'Sale order')+'</div><div class="mention-noti-item-body"><strong>'+esc(item.author_name||'')+'</strong>: '+esc(item.preview||'')+'</div><div class="mt-1">'+tags+'</div></div>';}).join('');if(moreCount)html+='<button type="button" class="mention-noti-more">Xem thêm '+moreCount+' thông báo</button>';list.innerHTML=html;}
function markMentionNotificationRead(id){var item=_mentionNotiItems.find(function(x){return String(x.id)===String(id);});if(item)item.unread=false;renderMentionNotiPanel();fetch('/api/sale_plan/mention_notifications/read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{notification_ids:[id]}})}).then(function(r){return r.json();}).then(function(j){var d=j.result||{};if(d.status==='success')_mentionNotiItems=d.events||_mentionNotiItems;renderMentionNotiPanel();}).catch(function(){});}
function openOrderFromNotification(soId,soName){soId=parseInt(soId,10)||0;var local=S.orders.find(function(o){return o.id===soId;});if(local){openDrawer(soId);return;}showLoading();fetch('/api/sale_plan/data',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{search:soName||'',warehouse_id:'all',delivery_status:'all',stock_status:'all',packing_status:'all',date_from:'',date_to:'',po_date_from:'',po_date_to:'',done_date_from:'',done_date_to:'',po_status:'all',saler_code:'',htgh:'',delivery_type:'all',tag_ids:'',show_completed:true,limit:20,offset:0}})}).then(function(r){return r.json();}).then(function(j){hideLoading();var d=j.result&&j.result.data;var order=d&&d.orders&&(d.orders.find(function(o){return o.id===soId;})||d.orders[0]);if(order){var exists=S.orders.find(function(o){return o.id===order.id;});if(!exists)S.orders.unshift(order);openDrawer(order.id);}}).catch(function(){hideLoading();});}
function playMentionSound(){try{var Ctx=window.AudioContext||window.webkitAudioContext;if(!Ctx)return;var ctx=window._salePlanMentionAudioCtx||(window._salePlanMentionAudioCtx=new Ctx());if(ctx.state==='suspended')ctx.resume();var now=ctx.currentTime;[660,880].forEach(function(freq,i){var osc=ctx.createOscillator();var gain=ctx.createGain();osc.type='sine';osc.frequency.value=freq;gain.gain.setValueAtTime(0.0001,now+i*0.1);gain.gain.exponentialRampToValueAtTime(0.055,now+i*0.1+0.02);gain.gain.exponentialRampToValueAtTime(0.0001,now+i*0.1+0.12);osc.connect(gain);gain.connect(ctx.destination);osc.start(now+i*0.1);osc.stop(now+i*0.1+0.14);});}catch(e){}}
function browserNotificationsSupported(){return 'Notification' in window&&'serviceWorker' in navigator&&'PushManager' in window&&window.isSecureContext;}
function setWebPushHelp(message){var box=$('mention-webpush-help');if(!box)return;if(message){box.innerHTML=message;box.classList.add('open');}else{box.innerHTML='';box.classList.remove('open');}}
function browserName(){var ua=navigator.userAgent||'';if(ua.indexOf('Edg/')>=0)return 'Edge';if(ua.indexOf('OPR/')>=0||ua.indexOf('Opera')>=0)return 'Opera';if(ua.indexOf('Chrome/')>=0)return 'Chrome';return 'trình duyệt';}
function updateBrowserNotiButton(){var btn=$('mention-browser-noti-button'),label=$('mention-browser-noti-label');if(!btn)return;btn.classList.remove('enabled','blocked');btn.disabled=false;if(!browserNotificationsSupported()){btn.classList.add('blocked');btn.title='Trình duyệt không hỗ trợ Web Push hoặc trang chưa chạy HTTPS';if(label)label.textContent='Không hỗ trợ';return;}if(Notification.permission==='granted'){btn.classList.add('enabled');btn.title='Web Push đã bật';if(label)label.textContent='Đã bật';setWebPushHelp('');return;}if(Notification.permission==='denied'){btn.classList.add('blocked');btn.title='Notification đang bị chặn';if(label)label.textContent='Bị chặn';return;}btn.title='Bật thông báo ngoài web';if(label)label.textContent='Bật ngoài web';}
function showPermissionDeniedHelp(){updateBrowserNotiButton();setWebPushHelp('Notification đang bị chặn. Bạn cần bật lại trong '+browserName()+': bấm icon ổ khóa bên trái URL -> Site settings -> Notifications -> Allow, rồi reload trang.');}
function urlBase64ToUint8Array(base64String){var padding='='.repeat((4-base64String.length%4)%4);var base64=(base64String+padding).replace(/-/g,'+').replace(/_/g,'/');var raw=window.atob(base64);var out=new Uint8Array(raw.length);for(var i=0;i<raw.length;i++)out[i]=raw.charCodeAt(i);return out;}
function subscribeSalePlanPush(publicKey,forceReset){var appKey=urlBase64ToUint8Array(publicKey);if(appKey.length!==65)throw new Error('invalid_vapid_public_key_'+appKey.length);return navigator.serviceWorker.register('/sale_plan_webpush_sw.js',{scope:'/'}).then(function(reg){return navigator.serviceWorker.ready.then(function(){return reg;});}).then(function(reg){return reg.pushManager.getSubscription().then(function(sub){if(sub&&forceReset)return sub.unsubscribe().then(function(){return null;});return sub;}).then(function(sub){return sub||reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:appKey});});});}
function requestBrowserNotifications(){setWebPushHelp('');if(!browserNotificationsSupported()){updateBrowserNotiButton();setWebPushHelp(browserName()+' không hỗ trợ Web Push hoặc trang chưa chạy HTTPS. Edge/Opera/Chrome bản chính thức đều hỗ trợ.');return Promise.resolve('unsupported');}if(Notification.permission==='denied'){showPermissionDeniedHelp();return Promise.resolve('denied');}return fetch('/api/sale_plan/webpush_config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})}).then(function(r){return r.json();}).then(function(j){var cfg=j.result||{};if(!cfg.enabled||!cfg.public_key)throw new Error('webpush_not_configured');var permissionPromise=Notification.permission==='granted'?Promise.resolve('granted'):Notification.requestPermission();return permissionPromise.then(function(p){if(p==='denied'){showPermissionDeniedHelp();throw new Error('permission_denied');}if(p!=='granted')throw new Error('permission_'+p);return subscribeSalePlanPush(cfg.public_key,false).catch(function(firstErr){console.warn('sale plan webpush first subscribe failed, retrying clean',firstErr);return subscribeSalePlanPush(cfg.public_key,true);});}).then(function(sub){return fetch('/api/sale_plan/webpush_subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{subscription:sub.toJSON(),backend_messages:false}})});}).then(function(){updateBrowserNotiButton();setWebPushHelp('');return 'granted';});}).catch(function(e){console.warn('sale plan webpush subscribe failed',e);updateBrowserNotiButton();if(e&&e.message==='permission_denied')return 'denied';var msg=(e&&e.name==='AbortError')?'Không kết nối được push service của '+browserName()+'. Thử Chrome/Edge/Opera bản mới, tắt VPN/proxy/adblock, hoặc kiểm tra quyền notification của site.':('Không bật được Web Push: '+(e&&e.message?e.message:e));setWebPushHelp(msg);return 'error';});}
if('serviceWorker' in navigator){navigator.serviceWorker.addEventListener('message',function(e){var d=e.data||{};if(d.type==='sale_plan_push_open')openOrderFromNotification(d.so_id,d.so_name);});}
function showMentionDesktopNotification(ev){try{if(!browserNotificationsSupported()||Notification.permission!=='granted'||!ev)return;var title='Có tin nhắn mới '+(ev.author_name?('từ '+ev.author_name):'');var body=(ev.so_name||'Sale order')+': '+(ev.preview||ev.body||'');var n=new Notification(title,{body:body,icon:'/web/static/img/favicon.ico',tag:'sale-plan-mention-'+(ev.notification_id||ev.id||ev.so_id||Date.now()),renotify:true});n.onclick=function(){window.focus();openOrderFromNotification(ev.so_id,ev.so_name);n.close();};setTimeout(function(){n.close();},9000);}catch(e){}}
function showMentionToast(ev){var stack=$('mention-toast-stack');if(!stack||!ev)return;var toast=document.createElement('div');toast.className='mention-toast';toast.innerHTML='<button type="button" class="mention-toast-close" aria-label="Đóng">&times;</button><div class="mention-toast-title">Có tin nhắn mới '+(ev.author_name?('từ '+esc(ev.author_name)):'')+'</div><div class="mention-toast-body"><strong>'+esc(ev.so_name||'Sale order')+'</strong>: '+esc(ev.preview||ev.body||'')+'</div>';toast.addEventListener('click',function(e){if(e.target.closest('.mention-toast-close')){toast.remove();return;}openOrderFromNotification(ev.so_id,ev.so_name);toast.remove();});stack.prepend(toast);while(stack.children.length>4)stack.lastElementChild.remove();setTimeout(function(){toast.remove();},7000);}
function handleMentionEvent(ev){if(!ev||!ev.id||!eventMatchesCurrentAlias(ev))return;var aliases=getCurrentMentionAliases();var idMap=ev.notification_id_by_alias||{};var matched=(ev.mentions||[]).map(normalizeMentionAlias).filter(function(alias){return aliases.indexOf(alias)!==-1;});var added=false;matched.forEach(function(alias){var notificationId=idMap[alias]||ev.notification_id||ev.id;var seenKey=String(notificationId);if(_mentionSeen[seenKey])return;_mentionSeen[seenKey]=true;added=true;addMentionNotification(Object.assign({},ev,{id:notificationId,notification_id:notificationId,alias:alias,unread:true}));});if(added){showMentionToast(ev);showMentionDesktopNotification(ev);playMentionSound();}_mentionLastId=Math.max(_mentionLastId,parseInt(ev.id,10)||0);}
function loadPublicMentionAliases(){return fetch('/api/sale_plan/mention_aliases',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})}).then(function(r){return r.json();}).then(function(j){var d=j.result||{};_mentionAliases=d.status==='success'?(d.aliases||[]):[];renderMentionNotiPanel();}).catch(function(){_mentionAliases=[];});}
function currentPublicMentionQuery(input){var pos=input.selectionStart||0;var before=input.value.slice(0,pos);var m=/(^|\s)@([^@,;:!?()\[\]{}<>]*)$/.exec(before);if(!m)return null;return {start:pos-m[2].length-1,term:normalizeMentionAlias(m[2]),pos:pos};}
function renderPublicMentionSuggest(input){var box=$('dr-mention-suggest');if(!box)return;var q=currentPublicMentionQuery(input);if(!q){box.classList.remove('open');box.innerHTML='';return;}var items=_mentionAliases.filter(function(a){return !q.term||normalizeMentionAlias(a.alias).indexOf(q.term)===0||normalizeMentionAlias(a.display_alias).indexOf(q.term)===0||normalizeMentionAlias(a.user_name).indexOf(q.term)>=0;}).slice(0,30);if(!items.length){box.classList.remove('open');box.innerHTML='';return;}_mentionActiveIndex=Math.min(Math.max(_mentionActiveIndex,0),items.length-1);box.innerHTML=items.map(function(a,i){var label=a.display_alias||a.alias;return '<div class="public-mention-suggest-item '+(i===_mentionActiveIndex?'active':'')+'" data-alias="'+esc(label)+'"><strong>@'+esc(label)+'</strong><small>'+esc(a.user_name||'')+'</small></div>';}).join('');box.classList.add('open');}
function applyPublicMentionAlias(input,alias){var q=currentPublicMentionQuery(input);if(!q)return;input.value=input.value.slice(0,q.start)+'@'+alias+' '+input.value.slice(q.pos);var pos=q.start+alias.length+2;input.focus();input.setSelectionRange(pos,pos);var box=$('dr-mention-suggest');if(box)box.classList.remove('open');}
function startSalePlanMentionListener(){updateBrowserNotiButton();Promise.all([loadPublicMentionAliases(),loadCurrentMentionAlias()]).then(function(){loadMentionNotiItems();});}
window.HLVSalePlanMentionBus={onEvent:function(payload){handleMentionEvent(payload);},onStatus:function(status){}};
var TAG_BG=['#adb5bd','#dc3545','#fd7e14','#ffc107','#20c997','#6610f2','#d63384','#0d6efd','#6f42c1','#e91e63','#198754','#0dcaf0'];
var TAG_FG=[0,0,0,1,1,0,0,0,0,0,0,1]; // 1=dark text
function tagBadge(tag){var c=tag[2]||0;var bg=TAG_BG[c]||TAG_BG[0];var fg=TAG_FG[c]?'#000':'#fff';return'<span class="badge me-1" style="background-color:'+bg+';color:'+fg+'">'+esc(tag[1])+'</span>';}
function groupLines(lines){
  var map={},order=[];
  lines.forEach(function(l){
    var pid=l.product_id?l.product_id[0]:0;
    // Cùng sản phẩm nhưng khác đơn giá/chiết khấu là các dòng thương mại khác nhau.
    var key=pid+'|'+String(l.price_unit||0)+'|'+String(l.discount||0);
    if(map[key]){
      map[key].product_uom_qty+=l.product_uom_qty||0;
      map[key].qty_delivered+=l.qty_delivered||0;
      map[key].qty_packed+=l.qty_packed||0;
      map[key].qty_reserved_here+=(l.qty_reserved_here||0); // sum reservations across matching commercial lines
      // qty_warehouse_free: keep first (product-level, same for all lines of same product/wh)
      map[key].delivered_subtotal+=(l.delivered_subtotal||0);
      map[key].delivered_tax+=(l.delivered_tax||0);
      map[key].delivered_total+=(l.delivered_total||0);
    } else {
      map[key]={product_id:l.product_id,product_uom_qty:l.product_uom_qty||0,
        qty_delivered:l.qty_delivered||0,qty_packed:l.qty_packed||0,
        qty_available:l.qty_available||0,qty_warehouse_free:l.qty_warehouse_free||0,
        qty_reserved_here:l.qty_reserved_here||0,is_kit:l.is_kit||false,
        price_unit:l.price_unit||0,discount:l.discount||0,
        delivered_subtotal:l.delivered_subtotal||0,
        delivered_tax:l.delivered_tax||0,
        delivered_total:l.delivered_total||0};
      order.push(key);
    }
  });
  return order.map(function(key){return map[key];});
}

function partnerName(o){return o.partner_id?o.partner_id[1]:'';}
function whName(o){return o.warehouse_id?o.warehouse_id[1]:''}

// --- IndexedDB cache ---
var _SP_CACHE_TTL=5*60*1000;
function _spFilterKey(){
  return JSON.stringify([gv('f-q'),gv('f-wh'),gv('f-del'),gv('f-stk'),gv('f-pack'),
    gv('f-date-from'),gv('f-date-to'),gv('f-po-date-from'),gv('f-po-date-to'),
    gv('f-done-from'),gv('f-done-to'),gv('f-po-status'),gv('f-saler'),
    gv('f-htgh'),gv('f-dtype'),getTagIds(),$('f-show-completed').checked,$('f-mine-only').checked]);
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
// Số thứ tự request — chống race condition: nếu 2 load() chạy chồng lên nhau (VD load() tự động
// lúc mở trang còn đang chạy thì user đã gõ search + Enter ngay), request nào bắn đi TRƯỚC nhưng
// VỀ SAU (do tải nhiều dữ liệu hơn/chậm hơn) sẽ tự bị bỏ qua, không ghi đè kết quả của request mới
// hơn — đây chính là nguyên nhân "search đúng rồi 1-2s sau tự quay lại ALL" đã gặp.
var _spLoadSeq=0;

function load(append,silent){
  if(!_spCacheRestored&&!silent)showLoading();
  _spCacheRestored=false;
  var mySeq=++_spLoadSeq;
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
    mine_only:$('f-mine-only').checked,
    limit:lim,offset:offset};
  fetch('/api/sale_plan/data',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',method:'call',params:body})})
  .then(function(r){return r.json()})
  .then(function(j){
    hideLoading();
    if(mySeq!==_spLoadSeq){
      // Đã có request load() mới hơn bắn ra sau request này (VD user gõ search khi request cũ
      // còn đang chạy) — bỏ qua kết quả trễ này để không ghi đè kết quả đúng đang hiển thị.
      return;
    }
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
      // Đơn trả hàng/dừng → ẩn khỏi cột chính, chỉ hiện ở cột "Trả hàng / Dừng"
      if(o.is_returned_or_stopped) return false;
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

  // ── Cột "Trả hàng / Dừng" — chỉ hiển thị khi user bật "Hiện đơn đã giao" ──
  var showCompleted=$('f-show-completed')&&$('f-show-completed').checked;
  if(showCompleted){
    var returnedItems=S.orders.filter(function(o){return o.is_returned_or_stopped;});
    if(returnedItems.length>0){
      var rPageSize=S.kanbanColPageSize['__returned__']||15;
      var rVisible=returnedItems.slice(0,rPageSize);
      var rRemaining=returnedItems.length-rPageSize;
      var rCol=document.createElement('div');rCol.className='kanban-col';
      rCol.innerHTML='<div class="card border-danger"><div class="card-header d-flex justify-content-between align-items-center text-danger py-2" style="background:#fff0f0;border-color:#dc3545">'
        +'<strong><i class="fa fa-undo me-1"></i>TRẢ HÀNG / DỪNG</strong>'
        +'<span class="badge bg-danger rounded-pill">'+returnedItems.length+'</span></div>'
        +'<div class="card-body p-2 d-flex flex-column gap-2"></div></div>';
      wrap.appendChild(rCol);
      var rBody=rCol.querySelector('.card-body');
      rVisible.forEach(function(o){
        var card=document.createElement('div');
        card.innerHTML=renderSOCard(o);
        rBody.appendChild(card.firstChild);
      });
      if(rRemaining>0){
        var rBtn=document.createElement('button');
        rBtn.className='btn-col-more mt-1';
        rBtn.innerHTML='<i class="fa fa-chevron-down"></i> Tải thêm ('+rRemaining+' còn lại)';
        rBtn.setAttribute('data-col-key','__returned__');
        rBody.appendChild(rBtn);
      }
    }
  }
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
  var misaLocked=!!o.misa_qty_sync_pending;
  var bgCls=o.has_delivered_today?' so-card-deltoday':(o.stock_status==='ready'?' so-card-ready':(o._is_new?' so-card-new':''));
  var h='<div class="card so-card cursor-pointer '+bc+(reported?' opacity-75':'')+bgCls+'" data-so-id="'+o.id+'">'
    +(misaLocked?'<div class="misa-lock-ribbon"><i class="fa fa-lock me-1"></i>ĐANG KHÓA · CHỜ KHO DUYỆT</div>':'')
    +'<div class="card-header py-2'+(misaLocked?' misa-lock-card-header':'')+'">'
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
  h+='<div class="d-flex justify-content-end align-items-center gap-1 mt-2">';
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
    var reportBtn=isReported
      ?'<span class="text-muted" style="font-size:.65rem"><i class="fa fa-flag text-danger"></i></span>'
      :'<button class="btn-report" data-so-id="'+o.id+'" data-so-name="'+esc(o.name)+'"><i class="fa fa-flag"></i></button>';
    var reportCell='<td>'+reportBtn+'</td>';
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
var _publicMessageQueue=[];
var _publicMessageSending=false;
var _publicMessageRefreshOrders={};

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
function updatePublicMessageSendingState(){
  var btn=$('dr-msg-send');
  if(!btn)return;
  btn.title=_publicMessageSending?'Đang gửi - bạn vẫn có thể gửi tiếp':'Gửi tin nhắn';
  btn.innerHTML='<i class="fa fa-paper-plane"></i>'+(_publicMessageSending?'<i class="fa fa-spinner fa-spin ms-1"></i>':'');
}
function restorePublicMessageDraft(item){
  if(!item||_currentDrawerOrderId!==item.orderId)return;
  var input=$('dr-msg-input');
  if(input&&item.body)input.value=item.body+(input.value?'\n'+input.value:'');
  if(item.files&&item.files.length){
    _currentMsgFiles=item.files.concat(_currentMsgFiles);
    renderPublicFileQueue();
  }
}
function processPublicMessageQueue(){
  if(_publicMessageSending||!_publicMessageQueue.length)return;
  var item=_publicMessageQueue.shift();
  _publicMessageSending=true;
  updatePublicMessageSendingState();
  fetch('/api/sale_plan/send_message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{order_id:item.orderId,body:item.body,author_name:item.authorName,attachments:item.attachments}})})
  .then(function(r){return r.json();})
  .then(function(resp){
    var d=resp.result||{};
    if(d.status!=='success')throw new Error(d.message||'Lỗi gửi tin nhắn');
    _publicMessageRefreshOrders[item.orderId]=true;
  })
  .catch(function(err){
    restorePublicMessageDraft(item);
    alert((err&&err.message)||'Lỗi kết nối');
  })
  .then(function(){
    _publicMessageSending=false;
    updatePublicMessageSendingState();
    if(_publicMessageQueue.length){
      processPublicMessageQueue();
    }else{
      var currentOrderId=_currentDrawerOrderId;
      var shouldRefresh=!!_publicMessageRefreshOrders[currentOrderId];
      _publicMessageRefreshOrders={};
      if(shouldRefresh)loadMessages();
    }
  });
}
function sendPublicMessage(){
  var input=$('dr-msg-input');
  var body=(input.value||'').trim();
  if((!body&&!_currentMsgFiles.length)||!_currentDrawerOrderId)return;
  var authorName=($('dr-msg-author').value||'').trim();
  if(!authorName){$('dr-msg-author').focus();$('dr-msg-author').classList.add('is-invalid');return;}
  $('dr-msg-author').classList.remove('is-invalid');
  localStorage.setItem('hlv_msg_author',authorName);
  var files=_currentMsgFiles.slice();
  _publicMessageQueue.push({
    orderId:_currentDrawerOrderId,
    body:body,
    authorName:authorName,
    files:files,
    attachments:files.map(function(f){return {name:f.name,mimetype:f.mimetype,datas:f.datas};}),
  });
  input.value='';
  _currentMsgFiles=[];
  renderPublicFileQueue();
  var suggest=$('dr-mention-suggest');
  if(suggest){suggest.classList.remove('open');suggest.innerHTML='';}
  processPublicMessageQueue();
}

var PICKING_STATE_LABEL={draft:'Nháp',waiting:'Chờ bước trước',confirmed:'Chờ hàng (chưa giữ được)',
  assigned:'Đã giữ đủ hàng, sẵn sàng lấy',done:'Hoàn thành',cancel:'Đã hủy'};
var PICKING_STATE_BADGE={draft:'bg-secondary',waiting:'bg-secondary',confirmed:'bg-warning text-dark',
  assigned:'bg-success',done:'bg-success',cancel:'bg-danger'};
// state 'assigned' của Odoo KHÔNG phân biệt giữ đủ hay giữ 1 phần — phải tự so sánh
// demand_qty/reserved_qty trong moves để biết chính xác, rồi báo đỏ nếu chỉ có 1 phần.
function getPickingStatusDisplay(p){
  if(!p.state){
    return {badgeClass:'bg-secondary',label:'Không rõ trạng thái'};
  }
  if(p.state==='assigned'){
    var moves=p.moves||[];
    var totalDemand=0,totalReserved=0;
    moves.forEach(function(mv){totalDemand+=(mv.demand_qty||0);totalReserved+=(mv.reserved_qty||0);});
    if(moves.length&&totalReserved<totalDemand){
      return {badgeClass:'bg-danger',label:totalReserved>0?'Có hàng 1 phần':'Chưa giữ được hàng'};
    }
    return {badgeClass:'bg-success',label:'Đã giữ đủ hàng, sẵn sàng lấy'};
  }
  return {badgeClass:PICKING_STATE_BADGE[p.state]||'bg-secondary',label:PICKING_STATE_LABEL[p.state]||p.state};
}
function renderPickingsSection(pickings,canPrint){
  var pickOnly=(pickings||[]).filter(function(p){return (p.sequence_code||'').indexOf('PICK')!==-1 && !p.return_of;});
  var h='<div class="mt-3 p-3 rounded" style="background:#f7fafc;border:1px solid #e2e8f0">'
    +'<h6 class="text-uppercase small mb-2 text-muted"><i class="fa fa-truck me-1"></i>Phiếu lấy hàng (PICK)</h6>';
  if(!canPrint){
    h+='<div class="small text-muted"><i class="fa fa-lock me-1"></i>Đơn này không thuộc mã sale của tài khoản bạn — không thể xem/in phiếu lấy hàng.</div></div>';
    return h;
  }
  if(!pickOnly.length){
    h+='<div class="small text-danger"><i class="fa fa-exclamation-triangle me-1"></i>Đơn này chưa có phiếu lấy hàng (PICK) nào — có thể chưa xác nhận, hoặc kho của đơn không dùng bước lấy hàng riêng.</div></div>';
    return h;
  }
  h+='<table class="table table-sm table-borderless mb-0" style="font-size:.78rem">'
    +'<thead><tr class="text-muted"><th>Phiếu</th><th>Trạng thái in</th><th>Trạng thái phiếu</th><th class="text-end">SL món</th></tr></thead><tbody>';
  pickOnly.forEach(function(p){
    var moves=p.moves||[];
    var stDisplay=getPickingStatusDisplay(p);
    // Phiếu đã hoàn tất/hủy vẫn cho MỞ dialog xem chi tiết + nhật ký (đối soát), chỉ chặn hành
    // động in NGAY TRONG dialog (xem openPickingDetailModal) — không chặn click mở luôn.
    var finished=(p.state==='done'||p.state==='cancel');
    h+='<tr class="pick-row'+(finished?' opacity-75':'')+'" data-picking-id="'+p.id+'" style="cursor:pointer"'
      +(finished?' title="Phiếu đã hoàn tất/hủy — chỉ xem chi tiết/nhật ký, không in lại được"':'')+'>'
      +'<td class="fw-bold'+(finished?' text-muted':' text-primary')+'">'+esc(p.name)+' <i class="fa fa-chevron-right text-muted" style="font-size:.65rem"></i></td>'
      +'<td>'+(p.printed?'<span class="badge bg-success">Đã gửi lệnh in</span>':'<span class="badge bg-secondary">Chưa in</span>')+'</td>'
      +'<td><span class="badge '+stDisplay.badgeClass+'">'+esc(stDisplay.label)+'</span></td>'
      +'<td class="text-end">'+moves.length+'</td>'
      +'</tr>';
  });
  h+='</tbody></table></div>';
  return h;
}

// --- Picking detail modal: xem chi tiết 1 phiếu PICK, xem trước rồi mới xác nhận in ---
var _pdPickingId=null;
function openPickingDetailModal(pickingId){
  var p=null,ownerOrder=null;
  for(var i=0;i<S.orders.length&&!p;i++){
    (S.orders[i].pickings||[]).forEach(function(pk){if(pk.id===pickingId){p=pk;ownerOrder=S.orders[i];}});
  }
  if(!p)return;
  if(!ownerOrder||ownerOrder.can_print!==true){
    showPrintToast('Đơn này không thuộc mã sale của tài khoản bạn, không được xem/in phiếu này.',false);
    return;
  }
  _pdPickingId=pickingId;
  $('pd-title').textContent=p.name;
  var pdStDisplay=getPickingStatusDisplay(p);
  $('pd-state-badge').className='badge mt-1 '+pdStDisplay.badgeClass;
  $('pd-state-badge').textContent=pdStDisplay.label;
  var moves=p.moves||[];
  var lh;
  if(!moves.length){
    lh='<div class="text-muted small">Không có dòng sản phẩm.</div>';
  } else {
    lh='<table class="table table-sm table-bordered mb-0"><thead><tr class="text-muted">'
      +'<th>Sản phẩm</th><th class="text-end">Yêu cầu</th><th class="text-end">Đã giữ</th></tr></thead><tbody>';
    moves.forEach(function(mv){
      var demand=mv.demand_qty||0,reserved=mv.reserved_qty||0;
      var short=reserved<demand;
      lh+='<tr><td>'+esc(mv.product_name)+'</td>'
        +'<td class="text-end">'+fq(demand)+'</td>'
        +'<td class="text-end '+(short?'text-danger fw-bold':'text-success fw-bold')+'">'+fq(reserved)+'</td></tr>';
    });
    lh+='</tbody></table>';
  }
  var finished=(p.state==='done'||p.state==='cancel');
  if(finished){
    lh+='<div class="small text-muted mt-2"><i class="fa fa-info-circle me-1"></i>Phiếu đã '
      +(p.state==='done'?'hoàn tất':'hủy')+' — chỉ xem chi tiết/nhật ký, không in lại được nữa.</div>';
  }
  $('pd-lines').innerHTML=lh;
  var pvBtn=$('pd-btn-preview');
  var cfBtn=$('pd-btn-confirm');
  if(finished){
    // Phiếu đã xong/hủy: ẩn hết nút in, chỉ còn xem chi tiết + nhật ký.
    pvBtn.classList.add('d-none');
    cfBtn.classList.add('d-none');
  } else {
    pvBtn.classList.remove('d-none');pvBtn.disabled=false;pvBtn.innerHTML='<i class="fa fa-eye me-1"></i>Xem trước';
    var whLabel='Gửi phiếu in cho kho'+(p.warehouse_name?' '+p.warehouse_name:'');
    cfBtn.dataset.label=whLabel;
    cfBtn.classList.add('d-none');cfBtn.disabled=false;cfBtn.innerHTML='<i class="fa fa-check me-1"></i>'+esc(whLabel);
  }
  pdSwitchTab('detail');
  $('pd-modal').style.display='flex';
  // Tự fetch nhật ký ngay khi mở dialog (không đợi user bấm qua tab "Nhật ký" mới gọi) — đỡ
  // phải "bấm load lại" mỗi lần xem, dữ liệu đã sẵn sàng khi chuyển tab.
  loadPickingPrintLog(pickingId);
}
function pdSwitchTab(tab){
  $('pd-tab-detail').classList.toggle('active',tab==='detail');
  $('pd-tab-log').classList.toggle('active',tab==='log');
  $('pd-tabpane-detail').classList.toggle('d-none',tab!=='detail');
  $('pd-tabpane-log').classList.toggle('d-none',tab!=='log');
  $('pd-footer-detail').classList.toggle('d-none',tab!=='detail');
  // Không fetch lại ở đây nữa — nhật ký đã được tải sẵn ngay lúc mở dialog
  // (xem openPickingDetailModal), tránh gọi API 2 lần cho cùng 1 lần xem.
}
$('pd-tab-detail').addEventListener('click',function(){pdSwitchTab('detail');});
$('pd-tab-log').addEventListener('click',function(){pdSwitchTab('log');});
function loadPickingPrintLog(pickingId){
  if(!pickingId)return;
  var pane=$('pd-tabpane-log');
  pane.innerHTML='<div class="p-3 text-center text-muted"><i class="fa fa-spinner fa-spin"></i></div>';
  fetch('/api/sale_plan/picking_print_log',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{picking_id:pickingId}})})
  .then(function(r){return r.json();})
  .then(function(j){
    var d=j.result;
    if(!d||!d.success){pane.innerHTML='<div class="p-3 text-danger small">'+esc((d&&d.message)||'Lỗi tải nhật ký')+'</div>';return;}
    var logs=d.logs||[];
    if(!logs.length){pane.innerHTML='<div class="p-3 text-muted small">Chưa có nhật ký nào cho phiếu này.</div>';return;}
    pane.innerHTML=logs.map(function(l){
      return '<div class="pd-log-item"><div class="pd-log-meta">'+esc(pqFormatTime(l.date))+' &middot; '+esc(l.author)+'</div>'
        +'<div class="pd-log-body">'+esc(l.body)+'</div></div>';
    }).join('');
  }).catch(function(){pane.innerHTML='<div class="p-3 text-danger small">Lỗi kết nối.</div>';});
}
function closePickingDetailModal(){
  $('pd-modal').style.display='none';
  _pdPickingId=null;
}
$('pd-close').addEventListener('click',closePickingDetailModal);
$('pd-modal').addEventListener('click',function(e){if(e.target===this)closePickingDetailModal();});
$('pd-btn-preview').addEventListener('click',function(){
  if(!_pdPickingId)return;
  var btn=this;
  btn.disabled=true;btn.innerHTML='<i class="fa fa-spinner fa-spin me-1"></i>Đang tạo bản xem trước...';
  fetch('/api/sale_plan/preview_pick_slip',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{picking_id:_pdPickingId}})})
  .then(function(r){return r.json();})
  .then(function(j){
    var d=j.result;
    btn.disabled=false;btn.innerHTML='<i class="fa fa-eye me-1"></i>Xem trước';
    if(d&&d.success){
      // Đã xem trước rồi thì ẩn nút "Xem trước" luôn, chỉ còn nút gửi in — tránh xem trước lại
      // nhiều lần không cần thiết, đỡ rối giao diện.
      btn.classList.add('d-none');
      $('pd-btn-confirm').classList.remove('d-none');
      // Hiện PDF trong 1 dialog riêng NGAY TRÊN trang này (không mở tab mới, không điều hướng
      // rời trang) — đóng lại là quay về đúng chỗ đang xem, khỏi phải tìm/lọc lại đơn.
      $('pdfp-frame').src=d.preview_url;
      $('pdfp-modal').style.display='flex';
    } else {
      showPrintToast((d&&d.message)||'Lỗi khi tạo bản xem trước',false);
    }
  }).catch(function(){
    btn.disabled=false;btn.innerHTML='<i class="fa fa-eye me-1"></i>Xem trước';showPrintToast('Lỗi kết nối.',false);
  });
});
function closePdfPreviewModal(){
  $('pdfp-modal').style.display='none';
  $('pdfp-frame').src='about:blank';
}
$('pdfp-close').addEventListener('click',closePdfPreviewModal);
$('pdfp-modal').addEventListener('click',function(e){if(e.target===this)closePdfPreviewModal();});
// Dùng chung cho cả nút "Gửi phiếu in cho kho" ở dialog chi tiết VÀ nút cùng tên ngay trong
// dialog xem trước PDF (pdfp-modal) — khỏi phải đóng preview quay lại mới gửi in được.
function sendPrintRequest(btn){
  if(!_pdPickingId)return;
  var label=$('pd-btn-confirm').dataset.label||'Gửi phiếu in cho kho';
  btn.disabled=true;btn.innerHTML='<i class="fa fa-spinner fa-spin me-1"></i>Đang gửi...';
  fetch('/api/sale_plan/confirm_print_pick_slip',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{picking_id:_pdPickingId}})})
  .then(function(r){return r.json();})
  .then(function(j){
    var d=j.result;
    btn.disabled=false;btn.innerHTML='<i class="fa fa-check me-1"></i>'+esc(label);
    if(d&&d.success){
      showPrintToast(d.message||'Đã gửi yêu cầu in',d.iot_ready!==false);
      loadPrintQueue();
      closePdfPreviewModal();
      closePickingDetailModal();
    } else {
      showPrintToast((d&&d.message)||'Lỗi khi gửi in',false);
    }
  }).catch(function(){btn.disabled=false;btn.innerHTML='<i class="fa fa-check me-1"></i>'+esc(label);showPrintToast('Lỗi kết nối.',false);});
}
$('pd-btn-confirm').addEventListener('click',function(){sendPrintRequest(this);});
$('pdfp-btn-confirm').addEventListener('click',function(){sendPrintRequest(this);});

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
    +(o.origin?'<div><i class="fa fa-sticky-note text-warning me-2"></i><span class="text-muted">Ghi chú: '+esc(o.origin)+'</span></div>':'')
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
    var reservedHere=l.qty_reserved_here||0;
    var stockTitle=reservedHere>0?' title="Tự do: '+fq(l.qty_warehouse_free||0)+'  |  Giữ cho đơn: '+fq(reservedHere)+'"':'';
    var stockSub=reservedHere>0?'<div class="text-info" style="font-size:.7rem;line-height:1.1"><i class="fa fa-lock me-1"></i>'+fq(reservedHere)+'</div>':'';
    h+='<tr class="'+rc+'"><td>'+esc(pname)+(l.is_kit?' <span class="badge bg-warning bg-opacity-25 text-dark" style="font-size:10px"><i class="fa fa-gift"></i> Combo</span>':'')+'</td>'
      +'<td class="text-end fw-bold">'+fq(l.product_uom_qty)+'</td>'
      +'<td class="text-end '+packCls+'">'+packHtml+'</td>'
      +'<td class="text-end '+stkCls+'"'+stockTitle+'>'+fq(wfree)+stockSub+'</td>'
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
  // Phiếu kho: giúp sale biết đơn đang có phiếu gì, ở trạng thái nào (nhất là phiếu PICK dùng để
  // in) — tránh tình trạng bấm "In" báo lỗi mà không hiểu vì sao.
  h+=renderPickingsSection(o.pickings||[], o.can_print===true);
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
    +'<div class="position-relative flex-grow-1"><input id="dr-msg-input" class="form-control form-control-sm" placeholder="Nhập tin nhắn..."/><div id="dr-mention-suggest" class="public-mention-suggest"></div></div>'
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
  $('dr-msg-input').addEventListener('input',function(){_mentionActiveIndex=0;renderPublicMentionSuggest(this);});
  $('dr-msg-input').addEventListener('keydown',function(e){var box=$('dr-mention-suggest');if(box&&box.classList.contains('open')){var items=Array.from(box.querySelectorAll('.public-mention-suggest-item'));if(items.length){if(e.key==='ArrowDown'){e.preventDefault();_mentionActiveIndex=(_mentionActiveIndex+1)%items.length;renderPublicMentionSuggest(this);return;}if(e.key==='ArrowUp'){e.preventDefault();_mentionActiveIndex=(_mentionActiveIndex-1+items.length)%items.length;renderPublicMentionSuggest(this);return;}if(e.key==='Tab'||e.key==='Enter'){e.preventDefault();applyPublicMentionAlias(this,items[_mentionActiveIndex].dataset.alias);return;}}}if(e.key==='Enter'){e.preventDefault();sendPublicMessage();}});
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
  if($('f-mine-only').checked) chips.push({k:'f-mine-only',v:'Đơn của tôi',reset:''});
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
  var browserNotiBtn=e.target.closest('#mention-browser-noti-button');
  if(browserNotiBtn){e.preventDefault();e.stopPropagation();requestBrowserNotifications();return;}
  var notiBtn=e.target.closest('#mention-noti-button');
  if(notiBtn){e.preventDefault();e.stopPropagation();var panel=$('mention-noti-panel');if(panel)panel.classList.toggle('open');return;}
  var notiAlias=e.target.closest('.mention-noti-alias-tab');
  if(notiAlias){e.preventDefault();e.stopPropagation();_mentionActiveAlias=normalizeMentionAlias(notiAlias.dataset.alias||'all')||'all';_mentionNotiVisible=20;renderMentionNotiPanel();return;}
  var notiMore=e.target.closest('.mention-noti-more');
  if(notiMore){e.preventDefault();e.stopPropagation();_mentionNotiVisible+=20;renderMentionNotiPanel();return;}
  var notiReadAll=e.target.closest('#mention-noti-read-all');
  if(notiReadAll){e.preventDefault();e.stopPropagation();_mentionNotiItems.forEach(function(x){if(_mentionActiveAlias==='all'||mentionItemHasAlias(x,_mentionActiveAlias))x.unread=false;});renderMentionNotiPanel();fetch('/api/sale_plan/mention_notifications/read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{alias:_mentionActiveAlias,all_aliases:_mentionActiveAlias==='all'}})}).then(function(r){return r.json();}).then(function(j){var d=j.result||{};if(d.status==='success')_mentionNotiItems=d.events||_mentionNotiItems;renderMentionNotiPanel();}).catch(function(){});return;}
  var notiClear=e.target.closest('#mention-noti-clear');
  if(notiClear){e.preventDefault();e.stopPropagation();_mentionNotiItems=_mentionNotiItems.filter(function(x){return !(_mentionActiveAlias==='all'||mentionItemHasAlias(x,_mentionActiveAlias));});renderMentionNotiPanel();fetch('/api/sale_plan/mention_notifications/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{alias:_mentionActiveAlias,all_aliases:_mentionActiveAlias==='all'}})}).then(function(r){return r.json();}).then(function(j){var d=j.result||{};if(d.status==='success')_mentionNotiItems=d.events||[];renderMentionNotiPanel();}).catch(function(){});return;}
  var notiItem=e.target.closest('.mention-noti-item');
  if(notiItem){e.preventDefault();e.stopPropagation();markMentionNotificationRead(notiItem.dataset.id);var notiPanel=$('mention-noti-panel');if(notiPanel)notiPanel.classList.remove('open');var notiSoId=parseInt(notiItem.dataset.soId,10)||0;if(notiSoId){openOrderFromNotification(notiItem.dataset.soId,notiItem.dataset.soName);}else{var notiFull=_mentionNotiItems.find(function(x){return String(x.id)===String(notiItem.dataset.id);});if(notiFull)showMentionToast(notiFull);}return;}
  var publicMentionItem=e.target.closest('.public-mention-suggest-item');
  if(publicMentionItem){e.preventDefault();e.stopPropagation();applyPublicMentionAlias($('dr-msg-input'),publicMentionItem.dataset.alias);return;}
  if(!e.target.closest('#dr-mention-suggest')){var ps=$('dr-mention-suggest');if(ps)ps.classList.remove('open');}
  if(!e.target.closest('#mention-noti-panel')){var np=$('mention-noti-panel');if(np)np.classList.remove('open');}
  var chipX=e.target.closest('.chip-x');
  if(chipX){
    e.preventDefault();e.stopPropagation();
    if(chipX.dataset.tagId){
      var tsel=$('f-tag');
      if(tsel){Array.from(tsel.options).forEach(function(o){if(o.value===chipX.dataset.tagId)o.selected=false;});}
    } else {
      var el=$(chipX.dataset.fk);
      if(el){if(el.type==='checkbox'){el.checked=false;}else{el.value=chipX.dataset.fr||'';}}
    }
    load(false);return;
  }
  var rBtn=e.target.closest('.btn-report');
  if(rBtn){e.stopPropagation();e.preventDefault();openReportModal(parseInt(rBtn.dataset.soId,10),rBtn.dataset.soName);return;}
  var pickRow=e.target.closest('.pick-row');
  if(pickRow){e.stopPropagation();e.preventDefault();openPickingDetailModal(parseInt(pickRow.dataset.pickingId,10));return;}
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
  $('f-mine-only').checked=true;
  S.kanbanColPageSize={};
  load(false);
}

$('btn-filter').addEventListener('click',function(){S.kanbanColPageSize={};load(false);});
$('f-need-transfer').addEventListener('change',function(){render();});
$('f-show-completed').addEventListener('change',function(){S.kanbanColPageSize={};load(false);});
$('f-mine-only').addEventListener('change',function(){S.kanbanColPageSize={};load(false);});
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
    show_completed:$('f-show-completed').checked?'1':'',
    filter_mine:$('f-mine-only').checked?'1':''
  });
  window.open('/api/sale_plan/export_excel?'+params.toString(),'_blank');
});
$('btn-export-picking-excel-dd').addEventListener('click',function(e){
  e.preventDefault();
  var params=new URLSearchParams({
    search_query:gv('f-q'),filter_warehouse_id:gv('f-wh'),filter_delivery_status:gv('f-del'),
    filter_stock_status:gv('f-stk'),filter_packing_status:gv('f-pack'),
    filter_date_from:gv('f-date-from'),filter_date_to:gv('f-date-to'),
    filter_po_date_from:gv('f-po-date-from'),filter_po_date_to:gv('f-po-date-to'),
    filter_done_date_from:gv('f-done-from'),filter_done_date_to:gv('f-done-to'),
    filter_po_status:gv('f-po-status'),filter_saler_code:gv('f-saler'),
    filter_htgh:gv('f-htgh'),filter_delivery_type:gv('f-dtype'),filter_tag_ids:getTagIds(),
    show_completed:$('f-show-completed').checked?'1':'',
    filter_mine:$('f-mine-only').checked?'1':''
  });
  window.open('/api/sale_plan/export_picking_excel?'+params.toString(),'_blank');
});
$('btn-export-picking-simple-excel-dd').addEventListener('click',function(e){
  e.preventDefault();
  var params=new URLSearchParams({
    search_query:gv('f-q'),filter_warehouse_id:gv('f-wh'),filter_delivery_status:gv('f-del'),
    filter_stock_status:gv('f-stk'),filter_packing_status:gv('f-pack'),
    filter_date_from:gv('f-date-from'),filter_date_to:gv('f-date-to'),
    filter_po_date_from:gv('f-po-date-from'),filter_po_date_to:gv('f-po-date-to'),
    filter_done_date_from:gv('f-done-from'),filter_done_date_to:gv('f-done-to'),
    filter_po_status:gv('f-po-status'),filter_saler_code:gv('f-saler'),
    filter_htgh:gv('f-htgh'),filter_delivery_type:gv('f-dtype'),filter_tag_ids:getTagIds(),
    show_completed:$('f-show-completed').checked?'1':'',
    filter_mine:$('f-mine-only').checked?'1':''
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
document.addEventListener('keydown',function(e){if(e.key==='Escape'){closeDrawer();closeReportModal();closePrintQueueDrawer();}});

// --- Auto-refresh: poll for changes every 10s ---
var _lastFingerprint=null;
var _pollInterval=300000; // 5 minutes
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

function showPrintToast(msg,ok){
  var toast=document.createElement('div');
  var maxW=ok?360:480;
  toast.style.cssText='position:fixed;bottom:24px;right:24px;z-index:3000;background:'+(ok?'#38a169':'#dc2626')+';color:#fff;padding:12px 20px;border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,.2);font-weight:600;max-width:'+maxW+'px;cursor:pointer';
  toast.title='Bấm để đóng';
  toast.innerHTML='<i class="fa fa-'+(ok?'check':'exclamation-triangle')+' me-1"></i>'+esc(msg);
  toast.addEventListener('click',function(){toast.remove();});
  document.body.appendChild(toast);
  setTimeout(function(){toast.remove();},ok?5000:15000);
}
// --- Drawer "Yêu cầu in": danh sách + trạng thái các yêu cầu in đã gửi, chia theo mã sale MISA
// (nhiều sale có thể dùng chung 1 tài khoản đăng nhập, xem filter "Đơn của tôi") ---
var _pqItems=[];
var _pqActiveTab='all';
var PQ_STATE_LABEL={pending:'Chờ in',printing:'Đang in...',printed:'Đã gửi lệnh in',error:'Lỗi',cancelled:'Đã hủy'};
var PQ_NO_CODE_LABEL='(Chưa rõ sale)';

function loadPrintQueue(){
  fetch('/api/sale_plan/print_queue',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})})
  .then(function(r){return r.json();})
  .then(function(j){
    if(!j.result||j.result.status!=='success')return;
    _pqItems=j.result.items||[];
    updatePrintQueueBadge();
    renderPrintQueueTabs();
    renderPrintQueueList();
    renderPrinterStatus(j.result.printer_status||[]);
  }).catch(function(){/* silent */});
}
// Trạng thái ONLINE/OFFLINE máy in IoT theo kho — hiển thị ngay trong drawer để sale/kho biết
// lý do 1 yêu cầu có thể bị kẹt/lỗi (máy in mất kết nối) mà không cần đợi bấm in.
function renderPrinterStatus(list){
  var box=$('print-queue-printer-status');
  if(!box)return;
  if(!list.length){box.innerHTML='';return;}
  box.innerHTML=list.map(function(p){
    var cls=p.connected?'online':'offline';
    var label=p.connected?'Online':'Offline';
    var title=p.device_name+(p.last_seen?' · lần cuối phản hồi '+esc(pqFormatTime(p.last_seen)):'');
    return '<span class="pq-printer-chip '+cls+'" title="'+esc(title)+'">'
      +'<i class="dot"></i>'+esc(p.warehouse_name)+': '+label+'</span>';
  }).join('');
}
// Định dạng ISO datetime (UTC, không có 'Z') từ hlv.iot.print.queue._to_summary_dict() sang giờ
// VN (UTC+7) — cần chính xác giờ:phút (không chỉ ngày) để đối soát khi sale/kho tranh luận đã
// gửi in lúc nào, khác với fd() (chỉ lấy ngày, không cộng offset UTC).
function pqFormatTime(isoStr){
  if(!isoStr)return'';
  try{
    var utc=new Date(isoStr.slice(-1)==='Z'?isoStr:isoStr+'Z');
    if(isNaN(utc.getTime()))return'';
    var vn=new Date(utc.getTime()+7*60*60*1000);
    var pad=function(n){return('0'+n).slice(-2);};
    return pad(vn.getUTCDate())+'/'+pad(vn.getUTCMonth()+1)+' '+pad(vn.getUTCHours())+':'+pad(vn.getUTCMinutes());
  }catch(e){return'';}
}
function updatePrintQueueBadge(){
  var pending=_pqItems.filter(function(i){return i.state==='pending'||i.state==='printing';}).length;
  var errors=_pqItems.filter(function(i){return i.state==='error';}).length;
  var btn=$('print-queue-button');
  btn.classList.toggle('has-error',errors>0);
  btn.classList.toggle('has-pending',errors===0&&pending>0);
  $('print-queue-count').textContent=String(errors>0?errors:pending);
}
function renderPrintQueueTabs(){
  var counts={};
  _pqItems.forEach(function(i){var c=i.saler_code||PQ_NO_CODE_LABEL;counts[c]=(counts[c]||0)+1;});
  var keys=Object.keys(counts).sort();
  var html='<span class="mention-noti-alias-tab'+(_pqActiveTab==='all'?' active':'')+'" data-pq-tab="all">Tất cả<span class="count">'+_pqItems.length+'</span></span>';
  keys.forEach(function(k){
    html+='<span class="mention-noti-alias-tab'+(_pqActiveTab===k?' active':'')+'" data-pq-tab="'+esc(k)+'">'+esc(k)+'<span class="count">'+counts[k]+'</span></span>';
  });
  $('print-queue-tabs').innerHTML=html;
}
function renderPrintQueueList(){
  var body=$('print-queue-body');
  var items=_pqActiveTab==='all'?_pqItems:_pqItems.filter(function(i){return (i.saler_code||PQ_NO_CODE_LABEL)===_pqActiveTab;});
  if(!items.length){
    body.innerHTML='<div class="p-4 text-center text-muted"><i class="fa fa-print fa-3x opacity-50 mb-2"></i><br/>Chưa có yêu cầu in nào.</div>';
    return;
  }
  var WH_ACTION_LABEL={deferred:'Kho: Xử lý sau',rejected:'Kho: Từ chối xử lý'};
  body.innerHTML=items.map(function(i){
    return '<div class="pq-item">'
      +'<div class="d-flex justify-content-between align-items-start">'
      +'<span class="pq-title">'+esc(i.sale_order_name)+'</span>'
      +'<span class="pq-badge '+esc(i.state)+'">'+esc(PQ_STATE_LABEL[i.state]||i.state)+'</span>'
      +'</div>'
      +'<div class="pq-meta"><i class="fa fa-warehouse me-1"></i>'+esc(i.warehouse_name||'')
      +' &middot; <i class="fa fa-user me-1"></i>'+esc(i.requested_by_name||'')+'</div>'
      +'<div class="pq-meta"><i class="fa fa-clock-o me-1"></i>Yêu cầu: '+esc(pqFormatTime(i.requested_at))
      +(i.printed_at?' &middot; <i class="fa fa-print me-1"></i>Đã gửi lệnh in: '+esc(pqFormatTime(i.printed_at)):'')+'</div>'
      +(i.warehouse_action&&i.warehouse_action!=='none'?'<div class="pq-badge cancelled mt-1" style="display:inline-block"><i class="fa fa-info-circle me-1"></i>'+esc(WH_ACTION_LABEL[i.warehouse_action]||i.warehouse_action)+'</div>':'')
      +(i.error_message?'<div class="pq-error"><i class="fa fa-exclamation-triangle me-1"></i>'+esc(i.error_message)+'</div>':'')
      +'</div>';
  }).join('');
}
$('print-queue-button').addEventListener('click',function(){
  $('print-queue-drawer').classList.add('open');
  $('print-queue-drawer-overlay').classList.add('open');
  loadPrintQueue();
});
function closePrintQueueDrawer(){
  $('print-queue-drawer').classList.remove('open');
  $('print-queue-drawer-overlay').classList.remove('open');
}
$('print-queue-close').addEventListener('click',closePrintQueueDrawer);
$('print-queue-drawer-overlay').addEventListener('click',closePrintQueueDrawer);
document.addEventListener('click',function(e){
  var tab=e.target.closest('[data-pq-tab]');
  if(tab){_pqActiveTab=tab.getAttribute('data-pq-tab');renderPrintQueueTabs();renderPrintQueueList();}
});
loadPrintQueue();
setInterval(loadPrintQueue,15000);

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
startSalePlanMentionListener();
load(false);
});
})();
</script>
</body></html>"""


class SalePlanPublicController(http.Controller):

    @http.route('/sale_plan/bus_frame', type='http', auth='user', methods=['GET'], csrf=False)
    def sale_plan_bus_frame(self, **kwargs):
        session_info = request.env['ir.http'].session_info()
        return request.render('hlv_sale_delivery_planning.sale_plan_bus_frame', {
            'session_info_json': Markup(json.dumps(session_info)),
        })

    @http.route('/sale_plan_webpush_sw.js', type='http', auth='user', methods=['GET'], csrf=False)
    def sale_plan_webpush_sw(self, **kwargs):
        js = """
self.addEventListener('push', function(event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  var title = data.title || 'Sale Plan';
  var options = {
    body: data.body || '',
    icon: '/web/static/img/favicon.ico',
    badge: '/web/static/img/favicon.ico',
    tag: data.tag || ('sale-plan-' + Date.now()),
    renotify: true,
    data: data
  };
  event.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  var data = event.notification.data || {};
  var url = data.url || '/sale_plan';
  event.waitUntil(clients.matchAll({type: 'window', includeUncontrolled: true}).then(function(clientList) {
    for (var i = 0; i < clientList.length; i++) {
      var client = clientList[i];
      if (client.url.indexOf(self.location.origin) === 0 && 'focus' in client) {
        client.focus();
        try { client.postMessage({type: 'sale_plan_push_open', so_id: data.so_id, so_name: data.so_name}); } catch (e) {}
        return;
      }
    }
    if (clients.openWindow) return clients.openWindow(url);
  }));
});
"""
        return request.make_response(js, headers=[
            ('Content-Type', 'application/javascript; charset=utf-8'),
            ('Service-Worker-Allowed', '/'),
            ('Cache-Control', 'no-store'),
        ])

    @http.route('/api/sale_plan/webpush_config', type='json', auth='user', methods=['POST'])
    def api_sale_plan_webpush_config(self, **kwargs):
        public_key, private_key = _get_or_create_webpush_vapid(request.env)
        try:
            import pywebpush  # noqa: F401
            sender_ready = True
        except Exception:
            sender_ready = False
        return {
            'status': 'success',
            'public_key': public_key,
            'enabled': bool(public_key and private_key),
            'sender_ready': sender_ready,
        }

    @http.route('/api/sale_plan/webpush_subscribe', type='json', auth='user', methods=['POST'], csrf=False)
    def api_sale_plan_webpush_subscribe(self, subscription=None, backend_messages=False, **kwargs):
        if not subscription or not isinstance(subscription, dict):
            return {'status': 'error', 'message': 'missing_subscription'}
        aliases = _get_user_sale_plan_aliases(request.env.user)
        if backend_messages:
            aliases = aliases or ['']
        elif not aliases:
            return {'status': 'error', 'message': 'missing_alias'}
        records = request.env['hlv.sale.plan.web.push.subscription'].sudo().upsert_subscription(
            request.env.user,
            subscription,
            aliases=aliases,
            backend_messages=bool(backend_messages),
        )
        return {'status': 'success', 'count': len(records), 'aliases': aliases}

    @http.route('/sale_plan', type='http', auth='user', methods=['GET', 'POST'])
    def sale_plan_page(self, **kwargs):
        return request.make_response(_PAGE, headers=_H)

    @http.route('/api/sale_plan/data', type='json', auth='user', methods=['POST'])
    def api_sale_plan_data(self, search='', warehouse_id='all', delivery_status='all',
                           stock_status='all', packing_status='all',
                           date_from='', date_to='', po_date_from='', po_date_to='',
                           done_date_from='', done_date_to='',
                           po_status='all', saler_code='', htgh='', delivery_type='all',
                           tag_ids='', limit=250, offset=0, show_completed=False,
                           mine_only=False, **kwargs):
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
                filter_mine=bool(mine_only),
            )
            return {'status': 'success', 'data': result}
        except Exception as e:
            _logger.exception('sale_plan API error')
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/sale_plan/preview_pick_slip', type='json', auth='user', methods=['POST'])
    def api_sale_plan_preview_pick_slip(self, picking_id=None, **kwargs):
        """Bước 1 (dialog chi tiết phiếu): chỉ render PDF xem trước, KHÔNG tạo hàng chờ / KHÔNG
        đánh dấu đã in. Xem services/delivery_planner_iot_print.py."""
        if not picking_id:
            return {'success': False, 'message': 'Thiếu picking_id'}
        try:
            return request.env['hlv.delivery.planner.service'].sudo().preview_pick_slip(picking_id)
        except Exception as e:
            _logger.exception('sale_plan preview_pick_slip error')
            return {'success': False, 'message': str(e)}

    @http.route('/api/sale_plan/confirm_print_pick_slip', type='json', auth='user', methods=['POST'])
    def api_sale_plan_confirm_print_pick_slip(self, picking_id=None, **kwargs):
        """Bước 2 (dialog chi tiết phiếu, sau khi đã xem trước): gửi yêu cầu in phiếu này vào
        hàng chờ theo kho (hlv.iot.print.queue) — kho mở "Điều phối Giao hàng > Hàng chờ in (IoT)"
        trong backend để tự động in thật. Xem services/delivery_planner_iot_print.py."""
        if not picking_id:
            return {'success': False, 'message': 'Thiếu picking_id'}
        try:
            return request.env['hlv.delivery.planner.service'].sudo().confirm_print_pick_slip(picking_id)
        except Exception as e:
            _logger.exception('sale_plan confirm_print_pick_slip error')
            return {'success': False, 'message': str(e)}

    @http.route('/api/sale_plan/picking_print_log', type='json', auth='user', methods=['POST'])
    def api_sale_plan_picking_print_log(self, picking_id=None, **kwargs):
        """Tab "Nhật ký" trên dialog chi tiết phiếu: lịch sử các yêu cầu in gắn thẳng vào phiếu
        này (không cần mò trong danh sách chung hàng chờ). Xem services/delivery_planner_iot_print.py."""
        if not picking_id:
            return {'success': False, 'message': 'Thiếu picking_id'}
        try:
            return request.env['hlv.delivery.planner.service'].sudo().get_print_log_for_picking(picking_id)
        except Exception as e:
            _logger.exception('sale_plan picking_print_log error')
            return {'success': False, 'message': str(e)}

    @http.route('/api/sale_plan/print_queue', type='json', auth='user', methods=['POST'])
    def api_sale_plan_print_queue(self, **kwargs):
        """Danh sách cho drawer "Yêu cầu in" trên /sale_plan — xem
        hlv.iot.print.queue.get_recent_for_sale_plan()."""
        try:
            Queue = request.env['hlv.iot.print.queue'].sudo()
            items = Queue.get_recent_for_sale_plan(limit=200)
            printer_status = Queue.get_printer_status_by_warehouse()
            return {'status': 'success', 'items': items, 'printer_status': printer_status}
        except Exception as e:
            _logger.exception('sale_plan print_queue error')
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/sale_plan/check_changes', type='json', auth='user', methods=['POST'])
    def api_check_changes(self, **kwargs):
        """Lightweight endpoint: returns a fingerprint (max write_date + record count)
        so the frontend can detect changes without reloading heavy data."""
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

    @http.route('/api/sale_plan/report_order', type='json', auth='user', methods=['POST'])
    def api_report_order(self, order_id=None, reason='', **kwargs):
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

    @http.route('/api/sale_plan/messages', type='json', auth='user', methods=['POST'])
    def api_sale_plan_messages(self, order_id=None, **kwargs):
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

    @http.route('/api/sale_plan/send_message', type='json', auth='user', methods=['POST'])
    def api_sale_plan_send_message(self, order_id=None, body='', author_name='', attachments=None, **kwargs):
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
                mention_aliases = [row['alias'] for row in _get_sale_plan_alias_rows(request.env)]
                formatted_body = _format_message_body_with_mentions(body, mention_aliases)
                if author_name:
                    safe_body = Markup('<p><strong>[%s]</strong> %s</p>') % (
                        Markup.escape(author_name), formatted_body)
                else:
                    safe_body = Markup('<p>%s</p>') % formatted_body
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
                so.sudo().with_context(skip_delivery_planner_data_bus=True).write({'x_plan_unread_message': True})
            
            # Send real-time bus notification to the delivery planner dashboard
            try:
              payload = {
                'so_id': so.id,
                'so_name': so.name,
                'author_name': author_name or 'Khách hàng',
                'body': body,
                'message_id': posted_msg.id if posted_msg else False,
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
              try:
                _push_backend_message_webpush(request.env, payload)
              except Exception:
                _logger.exception('Delivery Planner Web Push send error')
            except Exception as e:
                _logger.warning(f"Delivery Planner Bus send error: {e}")

            if body:
                try:
                    _push_public_mention_event(request.env, so, body, author_name or 'Khach hang')
                except Exception:
                    _logger.exception('sale_plan public mention event error')

            return {'status': 'success'}
        except Exception as e:
            _logger.exception('send_message error')
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/sale_plan/current_alias', type='json', auth='user', methods=['POST'])
    def api_sale_plan_current_alias(self, **kwargs):
        aliases = _get_user_sale_plan_aliases(request.env.user)
        return {'status': 'success', 'alias': aliases[0] if aliases else '', 'aliases': aliases}

    @http.route('/api/sale_plan/mention_aliases', type='json', auth='user', methods=['POST'])
    def api_sale_plan_mention_aliases(self, **kwargs):
        return {'status': 'success', 'aliases': _get_sale_plan_alias_rows(request.env)}

    def _sale_plan_mention_notif_payloads(self, aliases):
        aliases = [a for a in aliases if a]
        if not aliases:
            return []
        records = request.env['hlv.sale.plan.mention.notification'].sudo().search([
            ('alias', 'in', aliases),
        ], order='create_date desc, id desc', limit=100)
        return [{
            'id': rec.id,
            'notification_id': rec.id,
            'so_id': rec.sale_order_id.id,
            'so_name': rec.so_name or (rec.sale_order_id.name if rec.sale_order_id else ''),
            'author_name': rec.author_name or '',
            'body': rec.body or '',
            'preview': rec.preview or '',
            'mentions': _split_mention_aliases(rec.mentions or rec.alias),
            'alias': rec.alias,
            'unread': not rec.is_read,
            'ts': int(fields.Datetime.to_datetime(rec.create_date).timestamp()) if rec.create_date else 0,
        } for rec in records]

    @http.route('/api/sale_plan/mention_notifications', type='json', auth='user', methods=['POST'])
    def api_sale_plan_mention_notifications(self, **kwargs):
        aliases = _get_user_sale_plan_aliases(request.env.user)
        return {'status': 'success', 'events': self._sale_plan_mention_notif_payloads(aliases)}

    @http.route('/api/sale_plan/mention_notifications/read', type='json', auth='user', methods=['POST'])
    def api_sale_plan_mention_notifications_read(self, notification_ids=None, alias='', all_aliases=False, **kwargs):
        aliases = _get_user_sale_plan_aliases(request.env.user)
        domain = [('alias', 'in', aliases)]
        if notification_ids:
            try:
                ids = [int(x) for x in notification_ids]
            except Exception:
                ids = []
            domain.append(('id', 'in', ids))
        elif alias and not all_aliases:
            alias = _normalize_mention_alias(alias)
            if alias in aliases:
                domain.append(('alias', '=', alias))
            else:
                return {'status': 'success'}
        request.env['hlv.sale.plan.mention.notification'].sudo().search(domain).write({'is_read': True})
        return {'status': 'success', 'events': self._sale_plan_mention_notif_payloads(aliases)}

    @http.route('/api/sale_plan/mention_notifications/clear', type='json', auth='user', methods=['POST'])
    def api_sale_plan_mention_notifications_clear(self, alias='', all_aliases=False, **kwargs):
        aliases = _get_user_sale_plan_aliases(request.env.user)
        domain = [('alias', 'in', aliases)]
        if alias and not all_aliases:
            alias = _normalize_mention_alias(alias)
            if alias in aliases:
                domain.append(('alias', '=', alias))
            else:
                return {'status': 'success'}
        request.env['hlv.sale.plan.mention.notification'].sudo().search(domain).unlink()
        return {'status': 'success', 'events': self._sale_plan_mention_notif_payloads(aliases)}


    @http.route('/api/sale_plan/attachment/<int:att_id>', type='http', auth='user', methods=['GET'], csrf=False)
    def api_sale_plan_attachment(self, att_id, **kwargs):
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

    @http.route('/api/sale_plan/export_excel', type='http', auth='user', methods=['GET'], csrf=False)
    def api_export_excel(self, **kwargs):
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
                filter_mine=bool(kwargs.get('filter_mine', '')),
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

    @http.route('/api/sale_plan/export_picking_excel', type='http', auth='user', methods=['GET'], csrf=False)
    def api_export_picking_excel(self, **kwargs):
        """Export OUT pickings (state=done) of the filtered sale orders.
        Bao gồm phiếu đã xuất kho hoàn toàn hoặc xuất kho 1 phần (tạo backorder)
        — tức là tất cả stock.picking có picking_type_code='outgoing' và state='done'
        thuộc các đơn hàng trong bộ lọc hiện tại.
        """
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
                filter_mine=bool(kwargs.get('filter_mine', '')),
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
            # Nếu người dùng chọn "Hoàn thành từ/đến", filter thêm trực tiếp.
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

    @http.route('/api/sale_plan/export_picking_simple_excel', type='http', auth='user', methods=['GET'], csrf=False)
    def api_export_picking_simple_excel(self, **kwargs):
        """Export giản lược OUT pickings (state=done) — mỗi hàng = 1 phiếu, không có dòng sản phẩm.
        Columns: Mã phiếu XK, Đơn hàng, Trạng thái phiếu, Trạng thái ĐH,
                 Kho, Ngày hoàn thành, Tổng tiền trước thuế, Tổng tiền sau thuế.
        """
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
                filter_mine=bool(kwargs.get('filter_mine', '')),
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
