"""API cho AI — dữ liệu nền còn lại: cụm tuyến (định mức), xe, tài xế.

Controller chỉ đọc tham số rồi gọi service; luật nằm ở ``services/ai/master_service``.
"""

from odoo import http

from ...services.ai import master_service
from ..api_common import ROUTE_DEFAULTS, api_endpoint

READ = dict(methods=['GET', 'OPTIONS'], **ROUTE_DEFAULTS)
WRITE = dict(methods=['POST', 'OPTIONS'], **ROUTE_DEFAULTS)


class AiMasterController(http.Controller):

    @http.route('/api/v1/ai/zones/<int:zone_id>', **WRITE)
    @api_endpoint(write=True)
    def update_zone(self, ctx, zone_id, **_params):
        """Sửa định mức / trần điểm của cụm. Trả cả giá trị cũ lẫn mới."""
        zone = ctx.browse_or_404('hlv.vtracking.zone', zone_id, 'cụm tuyến')
        return master_service.update_zone(zone, ctx.json_body())

    @http.route('/api/v1/ai/zones/<int:zone_id>/apply-calibration', **WRITE)
    @api_endpoint(write=True)
    def apply_calibration(self, ctx, zone_id, **_params):
        """Ghi đề xuất học từ thực tế vào định mức của cụm."""
        zone = ctx.browse_or_404('hlv.vtracking.zone', zone_id, 'cụm tuyến')
        return master_service.apply_zone_calibration(zone)

    @http.route('/api/v1/ai/zones/recalibrate', **WRITE)
    @api_endpoint(write=True)
    def recalibrate(self, ctx, **_params):
        """Tính lại đề xuất định mức ngay, không chờ cron 20:00."""
        return master_service.recalibrate(ctx.env, ctx.company)

    @http.route('/api/v1/ai/vehicles/<int:vehicle_id>', **WRITE)
    @api_endpoint(write=True)
    def update_vehicle(self, ctx, vehicle_id, **_params):
        """Sửa chuyên chở + tài xế + điểm xuất phát mặc định của xe."""
        vehicle = ctx.browse_or_404('fleet.vehicle', vehicle_id, 'xe')
        return master_service.update_vehicle(vehicle, ctx.json_body())

    @http.route('/api/v1/ai/drivers', **READ)
    @api_endpoint()
    def drivers(self, ctx, **_params):
        """Tài khoản có tên shipper — người chọn được làm tài xế, kèm xe đang gắn."""
        return master_service.list_drivers(ctx.env, ctx.company)
