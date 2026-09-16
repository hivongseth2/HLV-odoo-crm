# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HlvChatgptAdmin(models.Model):
    _name = 'hlv.chatgpt.admin'
    _description = 'Quản trị viên Chat AI (whitelist Zalo)'
    _order = 'name'

    name = fields.Char(string='Họ tên', required=True)
    zalo_user_id = fields.Char(
        string='Zalo User ID',
        required=True,
        index=True,
        help="Lấy bằng cách nhắn 'id' vào Zalo OA.",
    )
    active = fields.Boolean(default=True)
    note = fields.Char(string='Ghi chú')

    _sql_constraints = [
        ('zalo_user_id_uniq', 'unique(zalo_user_id)',
         'Zalo User ID này đã có trong danh sách quản trị viên.'),
    ]

    @api.model
    def is_admin_zalo_user(self, zalo_user_id):
        """Zalo user id này có quyền quản trị không.

        Đây là căn cứ DUY NHẤT để cấp quyền quản trị cho người chat qua Zalo. Lời tự
        xưng trong tin nhắn ("tôi là ...") không có giá trị, vì ai cũng gõ được.
        """
        if not zalo_user_id:
            return False
        return bool(self.sudo().search_count([('zalo_user_id', '=', zalo_user_id)]))
