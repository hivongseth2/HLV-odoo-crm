"""Tra toạ độ cho kho toạ độ: gọi nhà cung cấp, duyệt, dán tay.

Tách khỏi ``vtracking_address.py`` để file đó chỉ còn mô hình dữ liệu và luật tra-cache.
Ở đây là việc khác hẳn: đụng mạng, đụng tiền, và có thể hỏng vì lý do bên ngoài.
"""

import json
import logging

from odoo import models
from odoo.exceptions import UserError
from odoo.addons.hlv_geo_utils.tools.geo_text import parse_latlng

from .vtracking_address import is_inside_vietnam

_logger = logging.getLogger(__name__)


class HlvVtrackingAddressGeo(models.Model):
    _inherit = 'hlv.vtracking.address'

    # ------------------------------------------------------------------
    # Tra toạ độ
    # ------------------------------------------------------------------
    def _geocode(self):
        """Gọi ``base.geocoder`` cho các bản ghi chưa có toạ độ đã duyệt.

        Gửi đi bản ĐÃ CHUẨN HOÁ chứ không phải nguyên văn: bỏ dấu và mở viết tắt giúp
        provider khớp tốt hơn hẳn với địa chỉ gõ tắt kiểu "P.5, Q.GV".
        """
        done = 0
        for record in self:
            if record.geo_state == 'manual':
                # Toạ độ người dán tay là nguồn đáng tin nhất, máy không được đè lên.
                continue
            # Tính lại theo nhà cung cấp đang dùng: đổi từ OpenStreetMap sang Google rồi
            # bấm "Tra lại" phải gửi đi chuỗi hợp với Google, không phải chuỗi cũ.
            address = record._normalized_for_provider(record.raw_address)
            if address and address != record.normalized_address:
                record.normalized_address = address
            address = address or record.raw_address
            try:
                result = self.env['base.geocoder'].sudo().geo_find(address)
            except Exception as exc:  # noqa: BLE001 — provider lỗi không được làm gãy cả lô
                _logger.warning('Tra toạ độ lỗi cho "%s": %s', address, exc)
                record.write({'geo_state': 'failed', 'geo_raw_result': 'Lỗi khi tra: %s' % exc})
                continue
            if not result:
                record.write({
                    'geo_state': 'failed',
                    'geo_raw_result': 'Không tìm thấy toạ độ cho: %s' % address,
                })
                continue
            if not is_inside_vietnam(result[0], result[1]):
                # Không lưu toạ độ này: giữ lại thì nó lặng lẽ chui vào phép tính quãng
                # đường và làm hỏng cả kế hoạch. Thà để trống rồi dán tay.
                record.write({
                    'geo_state': 'failed',
                    'geo_raw_result': (
                        'Toạ độ tra được (%s, %s) nằm NGOÀI Việt Nam — nhà cung cấp đã khớp '
                        'nhầm sang nơi khác. Địa chỉ gửi đi: %s\n'
                        'Hãy sửa địa chỉ cho đầy đủ hơn (thêm tỉnh/thành, "Việt Nam") rồi '
                        'tra lại, hoặc dán toạ độ tay từ Google Maps.'
                        % (result[0], result[1], address)
                    ),
                })
                _logger.warning(
                    'V-Tracking: geocode trả toạ độ ngoài VN (%s, %s) cho "%s".',
                    result[0], result[1], address,
                )
                continue
            record.write({
                'latitude': result[0],
                'longitude': result[1],
                'geo_source': 'geocode',
                'geo_state': 'pending_review',
                'geo_raw_result': json.dumps(
                    {'address': address, 'lat': result[0], 'lng': result[1]}, ensure_ascii=False,
                ),
            })
            done += 1
        return done

    def action_geocode_retry(self):
        """Tra lại — dùng khi lần trước trượt hoặc khi đã đổi nhà cung cấp."""
        return self._geocode()

    def action_confirm(self):
        self.write({'geo_state': 'confirmed'})
        return True

    def action_save_manual_geo(self):
        for record in self:
            parsed = parse_latlng(record.geo_input)
            if not parsed:
                raise UserError(
                    'Không đọc được toạ độ "%s". Dán đúng dạng: 10.78950, 106.99179'
                    % (record.geo_input or '')
                )
            record.write({
                'latitude': parsed[0],
                'longitude': parsed[1],
                'geo_source': 'manual',
                'geo_state': 'manual',
                'geo_input': False,
            })
        return True

    def action_open_gmaps(self):
        self.ensure_one()
        if not self.has_coords:
            raise UserError('Bản ghi này chưa có toạ độ.')
        return {
            'type': 'ir.actions.act_url',
            'url': 'https://www.google.com/maps?q=%s,%s' % (self.latitude, self.longitude),
            'target': 'new',
        }
