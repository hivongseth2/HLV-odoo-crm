# models/zalo_warehouse_recipient.py
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class ZaloWarehouseRecipient(models.Model):
    """
    Model để map kho với danh sách user_id nhận thông báo Zalo Stock Notification
    
    Ví dụ:
    - Kho TSN → gửi tới user_id A, B, C
    - Kho TSNSR → gửi tới user_id D, E
    - Kho KBC → gửi tới user_id F, G, H
    """
    _name = 'hlv.zalo.warehouse.recipient'
    _description = 'Zalo Warehouse Recipient Mapping'

    config_id = fields.Many2one(
        'hlv.zalo.stock.notification',
        'Zalo Config',
        required=True,
        ondelete='cascade',
        help='Config Zalo Stock Notification'
    )

    warehouse_id = fields.Many2one(
        'stock.warehouse',
        'Warehouse',
        required=True,
        help='Chọn kho'
    )

    recipient_ids = fields.Text(
        'Recipient User IDs',
        default='',
        help='Danh sách Zalo User ID cần nhận thông báo, mỗi ID một dòng'
    )

    active = fields.Boolean('Active', default=True)

    @api.constrains('warehouse_id')
    def _check_warehouse_unique(self):
        """
        Ensure mỗi warehouse_id chỉ xuất hiện 1 lần trong config
        """
        for rec in self:
            duplicates = self.search([
                ('config_id', '=', rec.config_id.id),
                ('warehouse_id', '=', rec.warehouse_id.id),
                ('id', '!=', rec.id),
            ])
            if duplicates:
                raise models.ValidationError(
                    _('Warehouse "%s" đã tồn tại trong config này') % rec.warehouse_id.name
                )

    def get_recipient_list(self):
        """
        Lấy danh sách recipient IDs từ text field
        
        :return: List of user IDs (strings)
        """
        self.ensure_one()
        if not self.recipient_ids:
            return []
        
        # Split by line breaks và lọc các dòng trống
        ids = [line.strip() for line in self.recipient_ids.split('\n') if line.strip()]
        return ids
