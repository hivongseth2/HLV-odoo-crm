# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorChatRead(models.Model):
    """Mốc "đã xem tới tin nào" của một người xem trên một cuộc trao đổi (báo giá / đơn mua).

    Người xem là user nội bộ (trang sale) HOẶC link của NCC — mỗi bên một mốc riêng, để
    thu mua mở xem không làm mất "tin mới" của sale phụ trách. Có mốc nghĩa là đã mở
    chứng từ ít nhất một lần (thông báo "yêu cầu báo giá mới / đơn mua mới" của NCC dựa vào
    đó). Chỉ đọc / ghi bằng sudo qua services/chat_read.py.
    """

    _name = "hlv.vendor.chat.read"
    _description = "Đã xem trao đổi với NCC"
    _log_access = False

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    user_id = fields.Many2one("res.users", ondelete="cascade", index=True)
    access_id = fields.Many2one("hlv.vendor.quote.access", ondelete="cascade", index=True)
    last_message_id = fields.Integer(default=0)

    _sql_constraints = [
        (
            "one_reader",
            "CHECK ((user_id IS NULL) <> (access_id IS NULL))",
            "Mốc đã xem phải thuộc đúng một người xem (user hoặc link NCC).",
        ),
    ]

    def init(self):
        self.env.cr.execute(
            f"CREATE INDEX IF NOT EXISTS {self._table}_record_idx ON {self._table} (res_model, res_id)"
        )
