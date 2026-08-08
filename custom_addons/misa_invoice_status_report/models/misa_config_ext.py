from odoo import models


class MisaConfigInvoiceStatus(models.AbstractModel):
    _inherit = 'misa.config'

    def get_invoice_request_bulk_payload(self, date_from_iso, date_to_iso, page_index=1, page_size=100):
        """Như get_invoice_request_payload() nhưng KHÔNG customFilter theo 1 refno cụ thể —
        tải hàng loạt "Đề nghị xuất hóa đơn" trong khoảng ngày để dựng map tra cứu 1 lần
        cho nhiều phiếu (xem misa.api.utils.get_invoice_request_map)."""
        return {
            "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},"
                    "{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "filter": [
                {"property": 3972, "value": date_from_iso, "operator": 10, "operand": 1, "data_type": 3},
                {"property": 3972, "value": date_to_iso, "operator": 12, "operand": 1, "data_type": 3},
            ],
            "customFilter": [],
            "pageIndex": page_index,
            "pageSize": page_size,
            "useSp": False,
            "view": 65,
            "summaryColumns": [5127, 5069, 5142, 5047],
        }
