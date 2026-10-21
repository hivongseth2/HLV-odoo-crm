import logging
import os
from collections import OrderedDict
from datetime import datetime, timedelta

from odoo import models, api, fields, tools
from markupsafe import Markup
import re
import pytz

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
_ALLOWED_CHAT_ATTACHMENT_MIMES = {
    'application/msword',
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/csv',
}
_ALLOWED_CHAT_ATTACHMENT_EXTS = {'.doc', '.docx', '.pdf', '.xls', '.xlsx', '.csv'}
_MAX_CHAT_ATTACHMENT_BYTES = 20 * 1024 * 1024


_MENTION_RE = re.compile(r'@([^\s@,;:!?()\[\]{}<>]+)')
_PUBLIC_AUTHOR_RE = re.compile(r'^\[([^\]]{1,80})\]\s*(.*)$', re.S)
_PUBLIC_AUTHOR_HTML_RE = re.compile(r'<strong[^>]*>\s*\[([^\]]{1,80})\]\s*</strong>\s*', re.I)
_SYSTEM_AUTHOR_RE = re.compile(r'\b(odoobot|odoo\s*bot|odoo\s*system)\b', re.I)


def _message_plain_text(body):
    try:
        plain = tools.html2plaintext(body or '')
    except Exception:
        plain = re.sub(r'<[^>]+>', ' ', body or '')
    plain = plain.replace('\xa0', ' ')
    return re.sub(r'[ \t\r\f\v]+', ' ', plain).strip()


def _split_public_author_prefix(body, plain):
    html_match = _PUBLIC_AUTHOR_HTML_RE.search(body or '')
    if html_match:
        author = (html_match.group(1) or '').strip()
        clean_body = re.sub(
            r'^[\s*_`]*\[' + re.escape(author) + r'\][\s*_`]*',
            '',
            plain or '',
            count=1,
        ).strip()
        return author, clean_body
    match = _PUBLIC_AUTHOR_RE.match(plain or '')
    if not match:
        return '', plain or ''
    return (match.group(1) or '').strip(), (match.group(2) or '').strip()


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


_logger = logging.getLogger(__name__)


class DeliveryPlannerServiceMessages(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    @api.model
    def get_order_messages(self, order_id):
        so = self.env['sale.order'].browse(int(order_id))
        if not so.exists():
            return []

        # TZ user (fallback Asia/Ho_Chi_Minh) – mail.message.date lưu UTC,
        # cells fronend hiển thị sai 7h nếu không convert.
        try:
            user_tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'Asia/Ho_Chi_Minh')
        except Exception:
            user_tz = pytz.UTC

        picking_ids = so.picking_ids.ids
        domain = [
            '|',
            '&', ('model', '=', 'sale.order'), ('res_id', '=', so.id),
            '&', ('model', '=', 'stock.picking'), ('res_id', 'in', picking_ids),
        ]
        messages = self.env['mail.message'].search(domain, order='date desc', limit=200)
        picking_name_map = {p.id: p.name for p in so.picking_ids}
        result = []
        for msg in messages:
            plain = re.sub(r'<[^>]+>', '', msg.body or '').strip()
            has_att = bool(msg.attachment_ids)
            if not plain and not has_att:
                continue
            if plain and _SKIP_MSG_RE.search(plain):
                continue
            attachments = [{
                'id': att.id, 'name': att.name or '',
                'mimetype': att.mimetype or 'application/octet-stream',
                'file_size': att.file_size or 0,
            } for att in msg.attachment_ids]
            origin = ''
            if msg.model == 'stock.picking':
                origin = picking_name_map.get(msg.res_id, '')
            local_dt = msg.date.replace(tzinfo=pytz.UTC).astimezone(user_tz) if msg.date else None
            result.append({
                'id': msg.id,
                'date': local_dt.strftime('%d/%m/%Y %H:%M') if local_dt else '',
                'author': msg.author_id.name if msg.author_id else (msg.email_from or ''),
                'body': msg.body or '',
                'origin': origin,
                'attachments': attachments,
            })
        return result

    @api.model
    def _sale_plan_message_date_bounds(self, date_from, date_to=None, tz_name='Asia/Ho_Chi_Minh'):
        date_from = (date_from or '').strip()
        date_to = (date_to or date_from or '').strip()
        user_tz = pytz.timezone(tz_name or 'Asia/Ho_Chi_Minh')
        start_local = user_tz.localize(datetime.strptime(date_from, '%Y-%m-%d'))
        end_local = user_tz.localize(datetime.strptime(date_to, '%Y-%m-%d')) + timedelta(days=1)
        start_utc = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        end_utc = end_local.astimezone(pytz.UTC).replace(tzinfo=None)
        return start_utc, end_utc

    @api.model
    def _is_system_message_author(self, message):
        author = message.author_id
        author_text = ' '.join(filter(None, [
            author.name if author else '',
            author.email if author else '',
            message.email_from or '',
        ])).strip()
        return bool(author_text and _SYSTEM_AUTHOR_RE.search(author_text))

    @api.model
    def _is_user_sale_plan_message(self, message, plain):
        if message.message_type != 'comment':
            return False
        has_att = bool(message.attachment_ids)
        if not plain and not has_att:
            return False
        if plain and _SKIP_MSG_RE.search(plain):
            return False
        if self._is_system_message_author(message):
            return False
        return True

    @api.model
    def get_sale_plan_user_message_groups(self, date_from, date_to=None, sale_order_ids=None, tz_name='Asia/Ho_Chi_Minh'):
        """Return user-authored sale/picking messages in a local date range, grouped by sale order."""
        start_utc, end_utc = self._sale_plan_message_date_bounds(date_from, date_to=date_to, tz_name=tz_name)
        scoped = sale_order_ids is not None
        so_ids = []
        if scoped:
            so_ids = [int(so_id) for so_id in (sale_order_ids or []) if so_id]
            if not so_ids:
                return []

        Message = self.env['mail.message'].sudo()
        Picking = self.env['stock.picking'].sudo()

        domain = [
            ('date', '>=', fields.Datetime.to_string(start_utc)),
            ('date', '<', fields.Datetime.to_string(end_utc)),
            ('message_type', '=', 'comment'),
        ]
        if scoped:
            picking_ids = Picking.search([('sale_id', 'in', so_ids)]).ids
            if picking_ids:
                domain += [
                    '|',
                    '&', ('model', '=', 'sale.order'), ('res_id', 'in', so_ids),
                    '&', ('model', '=', 'stock.picking'), ('res_id', 'in', picking_ids),
                ]
            else:
                domain += [('model', '=', 'sale.order'), ('res_id', 'in', so_ids)]
        else:
            domain += [('model', 'in', ['sale.order', 'stock.picking'])]

        messages = Message.search(domain, order='date asc, id asc')
        if not messages:
            return []

        direct_so_ids = [msg.res_id for msg in messages if msg.model == 'sale.order' and msg.res_id]
        msg_picking_ids = [msg.res_id for msg in messages if msg.model == 'stock.picking' and msg.res_id]
        pickings = Picking.browse(msg_picking_ids).exists()
        picking_by_id = {picking.id: picking for picking in pickings}
        all_so_ids = set(direct_so_ids) | set(pickings.mapped('sale_id').ids)
        if scoped:
            all_so_ids &= set(so_ids)
        sale_orders = self.env['sale.order'].sudo().browse(list(all_so_ids)).exists()
        sale_by_id = {so.id: so for so in sale_orders}

        try:
            user_tz = pytz.timezone(tz_name or 'Asia/Ho_Chi_Minh')
        except Exception:
            user_tz = pytz.timezone('Asia/Ho_Chi_Minh')

        groups = OrderedDict()
        for msg in messages:
            if msg.model == 'sale.order':
                so = sale_by_id.get(msg.res_id)
                origin = 'SO'
            elif msg.model == 'stock.picking':
                picking = picking_by_id.get(msg.res_id)
                so = sale_by_id.get(picking.sale_id.id) if picking and picking.sale_id else None
                origin = picking.name if picking else ''
            else:
                continue
            if not so:
                continue

            plain = _message_plain_text(msg.body or '')
            if not self._is_user_sale_plan_message(msg, plain):
                continue

            public_author, clean_body = _split_public_author_prefix(msg.body or '', plain)
            author_name = public_author or (msg.author_id.name if msg.author_id else (msg.email_from or ''))
            attachments = ', '.join(att.name or '' for att in msg.attachment_ids if att.name)
            local_dt = msg.date.replace(tzinfo=pytz.UTC).astimezone(user_tz) if msg.date else None

            if so.id not in groups:
                groups[so.id] = {
                    'sale_order_id': so.id,
                    'order_name': so.name or '',
                    'customer_name': so.partner_id.name or '',
                    'warehouse_name': so.warehouse_id.name or '',
                    'saler_code': getattr(so, 'x_studio_misa_saler_code', '') or '',
                    'messages': [],
                }
            groups[so.id]['messages'].append({
                'message_id': msg.id,
                'date': local_dt.strftime('%d/%m/%Y %H:%M') if local_dt else '',
                'origin': origin or '',
                'author': author_name or '',
                'body': clean_body or plain,
                'attachments': attachments,
            })

        return sorted(groups.values(), key=lambda group: (group.get('order_name') or '', group.get('sale_order_id') or 0))

    @api.model
    def get_sale_plan_mention_aliases(self):
        users = self.env['res.users'].sudo().search([
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

    @api.model
    def post_order_message(self, order_id, body='', attachments=None):
        so = self.env['sale.order'].browse(int(order_id))
        if not so.exists():
            return False

        body = (body or '').strip()
        attachments = attachments or []
        if not body and not attachments:
            return False

        attachment_ids = []
        for att in attachments:
            if not isinstance(att, dict):
                continue
            name = (att.get('name') or 'file').strip()[:255]
            mimetype = (att.get('mimetype') or 'application/octet-stream').strip().lower()
            datas = (att.get('datas') or '').strip()
            if not datas:
                continue
            if not self._is_allowed_chat_attachment(name, mimetype):
                continue
            estimated_size = int(len(datas) * 0.75)
            if estimated_size > _MAX_CHAT_ATTACHMENT_BYTES:
                continue
            new_att = self.env['ir.attachment'].sudo().create({
                'name': name,
                'datas': datas,
                'mimetype': mimetype or 'application/octet-stream',
                'res_model': 'sale.order',
                'res_id': so.id,
                'type': 'binary',
            })
            attachment_ids.append(new_att.id)

        if not body and not attachment_ids:
            return False

        mention_aliases = [row['alias'] for row in self.get_sale_plan_mention_aliases()]
        safe_body = Markup('<p>%s</p>') % _format_message_body_with_mentions(body, mention_aliases) if body else Markup('<p><i>Tệp đính kèm</i></p>')
        so.message_post(
            body=safe_body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
            attachment_ids=attachment_ids,
        )
        if body:
            try:
                from ..controllers.sale_plan_controller import _push_public_mention_event
                _push_public_mention_event(self.env, so, body, self.env.user.name or '')
            except Exception:
                _logger.exception('delivery planner public mention event error')
        return True

    @api.model
    def _is_allowed_chat_attachment(self, name, mimetype):
        if mimetype and (mimetype.startswith('image/') or mimetype.startswith('video/')):
            return True
        if mimetype in _ALLOWED_CHAT_ATTACHMENT_MIMES:
            return True
        ext = os.path.splitext(name or '')[1].lower()
        return ext in _ALLOWED_CHAT_ATTACHMENT_EXTS
