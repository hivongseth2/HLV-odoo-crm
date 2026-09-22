"""Nhập luật khách từ file JSON của bộ điều phối chạy tay, có bước duyệt trước khi ghi.

Vì sao là wizard chứ không phải file dữ liệu trong module: file nguồn là **danh sách khách
hàng thật**, không được nằm trong mã nguồn; và luật còn được người điều phối bổ sung tiếp,
nên phải nhập lại được nhiều lần mà không mất thứ người dùng đã tự sửa.

Vì sao có bước duyệt: khớp tên không bao giờ sạch. "Thép Nam Kim" và "Tôn Nam Kim Phú Mỹ"
là một điểm nhưng Odoo để hai pháp nhân; "Nam Hoa" dễ nhận nhầm sang "Bao bì Nam Việt".
Máy đề xuất, người xác nhận.
"""

import base64
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools.vtracking_rules import (
    alias_map, match_keys, normalize, note_text, rules_from_file,
)

VALUE_LABELS = {
    'procedure_required': 'Thủ tục',
    'delivery_method': 'Kênh giao',
    'must_be_last': 'Điểm cuối chuyến',
    'extra_service_minutes': 'Phút lâu hơn',
    'receiving_to': 'Nhận đến',
}


class HlvVtrackingRuleImport(models.TransientModel):
    _name = 'hlv.vtracking.rule.import'
    _description = 'Nhập luật khách từ file'

    file_data = fields.Binary(string='File luật (JSON)', required=True)
    file_name = fields.Char(string='Tên file')
    source = fields.Char(
        string='Nguồn', required=True, default='khach.json',
        help='Ghi vào ghi chú của từng khách để sau này biết luật đến từ đâu.',
    )
    line_ids = fields.One2many('hlv.vtracking.rule.import.line', 'wizard_id', string='Đề xuất')
    state = fields.Selection(
        [('upload', 'Chọn file'), ('preview', 'Duyệt đề xuất')], default='upload',
    )
    matched_count = fields.Integer(compute='_compute_counts', string='Khớp được')
    problem_count = fields.Integer(compute='_compute_counts', string='Cần xử lý tay')

    @api.depends('line_ids.match_state')
    def _compute_counts(self):
        for wizard in self:
            states = wizard.line_ids.mapped('match_state')
            wizard.matched_count = states.count('matched')
            wizard.problem_count = len(states) - states.count('matched')

    # ------------------------------------------------------------------
    def action_load(self):
        """Đọc file, khớp tên với địa điểm, dựng bảng đề xuất. KHÔNG ghi gì."""
        self.ensure_one()
        data = self._read_file()
        aliases = alias_map(data)
        places = self._place_index()
        self.line_ids.unlink()

        values = []
        for item in rules_from_file(data):
            matches = self._match(item['key'], aliases, places)
            values.append((0, 0, {
                'customer_name': item['name'],
                'place_id': matches[0].id if len(matches) == 1 else False,
                'match_state': ('matched' if len(matches) == 1
                                else 'ambiguous' if matches else 'missing'),
                'candidate_count': len(matches),
                'payload': json.dumps(item['values'], ensure_ascii=False),
                'values_summary': self._summary(item['values']),
                'note_preview': note_text(item['notes'], self.source),
                'selected': len(matches) == 1,
            }))
        self.write({'line_ids': values, 'state': 'preview'})
        return self._reopen()

    def action_apply(self):
        """Ghi các dòng đã chọn vào Thói quen khách."""
        self.ensure_one()
        lines = self.line_ids.filtered(lambda line: line.selected and line.place_id)
        if not lines:
            raise UserError(_('Chưa chọn dòng nào có địa điểm để ghi.'))
        for line in lines:
            line._apply()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã nhập luật khách'),
                'message': _('%s khách được cập nhật thói quen.') % len(lines),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ------------------------------------------------------------------
    def _read_file(self):
        try:
            raw = base64.b64decode(self.file_data or b'')
            data = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            raise UserError(_('File không phải JSON đọc được: %s') % exc) from exc
        if not isinstance(data, dict):
            raise UserError(_('File phải là một JSON object như khach.json.'))
        return data

    def _place_index(self):
        """dict {khoá tên đã chuẩn hoá: địa điểm}. Gồm cả tên khách của điểm.

        Một điểm có thể vào bảng bằng hai khoá (tên điểm và tên khách) — cả hai đều là
        cách người ta gọi nó.
        """
        index = {}
        places = self.env['hlv.vtracking.place'].search([
            ('company_id', '=', self.env.company.id),
        ])
        for place in places:
            for name in (place.name, place.partner_id.display_name):
                key = normalize(name or '')
                if key:
                    index.setdefault(key, place)
        return index

    @staticmethod
    def _match(key, aliases, places):
        """Các địa điểm có thể là khách này. Luật khớp nằm ở ``tools/vtracking_rules``.

        Một địa điểm vào bảng bằng hai khoá (tên điểm và tên khách) nên phải khử trùng theo
        id, nếu không một điểm hiện ra thành hai ứng viên và người duyệt tưởng là hai chỗ.
        """
        found = {}
        for place_key in match_keys(key, places, aliases):
            place = places[place_key]
            found.setdefault(place.id, place)
        return list(found.values())

    @staticmethod
    def _summary(values):
        parts = []
        for field, value in values.items():
            label = VALUE_LABELS.get(field, field)
            if field == 'receiving_to':
                value = '%02d:%02d' % (int(value), round((value % 1) * 60))
            parts.append('%s = %s' % (label, value))
        return ' · '.join(parts) or '(chỉ ghi chú)'

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class HlvVtrackingRuleImportLine(models.TransientModel):
    _name = 'hlv.vtracking.rule.import.line'
    _description = 'Dòng đề xuất nhập luật khách'
    _order = 'match_state, customer_name'

    wizard_id = fields.Many2one('hlv.vtracking.rule.import', required=True, ondelete='cascade')
    customer_name = fields.Char(string='Khách trong file', readonly=True)
    place_id = fields.Many2one('hlv.vtracking.place', string='Địa điểm trong V-Tracking')
    match_state = fields.Selection(
        [('matched', 'Khớp một điểm'), ('ambiguous', 'Khớp nhiều điểm'),
         ('missing', 'Không tìm ra')],
        string='Khớp tên', readonly=True,
    )
    candidate_count = fields.Integer(string='Số điểm khớp', readonly=True)
    values_summary = fields.Char(string='Sẽ ghi', readonly=True)
    note_preview = fields.Text(string='Ghi chú sẽ thêm', readonly=True)
    payload = fields.Char(readonly=True)
    selected = fields.Boolean(string='Ghi', default=False)

    def _apply(self):
        """Ghi một dòng vào thói quen của điểm. Tạo thói quen nếu điểm chưa có."""
        self.ensure_one()
        place = self.place_id
        profile = place.profile_id
        values = json.loads(self.payload or '{}')
        if self.note_preview:
            # Nối vào ghi chú cũ chứ không đè: ghi chú cũ là thứ người ở kho tự viết.
            old = (profile.free_note or '').strip() if profile else ''
            values['free_note'] = ('%s\n\n%s' % (old, self.note_preview)).strip() \
                if self.note_preview not in old else old
        if profile:
            profile.write(values)
        else:
            self.env['hlv.vtracking.partner.profile'].create(dict(
                values, place_id=place.id, company_id=place.company_id.id,
            ))
        place.message_post(
            body='Nhập luật khách từ %s: %s' % (self.wizard_id.source, self.values_summary),
            message_type='notification',
        )
        return True
