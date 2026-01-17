# -*- coding: utf-8 -*-
from odoo import models, fields

class JTTrackingLog(models.Model):
    _name = "jt.tracking.log"
    _description = "J&T Tracking Log"
    _order = "scan_time desc"

    picking_id = fields.Many2one("stock.picking", string="Phiếu xuất kho", ondelete="cascade")
    scan_time = fields.Datetime(string="Thời gian")
    scan_type_name = fields.Char(string="Loại thao tác")
    desc = fields.Text(string="Mô tả chi tiết")
    scan_network_name = fields.Char(string="Bưu cục/Trạm")
    staff_name = fields.Char(string="Nhân viên")
    staff_contact = fields.Char(string="Liên hệ NV")
