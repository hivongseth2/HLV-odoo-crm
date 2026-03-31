from odoo import models, fields

class GoogleAdsAdType(models.Model):
    _name = 'google.ads.ad.type'
    _description = 'Loại Quảng Cáo Google Ads'
    _order = 'sequence, id'

    name = fields.Char(string='Tên Loại', required=True, translate=True)
    code = fields.Char(string='Mã Kỹ Thuật', required=True)
    sequence = fields.Integer(default=10)
    
    # Comma-separated list of compatible ad group types
    # e.g., 'SEARCH_STANDARD,SEARCH_DYNAMIC_ADS'
    compatible_ad_group_types = fields.Char(
        string='Mã Nhóm Tương Thích',
        help='Danh sách mã loại nhóm quảng cáo hỗ trợ (cách nhau bởi dấu phẩy).'
    )
