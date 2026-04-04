from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        """
        Ghi đè action_done để kích hoạt Rule ngay khi có thay đổi kho.
        Tối ưu Performance: Chỉ chạy nếu sản phẩm có nằm trong Product Feed.
        """
        res = super(StockMove, self)._action_done(cancel_backorder=cancel_backorder)
        
        # Lấy danh sách Product Template IDs từ các moves vừa hoàn thành
        product_tmpl_ids = self.mapped('product_id.product_tmpl_id').ids
        
        if product_tmpl_ids:
            try:
                # Gọi Rule Engine đánh giá ngay (Sử dụng sudo để tránh quyền truy cập kho của user chặn API)
                self.env['google.ads.rule'].sudo()._run_rules_for_products(product_tmpl_ids)
            except Exception as e:
                _logger.error("Reactive Automation Trigger Error: %s", str(e))
                
        return res
