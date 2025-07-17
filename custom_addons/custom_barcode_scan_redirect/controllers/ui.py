# from odoo import http
# from odoo.http import request


# class CustomBarcodeScanUIController(http.Controller):

#     @http.route('/custom_barcode_scan/ui', type='http', auth='user', website=True)
#     def scan_ui_page(self, **kwargs):
#         return request.render('custom_barcode_scan_redirect.scan_ui_template', {})

#     @http.route('/custom_barcode_scan/ui/scan', type='json', auth='user')
#     def scan_ui_api(self, barcode):
#         StockPicking = request.env['stock.picking']
#         picking = StockPicking.search([('name', '=', barcode)], limit=1)

#         if picking and picking.state == 'done' and picking.group_id:
#             next_picking = StockPicking.search([
#                 ('group_id', '=', picking.group_id.id),
#                 ('state', 'not in', ['done', 'cancel']),
#                 ('id', '!=', picking.id)
#             ], order='scheduled_date asc', limit=1)
#             if next_picking:
#                 return next_picking.get_barcode_view_state(next_picking.name)
#             return {"type": "ir.actions.client", "tag": "display_notification", "params": {"title": "Thông báo", "message": "Đã hoàn tất mọi phiếu.", "sticky": False}}

#         if picking:
#             return picking.get_barcode_view_state(picking.name)

#         return {"type": "ir.actions.client", "tag": "display_notification", "params": {"title": "Không tìm thấy", "message": f"Không có phiếu với mã  {barcode}", "sticky": False}}