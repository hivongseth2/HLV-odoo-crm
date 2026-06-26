import os

from odoo import models, api
from markupsafe import Markup
import re
import pytz

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
    r'|Đơn hàng được tạo',
    r'|🖨️',
    r'|👤',
    r'|Nhu cầu ban đầu đã được',
    r'|Đồng bộ MISA thành công',
    r'|The initial demand has',
    r'|The ordered quantity has been updated',
    r'|extra line with',
    r'|Đơn hàng tách kiện',
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

        safe_body = Markup('<p>%s</p>') % Markup.escape(body) if body else Markup('<p><i>Tệp đính kèm</i></p>')
        so.message_post(
            body=safe_body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
            attachment_ids=attachment_ids,
        )
        return True

    @api.model
    def _is_allowed_chat_attachment(self, name, mimetype):
        if mimetype and (mimetype.startswith('image/') or mimetype.startswith('video/')):
            return True
        if mimetype in _ALLOWED_CHAT_ATTACHMENT_MIMES:
            return True
        ext = os.path.splitext(name or '')[1].lower()
        return ext in _ALLOWED_CHAT_ATTACHMENT_EXTS
