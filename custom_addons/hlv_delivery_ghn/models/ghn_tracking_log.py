# -*- coding: utf-8 -*-
from odoo import models, fields, api

class GHNTrackingLog(models.Model):
    _name = "ghn.tracking.log"
    _description = "GHN Tracking Log"
    _order = "time_log desc"

    picking_id = fields.Many2one("stock.picking", string="Phiếu xuất kho", ondelete="cascade")
    status_code = fields.Char(string="Mã trạng thái")
    status_name = fields.Char(string="Trạng thái (VN)")
    description = fields.Text(string="Mô tả CHI TIẾT")
    time_log = fields.Datetime(string="Thời gian")
    location = fields.Char(string="Địa điểm")
