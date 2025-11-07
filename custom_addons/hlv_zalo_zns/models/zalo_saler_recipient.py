# models/zalo_saler_recipient.py
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class ZaloSalerRecipient(models.Model):
    """
    Model để map mã nhân viên sale với danh sách user_id nhận thông báo Zalo Stock Notification
    
    Ví dụ:
    - Mã nhân viên sale A (BACHTHIKIMTHUY) → gửi tới user_id X
    - Mã nhân viên sale B (NGUYENVANA) → gửi tới user_id Y
    - Mã nhân viên sale C (TRANVANB) → gửi tới user_id Z
    
    Model này hoạt động độc lập với zalo_warehouse_recipient:
    - Có thể cấu hình chỉ theo kho (warehouse_recipient_ids)
    - Có thể cấu hình chỉ theo nhân viên sale (saler_recipient_ids)
    - Có thể cấu hình cả hai (sẽ gửi cho cả hai nhóm recipients)
    """
    _name = 'hlv.zalo.saler.recipient'
    _description = 'Zalo Saler Recipient Mapping'

    config_id = fields.Many2one(
        'hlv.zalo.stock.notification',
        'Zalo Config',
        required=True,
        ondelete='cascade',
        help='Config Zalo Stock Notification'
    )

    saler_code = fields.Char(
        'Mã Nhân Viên Sale',
        required=True,
        help='Mã nhân viên sale từ MISA (ví dụ: BACHTHIKIMTHUY)'
    )

    recipient_ids = fields.Text(
        'Recipient User IDs',
        default='',
        help='Danh sách Zalo User ID cần nhận thông báo, mỗi ID một dòng'
    )

    active = fields.Boolean('Active', default=True)

    @api.constrains('saler_code')
    def _check_saler_code_unique(self):
        """
        Ensure mỗi saler_code chỉ xuất hiện 1 lần trong config
        """
        for rec in self:
            if rec.saler_code:
                duplicates = self.search([
                    ('config_id', '=', rec.config_id.id),
                    ('saler_code', '=', rec.saler_code),
                    ('id', '!=', rec.id),
                ])
                if duplicates:
                    raise models.ValidationError(
                        _('Mã nhân viên sale "%s" đã tồn tại trong config này') % rec.saler_code
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
