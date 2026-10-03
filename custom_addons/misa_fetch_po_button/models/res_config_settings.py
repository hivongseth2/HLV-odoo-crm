# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Mặc định tắt: bật lên là mọi lần sửa tên / mã sản phẩm trên Odoo đều ghi lên MISA.
    misa_crm_auto_sync_product = fields.Boolean(
        string="Tự cập nhật sản phẩm lên MISA CRM khi lưu",
        config_parameter='misa.crm.auto_sync_product',
        help="Sửa TÊN hoặc MÃ sản phẩm trên Odoo rồi bấm Lưu thì hàng tương ứng trên MISA CRM "
             "được cập nhật theo. Kết quả ghi ở chatter của sản phẩm. Chỉ áp dụng khi người "
             "dùng sửa; các luồng đồng bộ tự động từ MISA về không bị đẩy ngược lên.",
    )
