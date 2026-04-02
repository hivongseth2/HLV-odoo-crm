from odoo import models, fields

class GoogleAdsAdGroupType(models.Model):
    _name = 'google.ads.ad.group.type'
    _description = 'Loại Nhóm Quảng Cáo Google Ads'
    _order = 'sequence, id'

    name = fields.Char(string='Tên Loại', required=True, translate=True)
    code = fields.Char(string='Mã Kỹ Thuật', required=True)
    sequence = fields.Integer(default=10)
    
    # Comma-separated list of compatible campaign channel types
    # e.g., 'SEARCH,SMART'
    compatible_channel_types = fields.Char(
        string='Mênh Tương Thích',
        help='Danh sách mã loại kênh chiến dịch hỗ trợ (cách nhau bởi dấu phẩy).'
    )
