"""Đọc thân request của các endpoint GHI dữ liệu nền — một chỗ, luật giống nhau.

Ném ``UserError`` (thành 422) khi giá trị sai: bên gọi là AI, câu lỗi phải nói rõ ô nào
sai và giá trị hợp lệ là gì để nó tự sửa được ở lần gọi sau.
"""

from odoo.addons.hlv_geo_utils.tools.geo_text import parse_latlng
from odoo.exceptions import UserError


def coords_from_body(body):
    """``{"latitude", "longitude"}`` hoặc ``{"coords": "10.78950, 106.99179"}`` -> (lat, lng).

    Không có ô toạ độ nào thì trả None. Có mà sai thì báo lỗi, không lặng lẽ bỏ qua.
    """
    if body.get('coords'):
        parsed = parse_latlng(body['coords'])
        if not parsed:
            raise UserError('Không đọc được "coords": %s. Dạng đúng: "10.78950, 106.99179".'
                            % body['coords'])
        return parsed
    if body.get('latitude') in (None, '') and body.get('longitude') in (None, ''):
        return None
    parsed = parse_latlng('%s, %s' % (body.get('latitude'), body.get('longitude')))
    if not parsed:
        raise UserError('"latitude"/"longitude" không hợp lệ: %s, %s.'
                        % (body.get('latitude'), body.get('longitude')))
    return parsed


def pick_values(body, record, allowed):
    """Lấy các ô được phép sửa từ ``body``, kiểm theo kiểu field của ``record``.

    allowed: tuple tên field. Ô không có trong ``body`` thì bỏ qua (không xoá). Truyền
    ``null`` để xoá giá trị ô đó.

    - selection: phải là một trong các mã hợp lệ (báo lỗi kèm danh sách mã)
    - many2one: id số nguyên, bản ghi phải tồn tại
    - many2many: danh sách id, ghi ĐÈ cả danh sách (``null`` hoặc ``[]`` là xoá hết)
    - integer / float / char / text / boolean: ép kiểu
    """
    values = {}
    for name in allowed:
        if name not in body:
            continue
        raw = body[name]
        field = record._fields[name]
        if field.type == 'many2many':
            values[name] = [(6, 0, _to_ids(raw, name, record, field))]
            continue
        if raw is None:
            values[name] = False
            continue
        if field.type == 'selection':
            codes = [code for code, _label in field._description_selection(record.env)]
            if raw not in codes:
                raise UserError('"%s" phải là một trong: %s (nhận được "%s").'
                                % (name, ', '.join(codes), raw))
            values[name] = raw
        elif field.type == 'many2one':
            target = record.env[field.comodel_name].browse(_to_int(raw, name)).exists()
            if not target:
                raise UserError('"%s": không có %s id %s.' % (name, field.comodel_name, raw))
            values[name] = target.id
        elif field.type == 'integer':
            values[name] = _to_int(raw, name)
        elif field.type == 'float':
            values[name] = _to_float(raw, name)
        elif field.type == 'boolean':
            values[name] = bool(raw)
        else:
            values[name] = str(raw).strip()
    return values


def _to_ids(raw, name, record, field):
    """Danh sách id cho một ô many2many. Kiểm bản ghi có thật để không ghi id rác."""
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise UserError('"%s" phải là danh sách id, nhận được "%s".' % (name, raw))
    ids = [_to_int(item, name) for item in raw]
    found = record.env[field.comodel_name].browse(ids).exists()
    missing = sorted(set(ids) - set(found.ids))
    if missing:
        raise UserError('"%s": không có %s id %s.'
                        % (name, field.comodel_name, ', '.join(str(i) for i in missing)))
    return found.ids


def _to_int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise UserError('"%s" phải là số nguyên, nhận được "%s".' % (name, value)) from exc


def _to_float(value, name):
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise UserError('"%s" phải là số, nhận được "%s".' % (name, value)) from exc
