"""Hội thoại (chatter) của một chứng từ, ở dạng AI đọc được.

Chatter là nơi sale, kho và khách dặn nhau những thứ không có ô nào để điền: "khách nghỉ
lễ đến 3/9, ngày 4/9 giao", "gọi trước 30 phút", "hàng dễ vỡ". Đó thường chính là thông
tin quyết định xếp đơn vào ngày nào — nên AI lập kế hoạch phải đọc được.
"""

from .serialize import iso_datetime, plain_text

DEFAULT_LIMIT = 30
MAX_LIMIT = 100

# Cắt mỗi tin nhắn: một email dán nguyên chữ ký và chuỗi trả lời có thể dài vài nghìn ký
# tự, mà phần có ích cho việc giao hàng gần như luôn nằm ở mấy dòng đầu.
MESSAGE_CHAR_LIMIT = 1200

# Loại tin do NGƯỜI viết: bình luận/ghi chú, email đến, email đi.
HUMAN_MESSAGE_TYPES = ('comment', 'email', 'email_outgoing')


def record_messages(record, limit=DEFAULT_LIMIT, include_system=False):
    """Tin nhắn trên chatter của một bản ghi, MỚI NHẤT TRƯỚC.

    Mặc định chỉ lấy tin do NGƯỜI viết (bình luận, ghi chú nội bộ, email). Tin hệ thống
    ("Báo giá đã xác nhận", dòng theo dõi đổi trạng thái) bị bỏ vì chúng lặp lại thứ AI đã
    đọc được từ field, và nhiều tới mức che mất lời dặn thật. ``include_system=True`` lấy
    cả chúng, kèm danh sách thay đổi field.

    Trả về list dict. Bản ghi không có chatter trả list rỗng.
    """
    if not record or 'message_ids' not in record._fields:
        return []
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    domain = [('model', '=', record._name), ('res_id', '=', record.id)]
    if not include_system:
        domain.append(('message_type', 'in', HUMAN_MESSAGE_TYPES))
    messages = record.env['mail.message'].sudo().search(domain, order='date desc, id desc', limit=limit)
    return [message_block(message, include_system) for message in messages]


def message_block(message, with_tracking=False):
    """Một tin nhắn ở dạng dict.

    ``is_internal_note`` phân biệt ghi chú nội bộ (chỉ nhân viên thấy) với tin gửi cho
    khách — lời dặn nội bộ kiểu "khách này hay huỷ" không phải thứ để nói lại với khách.
    """
    block = {
        'id': message.id,
        'date': iso_datetime(message.date),
        'author': message.author_id.name or message.email_from or None,
        'type': message.message_type,
        'is_internal_note': bool(message.subtype_id.internal) if message.subtype_id else False,
        'subject': message.subject or None,
        'body': plain_text(message.body, MESSAGE_CHAR_LIMIT) or None,
        'attachment_count': len(message.attachment_ids),
    }
    if with_tracking:
        block['changes'] = tracking_changes(message)
    return block


def tracking_changes(message):
    """Các thay đổi field ghi kèm một tin hệ thống: list ``{'field', 'old', 'new'}``.

    Dùng ``_tracking_value_format`` của Odoo khi có: giá trị cũ/mới nằm rải ở nhiều cột
    tuỳ kiểu field (char, integer, datetime...), tự đọc từng cột là viết lại thứ Odoo đã có.
    """
    trackings = message.sudo().tracking_value_ids
    if not trackings:
        return []
    if hasattr(trackings, '_tracking_value_format'):
        return [{
            'field': item.get('changedField'),
            'old': (item.get('oldValue') or {}).get('value') or None,
            'new': (item.get('newValue') or {}).get('value') or None,
        } for item in trackings._tracking_value_format()]
    return [{
        'field': tracking.field_id.field_description or tracking.field_id.name,
        'old': tracking.old_value_char or None,
        'new': tracking.new_value_char or None,
    } for tracking in trackings]


def latest_notes(records):
    """dict {id bản ghi: lời dặn gần nhất do người viết} cho cả recordset — MỘT truy vấn.

    Danh sách đơn chờ giao kèm sẵn dòng này để AI biết đơn nào có lời dặn mà không phải
    gọi chatter của từng đơn. Bản ghi chưa ai viết gì thì không có mặt trong dict.
    """
    if not records or 'message_ids' not in records._fields:
        return {}
    messages = records.env['mail.message'].sudo().search([
        ('model', '=', records._name),
        ('res_id', 'in', records.ids),
        ('message_type', 'in', HUMAN_MESSAGE_TYPES),
    ], order='date desc, id desc', limit=len(records) * 10)
    result = {}
    for message in messages:
        body = plain_text(message.body, 200)
        if body and message.res_id not in result:
            result[message.res_id] = {
                'date': iso_datetime(message.date),
                'author': message.author_id.name or message.email_from or None,
                'body': body,
            }
    return result
