# -*- coding: utf-8 -*-
from odoo import models, fields


class MeinvoiceLog(models.Model):
    _name = 'meinvoice.log'
    _description = 'MEinvoice API Log'
    _order = 'create_date desc'
    _rec_name = 'move_id'

    move_id = fields.Many2one(
        'account.move',
        string='Hóa đơn Odoo',
        ondelete='set null',
        index=True,
    )
    action = fields.Selection([
        ('publish',  'Phát hành'),
        ('cancel',   'Hủy'),
        ('adjust',   'Điều chỉnh'),
        ('search',   'Tra cứu'),
        ('download', 'Tải file'),
    ], string='Hành động', required=True)
    state = fields.Selection([
        ('success', 'Thành công'),
        ('error',   'Lỗi'),
    ], string='Kết quả', required=True)
    transaction_id = fields.Char('Transaction ID (MEinvoice)')
    message = fields.Text('Thông tin / Lỗi')
    request_data = fields.Text('Dữ liệu gửi đi')
    response_data = fields.Text('Dữ liệu nhận về')
    create_date = fields.Datetime('Thời gian', readonly=True)
    create_uid = fields.Many2one('res.users', 'Người thực hiện', readonly=True)
