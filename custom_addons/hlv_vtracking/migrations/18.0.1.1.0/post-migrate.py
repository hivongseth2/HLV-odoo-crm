"""Điền cờ ``variance_measured`` cho các kế hoạch đã chạy trước bản này.

Cron đối chiếu chỉ quét 2 ngày gần nhất, nên không có bước này thì mọi điểm cũ nằm ngoài
báo cáo "Độ chính xác dự báo" và lịch sử bắt đầu từ con số 0. Đọc lại từ nguồn (phiếu +
GPS) chứ không suy từ ``variance_minutes`` cũ: ở đó "không đo được" đã bị ghi thành 0.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.hlv_vtracking.services.vtracking_actual import fill_plan_actuals


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    plans = env['hlv.vtracking.plan'].search([('state', 'in', ('confirmed', 'done'))])
    fill_plan_actuals(plans)
