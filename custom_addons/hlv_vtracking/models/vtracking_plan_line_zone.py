"""Suy cụm tuyến cho một điểm giao trong kế hoạch.

Tách khỏi ``vtracking_plan_line.py`` vì đây là một quy tắc riêng, đủ dài và đủ quan trọng
để đọc tách bạch: nó quyết định kế hoạch dùng định mức thời gian nào.

Nguyên tắc: **cụm suy từ TOẠ ĐỘ của địa chỉ giao**, không suy từ khách hàng. Một khách có
thể giao ở hai nơi thuộc hai cụm khác nhau (nhà máy và kho) — hỏi theo khách thì hai địa
chỉ ra cùng một đáp án và một trong hai sẽ sai.
"""

from odoo import api, models

from odoo.addons.hlv_vtracking.tools.vtracking_planning import (
    DEFAULT_ZONE_MATCH_KM, nearest_zone,
)


class HlvVtrackingPlanLineZone(models.Model):
    _inherit = 'hlv.vtracking.plan.line'

    @api.depends('latitude', 'longitude', 'place_id')
    def _compute_zone_id(self):
        """Cụm tuyến của điểm giao này, suy từ TOẠ ĐỘ trước hết.

        Thứ tự nguồn:

        1. **Toạ độ** của địa chỉ giao trên chứng từ → cụm của điểm mẫu gần nhất. Đây là
           nguồn chính, và là nguồn duy nhất xử lý đúng trường hợp một khách giao ở hai
           nơi thuộc hai cụm khác nhau.
        2. **Điểm giao của khách** → dự phòng khi chưa tra được toạ độ. Đoán, nên đánh dấu
           ``zone_uncertain``.
        3. Không có gì → để trống.

        Gán tay thì giữ nguyên: người biết rõ hơn máy, và máy đè lên thì họ không biết vì sao.
        """
        samples_by_company = {}
        for line in self:
            if line.zone_source == 'manual' and line.zone_id:
                line.zone_id = line.zone_id
                continue
            company_id = line.company_id.id or self.env.company.id
            if company_id not in samples_by_company:
                samples_by_company[company_id] = line._zone_samples(company_id)
            line._assign_zone(samples_by_company[company_id])

    def _zone_samples(self, company_id):
        """Các điểm giao đã biết chắc thuộc cụm nào — tập mẫu để so khoảng cách.

        Đọc MỘT lần cho cả recordset: compute chạy trên hàng chục dòng, mỗi dòng một truy
        vấn thì màn kế hoạch sẽ ì.
        """
        places = self.env['hlv.vtracking.place'].sudo().search([
            ('zone_id', '!=', False),
            ('has_coords', '=', True),
            ('company_id', '=', company_id),
        ])
        return [(place.zone_id.id, (place.latitude, place.longitude)) for place in places]

    def _assign_zone(self, samples):
        """Đặt cụm cho một dòng theo thứ tự nguồn đã nêu ở ``_compute_zone_id``."""
        self.ensure_one()
        coords = (self.latitude, self.longitude) if self.latitude and self.longitude else None
        near_km = (
            self.company_id or self.env.company
        ).vtracking_zone_match_km or DEFAULT_ZONE_MATCH_KM
        zone_id, distance, confident = nearest_zone(coords, samples, near_km)
        if zone_id:
            self.zone_id = zone_id
            self.zone_source = 'coords'
            self.zone_distance_km = distance
            self.zone_uncertain = not confident
            return
        fallback = self.place_id.zone_id
        self.zone_id = fallback.id or False
        self.zone_source = 'place' if fallback else 'none'
        self.zone_distance_km = 0.0
        # Đoán theo khách thì luôn là chưa chắc: khách có thể giao ở nơi khác lần này.
        self.zone_uncertain = bool(fallback)

    def _inverse_zone_id(self):
        """Người sửa cụm tay thì đánh dấu để máy không đè lên nữa."""
        for line in self:
            line.zone_source = 'manual' if line.zone_id else 'none'
            line.zone_distance_km = 0.0
            line.zone_uncertain = False
