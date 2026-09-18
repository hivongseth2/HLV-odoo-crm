"""Tra toạ độ cho địa điểm, và mồi kết quả sang kho toạ độ.

Tách khỏi ``vtracking_place.py`` để file đó chỉ còn mô hình dữ liệu. Ở đây là một luồng
riêng: máy tra → người duyệt → đẩy sang kho toạ độ dùng chung.

Bước cuối quan trọng: điểm giao mang toạ độ người ghim tay, chính xác hơn hẳn máy tra.
Không đẩy sang kho toạ độ thì mỗi phiếu có địa chỉ tương tự lại tốn một lượt gọi Google
để nhận về một kết quả kém hơn thứ đã nằm sẵn trong hệ thống.
"""

import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.hlv_geo_utils.tools.geo_text import parse_latlng

_logger = logging.getLogger(__name__)

# Nominatim giới hạn 1 request/giây; Google tính tiền theo lượt. Cron chạy lô nhỏ để
# không bị chặn IP và không đốt quota trong một lần.
GEOCODE_BATCH_SIZE = 20


class HlvVtrackingPlaceGeo(models.Model):
    _inherit = 'hlv.vtracking.place'

    # ------------------------------------------------------------------
    # Geocode: máy tra trước, người duyệt sau
    # ------------------------------------------------------------------
    def _geocode_one(self):
        """Gọi ``base.geocoder`` cho một địa điểm. Không tự viết HTTP client.

        Nhà cung cấp (OpenStreetMap hay Google) do ``base_geolocalize`` quyết định qua
        tham số hệ thống — xem ô "Nhà cung cấp tra toạ độ" ở cấu hình V-Tracking.
        """
        self.ensure_one()
        address = self._address_for_geocode()
        if not address:
            self.write({'geo_state': 'failed', 'geo_raw_result': 'Không có địa chỉ để tra.'})
            return False
        try:
            result = self.env['base.geocoder'].sudo().geo_find(address)
        except Exception as exc:  # noqa: BLE001 — provider lỗi không được làm gãy cả lô
            _logger.warning('Tra toạ độ lỗi cho "%s": %s', self.display_name, exc)
            self.write({'geo_state': 'failed', 'geo_raw_result': 'Lỗi khi tra: %s' % exc})
            return False
        if not result:
            self.write({
                'geo_state': 'failed',
                'geo_raw_result': 'Không tìm thấy toạ độ cho: %s' % address,
            })
            return False
        self.write({
            'latitude': result[0],
            'longitude': result[1],
            'geo_source': 'geocode',
            'geo_state': 'pending_review',
            'geo_raw_result': json.dumps(
                {'address': address, 'lat': result[0], 'lng': result[1]}, ensure_ascii=False,
            ),
        })
        return True

    def action_geocode_now(self):
        """Tra lại toạ độ rồi báo kết quả."""
        return self._geocode_notification(self._geocode_now_silently(), len(self))

    def _geocode_now_silently(self):
        """Tra toạ độ cho cả recordset, trả về SỐ địa điểm tra được.

        Bỏ qua địa điểm đã nhập tay: toạ độ người dán là nguồn đáng tin nhất, máy không
        được đè lên.

        Không trả thông báo để dùng được cả khi tra chỉ là bước phụ của việc khác (tạo
        địa điểm hàng loạt) — việc đó đã có màn hình kết quả riêng.
        """
        return sum(
            1 for place in self
            if place.geo_state != 'manual' and place._geocode_one()
        )

    def _geocode_notification(self, done, total):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tra toạ độ',
                'message': 'Tra được %s/%s địa điểm. Kết quả máy tra cần duyệt trước khi '
                           'dùng — mở bộ lọc "Chờ duyệt" để soát.' % (done, total),
                'type': 'success' if done else 'warning',
                'sticky': False,
            },
        }

    def _address_cache_variants(self):
        """Các cách viết địa chỉ của điểm này, đều nên trỏ về cùng một toạ độ.

        Không chỉ mồi mỗi chuỗi ``_address_for_geocode()``: chuỗi đó có thể kèm TÊN điểm ở
        đầu, trong khi phiếu giao thường chỉ ghi phần địa chỉ. Mồi cả hai cách viết thì
        phiếu ghi kiểu nào cũng tra trúng. Nhiều khoá cùng trỏ một toạ độ chính là việc
        một cache phải làm, không phải trùng lặp dữ liệu.
        """
        self.ensure_one()
        partner = self.partner_id
        parts = [partner.street, partner.street2, partner.city,
                 partner.state_id.name, partner.country_id.name] if partner else []
        variants = [
            self._address_for_geocode(),
            (self.address or '').strip(),
            ', '.join(part.strip() for part in parts if part and part.strip()),
        ]
        return [variant for variant in dict.fromkeys(variants) if variant]

    def _seed_address_cache(self):
        """Đẩy toạ độ của điểm này vào kho toạ độ để lần sau khỏi gọi geocoder.

        Chỉ đẩy toạ độ ĐÁNG TIN (đã duyệt hoặc nhập tay). Toạ độ máy tra chưa ai duyệt mà
        đem mồi thì chỉ nhân bản một phỏng đoán.

        Trả về số ĐIỂM đã mồi được (không phải số bản ghi kho toạ độ): người dùng đang
        đếm điểm, không đếm cách viết.
        """
        Address = self.env['hlv.vtracking.address']
        seeded = 0
        for place in self:
            if place.geo_state not in ('confirmed', 'manual') or not place.has_coords:
                continue
            done = False
            for address in place._address_cache_variants():
                if Address.seed(address, place.latitude, place.longitude):
                    done = True
            seeded += 1 if done else 0
        return seeded

    def action_seed_address_cache(self):
        """Nút mồi kho toạ độ cho các điểm đang chọn."""
        seeded = self._seed_address_cache()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Mồi kho toạ độ',
                'message': 'Đã đưa %s/%s địa điểm vào kho toạ độ. Phiếu có địa chỉ giống '
                           'sẽ tra trúng ngay, không gọi ra ngoài.' % (seeded, len(self)),
                'type': 'success' if seeded else 'warning',
                'sticky': False,
            },
        }

    def action_confirm_geo(self):
        """Duyệt toạ độ máy đoán."""
        for place in self:
            if not place.has_coords:
                raise UserError('Địa điểm "%s" chưa có toạ độ để duyệt.' % place.name)
            place.write({
                'geo_state': 'confirmed',
                'geo_checked_by_id': self.env.user.id,
                'geo_checked_at': fields.Datetime.now(),
            })
        # Duyệt xong là toạ độ đáng tin — mồi ngay vào kho để phiếu sau khỏi gọi geocoder.
        self._seed_address_cache()
        return True

    def action_save_manual_geo(self):
        """Lưu toạ độ dán tay từ ô ``geo_input``."""
        for place in self:
            parsed = parse_latlng(place.geo_input)
            if not parsed:
                raise UserError(
                    'Không đọc được toạ độ "%s". Dán đúng dạng: 10.78950, 106.99179'
                    % (place.geo_input or '')
                )
            place.write({
                'latitude': parsed[0],
                'longitude': parsed[1],
                'geo_source': 'manual',
                'geo_state': 'manual',
                'geo_input': False,
                'geo_checked_by_id': self.env.user.id,
                'geo_checked_at': fields.Datetime.now(),
            })
        self._seed_address_cache()
        return True

    def action_open_gmaps(self):
        self.ensure_one()
        if not self.map_url:
            raise UserError('Địa điểm này chưa có toạ độ.')
        return {'type': 'ir.actions.act_url', 'url': self.map_url, 'target': 'new'}

    @api.model
    def _cron_geocode_pending(self, limit=GEOCODE_BATCH_SIZE):
        """Tra toạ độ cho địa điểm chưa tra. KHÔNG đụng địa điểm đã duyệt/nhập tay."""
        places = self.search([('geo_state', '=', 'none'), ('active', '=', True)], limit=limit)
        done = sum(1 for place in places if place._geocode_one())
        if places:
            _logger.info('Tra toạ độ địa điểm: xử lý %s, thành công %s', len(places), done)
        return done
