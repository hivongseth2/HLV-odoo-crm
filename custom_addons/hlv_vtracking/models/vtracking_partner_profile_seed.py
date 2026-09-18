"""Mồi thói quen khách đã biết vào các điểm giao đang có.

Không để ở ``data/*.xml``: dữ liệu XML phải trỏ tới bản ghi bằng xmlid, mà điểm giao do
người dùng tự nhập từ bản đồ nên module không biết trước id của chúng. Khớp theo TÊN là
cách duy nhất chạy được, và khớp theo tên thì phải chạy sau khi điểm đã tồn tại — tức là
bằng một nút bấm, không phải bằng dữ liệu cài đặt.

Chạy lại nhiều lần được: chỉ điền vào ô còn để trống, không đè lên thứ người đã sửa.
"""

import logging

from odoo import api, models

from ..tools.vtracking_habits import match_known_habits

_logger = logging.getLogger(__name__)


class HlvVtrackingPartnerProfileSeed(models.Model):
    _inherit = 'hlv.vtracking.partner.profile'

    @api.model
    def seed_known(self, places=None):
        """Tạo/bổ sung thói quen cho các điểm khớp bảng đã biết.

        :param places: recordset điểm giao; để trống thì quét mọi điểm của công ty hiện tại
        :returns: dict ``{'created', 'updated', 'skipped'}``
        """
        if places is None:
            places = self.env['hlv.vtracking.place'].search([
                ('company_id', '=', self.env.company.id),
            ])
        result = {'created': 0, 'updated': 0, 'skipped': 0}
        for place in places:
            habits = match_known_habits(place.name) or match_known_habits(
                place.partner_id.commercial_partner_id.name
            )
            if not habits:
                continue
            profile = place.profile_id
            if not profile:
                self.create(dict(habits, place_id=place.id, company_id=place.company_id.id))
                result['created'] += 1
                continue
            filled = profile._fill_blanks(habits)
            result['updated' if filled else 'skipped'] += 1
        _logger.info(
            'V-Tracking: mồi thói quen khách — tạo %(created)s, bổ sung %(updated)s, '
            'bỏ qua %(skipped)s (đã có người sửa).', result,
        )
        return result

    def _fill_blanks(self, habits):
        """Điền các ô còn TRỐNG theo ``habits``. Trả về True nếu có ghi gì đó.

        Ô đã có giá trị thì giữ nguyên, kể cả khi giá trị đó khác bảng: người điều phối
        gặp khách hằng ngày nên họ đúng hơn bảng mồi lấy từ hội thoại cũ.
        """
        self.ensure_one()
        values = {}
        for field_name, value in habits.items():
            current = self[field_name]
            # 'none' là mặc định của procedure_required, coi như chưa ai đụng tới.
            if current in (False, '', 0, 'none'):
                values[field_name] = value
        if not values:
            return False
        self.write(values)
        return True

    @api.model
    def action_seed_known(self):
        """Nút "Mồi thói quen đã biết" trên menu."""
        result = self.seed_known()
        total = result['created'] + result['updated']
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Mồi thói quen khách',
                'message': (
                    'Tạo mới %(created)s, bổ sung %(updated)s, giữ nguyên %(skipped)s bộ '
                    'người đã sửa. Điểm chưa nhập thì mồi lại sau khi nhập xong.' % result
                ),
                'type': 'success' if total else 'warning',
                'sticky': False,
            },
        }
