import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WarehouseMonitorConfig(models.Model):
    _name = "warehouse.monitor.config"
    _description = "Warehouse Monitor Configuration"
    _rec_name = "warehouse_id"

    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Kho",
        required=True,
        ondelete="cascade",
    )
    active = fields.Boolean(
        string="Kích hoạt giám sát",
        default=True,
    )
    auto_suggest_pick = fields.Boolean(
        string="Tự động đề xuất PICK khi nhập hàng",
        default=True,
        help="Khi đơn mua hàng được nhập kho, tự động đề xuất lấy hàng cho đơn bán liên quan",
    )
    auto_suggest_pack = fields.Boolean(
        string="Tự động đề xuất PACK sau PICK",
        default=True,
        help="Khi PICK hoàn thành, tự động đề xuất đóng gói",
    )
    auto_suggest_out = fields.Boolean(
        string="Tự động đề xuất xuất kho sau PACK",
        default=True,
        help="Khi PACK hoàn thành, tự động đề xuất xuất kho",
    )
    track_sales = fields.Boolean(
        string="Theo dõi đơn bán hàng",
        default=True,
    )
    track_purchases = fields.Boolean(
        string="Theo dõi đơn mua hàng",
        default=True,
    )
    track_pickings = fields.Boolean(
        string="Theo dõi phiếu kho",
        default=True,
    )

    _sql_constraints = [
        (
            "warehouse_unique",
            "unique(warehouse_id)",
            "Mỗi kho chỉ được cấu hình giám sát một lần!",
        ),
    ]

    @api.model
    def get_config_for_warehouse(self, warehouse_id):
        """Get or create monitor config for a warehouse."""
        config = self.search([("warehouse_id", "=", warehouse_id)], limit=1)
        if not config:
            config = self.create({"warehouse_id": warehouse_id})
        return config

    @api.model
    def is_monitoring_active(self, warehouse_id):
        """Check if monitoring is active for a warehouse."""
        config = self.search([("warehouse_id", "=", warehouse_id), ("active", "=", True)], limit=1)
        return bool(config)
