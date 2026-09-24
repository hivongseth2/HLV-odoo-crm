"""Điền ``delivered_source`` cho các chuyến đã chạy trước bản này.

Không có bước này thì mọi dòng cũ mang nguồn rỗng, phần học lại định mức coi chúng là
"không phải giờ quét" và bỏ hết — cron tối sẽ báo không đủ mẫu dù dữ liệu vẫn còn đó.

Đọc lại từ nguồn (phiếu + nhật ký quét + GPS) chứ không suy từ ô cũ.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.hlv_vtracking.services.vtracking_actual import fill_plan_actuals


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    plans = env['hlv.vtracking.plan'].search([('state', 'in', ('confirmed', 'done'))])
    fill_plan_actuals(plans)
