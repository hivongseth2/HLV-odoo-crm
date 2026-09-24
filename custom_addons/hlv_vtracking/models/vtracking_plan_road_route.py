"""Lộ trình ĐƯỜNG THẬT của kế hoạch: lấy từ Google Routes một lần rồi lưu lại.

Tách khỏi ``vtracking_plan.py`` vì đây là mối quan tâm khép kín và có tính chất khác hẳn
phần còn lại của model: nó phụ thuộc một dịch vụ ngoài, có thể thất bại, tốn tiền theo
lượt gọi, và vì vậy phải được LƯU LẠI chứ không tính lại mỗi lần đọc. Toàn bộ số dự kiến
khác của kế hoạch (``distance_km``, ``total_minutes``) vẫn là field compute chạy offline —
bản đồ và API phải dùng được khi Google hỏng hoặc khi tính năng này chưa bật.

Vì sao phải cache chứ không gọi trực tiếp lúc vẽ bản đồ: bản đồ tự tải lại mỗi 30 giây.
Gọi API trong đường đọc đó là vừa đốt hạn mức cho thứ không đổi, vừa cộng thêm thời gian
chờ mạng (tới 20 giây/chuyến) vào một endpoint người dùng đang ngồi trước.
"""

import logging

from odoo import api, fields, models

from ..services.google_routes import RoadRouteError, fetch_road_route
from ..tools.vtracking_road_route import route_points, route_signature

_logger = logging.getLogger(__name__)

# Số chuyến tối đa mỗi lượt cron. Chặn trần để một ngày có nhiều chuyến mới không biến
# thành một loạt lời gọi API bất ngờ; phần còn lại lượt sau lấy tiếp.
CRON_BATCH = 20


class VtrackingPlanRoadRoute(models.Model):
    _inherit = 'hlv.vtracking.plan'

    road_distance_km = fields.Float(
        string='Km đường thật', readonly=True, copy=False, digits=(10, 1),
        help='Quãng đường theo đường đi thật do Google Routes trả về, cho cùng thứ tự ghé '
             'của kế hoạch này. Phạm vi giống ô "Quãng đường (km)": kho → điểm cuối, KHÔNG '
             'gồm chặng về kho, để hai con số so được với nhau.',
    )
    road_duration_minutes = fields.Integer(
        string='Phút chạy (Google)', readonly=True, copy=False,
        help='Thời gian CHẠY thuần theo Google, chưa tính thời gian đứng giao tại điểm. '
             'Không thay thế ô "Dự kiến" — ô đó dùng định mức đo từ chuyến thật, sát hơn '
             'với cách đội xe chạy.',
    )
    road_polyline = fields.Text(
        string='Đường vẽ (Google)', readonly=True, copy=False,
        help='Hình dạng đường đi ở dạng encoded polyline, để bản đồ vẽ nét liền theo đúng '
             'đường xe chạy thay cho nét đứt nối thẳng các điểm.',
    )
    road_route_signature = fields.Char(
        string='Dấu lộ trình đã lấy', readonly=True, copy=False,
        help='Toạ độ và thứ tự ghé tại thời điểm gọi API. Khác với hiện tại nghĩa là kế '
             'hoạch đã đổi sau đó, đường đang vẽ là của thứ tự cũ.',
    )
    road_route_synced_at = fields.Datetime(string='Lấy lúc', readonly=True, copy=False)
    road_route_error = fields.Char(
        string='Lỗi lấy lộ trình', readonly=True, copy=False,
        help='Lý do lần gọi gần nhất thất bại. Còn giá trị ở đây thì cron KHÔNG tự gọi lại '
             '— phải xử lý nguyên nhân rồi bấm lấy lại, để một chuyến hỏng không gọi API '
             'mỗi 10 phút suốt ngày.',
    )
    road_route_stale = fields.Boolean(
        string='Lộ trình đã cũ', compute='_compute_road_route_stale',
        help='Kế hoạch đã đổi điểm hoặc thứ tự ghé sau lần lấy lộ trình gần nhất.',
    )

    # Không store: giá trị chỉ là phép so hai chuỗi, tính lại rẻ hơn lưu. Vẫn khai depends
    # đầy đủ để nó được tính lại ngay trong cùng transaction khi người dùng kéo đổi thứ tự
    # điểm — thiếu depends là ô này còn hiện "đang mới" trong khi thứ tự đã khác.
    @api.depends('road_route_signature', 'line_ids.sequence',
                 'line_ids.latitude', 'line_ids.longitude',
                 'start_place_id.latitude', 'start_place_id.longitude')
    def _compute_road_route_stale(self):
        for plan in self:
            plan.road_route_stale = bool(
                plan.road_route_signature
                and plan.road_route_signature != plan._road_route_signature()
            )

    def _road_route_points(self):
        """Toạ độ để gọi API: dùng lại đúng điểm xuất phát và thứ tự ghé của phần tính chim
        bay (``_route_start`` / ``_route_stops``) — hai cách tính phải nói về cùng lộ trình,
        nếu không thì so km với nhau là so hai thứ khác nhau."""
        self.ensure_one()
        return route_points(self._route_start(), self._route_stops())

    def _road_route_signature(self):
        self.ensure_one()
        return route_signature(self._road_route_points())

    def _road_route_api_key(self):
        """Khoá Google dùng chung với phần tra toạ độ (base_geolocalize.google_map_api_key).

        Cố tình KHÔNG thêm khoá riêng: hai chỗ cùng giữ một khoá Google là kiểu lỗi mà
        người dùng đổi ở chỗ này rồi không hiểu vì sao chỗ kia vẫn hỏng — cùng lý do đã ghi
        ở res_company.geocode_google_key. Đổi lại, khoá đó phải được bật thêm Routes API
        trong Google Cloud Console, không chỉ Geocoding API.
        """
        return self.env['ir.config_parameter'].sudo().get_param(
            'base_geolocalize.google_map_api_key'
        ) or ''

    def _fetch_road_route(self):
        """Gọi API và ghi kết quả cho từng kế hoạch trong recordset.

        Luôn ghi lại kết quả — thành công thì xoá lỗi cũ, thất bại thì lưu lý do vào
        ``road_route_error`` và GIỮ NGUYÊN đường vẽ cũ (đường cũ còn đúng hơn là không có
        gì). Không raise: bên gọi là nút bấm và cron, cả hai đều cần đi tiếp cho các bản
        ghi còn lại.

        Trả về số kế hoạch lấy được lộ trình.
        """
        api_key = self._road_route_api_key()
        fetched = 0
        for plan in self:
            points = plan._road_route_points()
            try:
                result = fetch_road_route(api_key, points)
            except RoadRouteError as exc:
                plan.write({'road_route_error': str(exc)[:500]})
                continue
            if not result:
                plan.write({
                    'road_route_error': 'Google không tìm được đường đi qua hết các điểm '
                                        'của chuyến này — kiểm tra lại toạ độ các điểm.',
                })
                continue
            plan.write({
                'road_distance_km': result['distance_km'],
                'road_duration_minutes': result['duration_minutes'],
                'road_polyline': result['polyline'],
                'road_route_signature': route_signature(points),
                'road_route_synced_at': fields.Datetime.now(),
                'road_route_error': False,
            })
            fetched += 1
        return fetched

    def action_fetch_road_route(self):
        """Nút "Lấy lộ trình đường thật". Bấm là gọi API, kể cả khi đã có đường cũ — người
        bấm đang chủ động muốn lấy lại (VD vừa sửa toạ độ một điểm, hoặc vừa bật Routes API
        cho khoá sau một lần lỗi)."""
        fetched = self._fetch_road_route()
        failed = self.filtered('road_route_error')
        if failed:
            # Hiện lý do ngay thay vì raise: raise sẽ rollback luôn cái lỗi vừa ghi, xem
            # lại không còn dấu vết gì.
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'danger',
                    'sticky': True,
                    'title': 'Không lấy được lộ trình',
                    'message': failed[0].road_route_error,
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': 'Đã lấy lộ trình đường thật',
                'message': 'Lấy xong %d chuyến.' % fetched,
            },
        }

    @api.model
    def _cron_fetch_road_routes(self):
        """Lấy lộ trình cho các chuyến còn thiếu, từ hôm nay trở đi.

        Chỉ chuyến CHƯA có đường vẽ và CHƯA từng lỗi: chuyến đã lỗi phải có người xử lý
        nguyên nhân rồi bấm lấy lại, để một chuyến có toạ độ sai không gọi API mỗi 10 phút.
        Chuyến đã đổi thứ tự sau khi lấy (``road_route_stale``) cũng không tự lấy lại —
        người điều phối còn đang sắp, gọi lại mỗi lượt kéo thả là đốt hạn mức; bản đồ đã
        hiện cảnh báo lộ trình cũ.

        Chuyến của ngày đã qua không lấy nữa: không ai cần đường vẽ của hôm qua, mà số
        thực tế thì đã có vòng đối chiếu GPS lo.
        """
        # Theo TỪNG công ty có bật, không theo self.env.company: cron chạy bằng tài khoản
        # hệ thống nên env.company chỉ là công ty mặc định của tài khoản đó — lấy theo nó
        # thì công ty thứ hai bật tính năng mà mãi không thấy lộ trình nào, không rõ vì sao.
        companies = self.env['res.company'].sudo().search([
            ('vtracking_road_route_enabled', '=', True),
        ])
        if not companies:
            return 0
        plans = self.search([
            ('company_id', 'in', companies.ids),
            ('date', '>=', fields.Date.context_today(self)),
            ('state', 'in', ('draft', 'confirmed')),
            ('road_polyline', '=', False),
            ('road_route_error', '=', False),
        ], order='date, id', limit=CRON_BATCH)
        # Dưới 2 điểm có toạ độ thì không có đoạn nào để đi — bỏ qua trước khi gọi mạng,
        # thay vì để API trả lỗi rồi ghi vào road_route_error (chuyến đang soạn dở, chưa
        # đủ điểm là chuyện bình thường, không phải lỗi cần người xử lý).
        plans = plans.filtered(lambda plan: len(plan._road_route_points()) >= 2)
        if not plans:
            return 0
        _logger.info('V-Tracking: lấy lộ trình đường thật cho %d chuyến.', len(plans))
        return plans._fetch_road_route()
