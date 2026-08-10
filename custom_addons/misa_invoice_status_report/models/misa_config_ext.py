from odoo import models


class MisaConfigInvoiceStatus(models.AbstractModel):
    _inherit = 'misa.config'

    def get_invoice_request_bulk_payload(self, date_from_iso, date_to_iso, page_index=1, page_size=100):
        """Như get_invoice_request_payload() nhưng KHÔNG customFilter theo 1 refno cụ thể —
        tải hàng loạt "Đề nghị xuất hóa đơn" trong khoảng ngày để dựng map tra cứu 1 lần
        cho nhiều phiếu (xem misa.api.utils.get_invoice_request_map).

        ⚠️ Payload thật của MISA khi liệt kê KHÔNG lọc gì (chụp từ trang InvoiceRequest lúc
        không gõ tìm kiếm) hoàn toàn KHÔNG có key "customFilter" — gửi key này dù để mảng
        rỗng ([]) cũng khiến MISA trả lỗi server chung chung (Code 99). Vì vậy tuyệt đối
        không thêm lại "customFilter" ở đây, kể cả rỗng."""
        return {
            "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},"
                    "{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "filter": [
                {"property": 3972, "value": date_from_iso, "operator": 10, "operand": 1, "data_type": 3},
                {"property": 3972, "value": date_to_iso, "operator": 12, "operand": 1, "data_type": 3},
            ],
            "pageIndex": page_index,
            "pageSize": page_size,
            "useSp": False,
            "view": 65,
            "summaryColumns": [5127, 5069, 5142, 5047],
        }

    def get_invoice_request_detail_payload(self, request_refid, page_index=1, page_size=100):
        """Payload lấy CHI TIẾT TỪNG DÒNG HÀNG của 1 "Đề nghị xuất hóa đơn" (theo refid, chính
        là misa_invoice_request_refid đã lưu sẵn trên phiếu) — dùng để đối chiếu từng dòng sản
        phẩm với Odoo. Copy nguyên payload thật (chụp từ DevTools khi xem chi tiết 1 hóa đơn
        trên MISA), chỉ thay value của filter property 3993 = request_refid, KHÔNG đổi field
        nào khác (property/operator/data_type/columns đều là mã nội bộ MISA, không tự suy ra
        được nếu đoán sai)."""
        return {
            "columns": [2157, 1355, 5274, 3870, 5279, 308, 1455, 5350, 3295, 1000, 5936, 3487, 3490, 3486, 3489, 3488, 5476, 5575],
            "sort": "[{\"property\":4555,\"desc\":false,\"data_type\":4,\"operand\":1}]",
            "filter": [
                {"property": 3993, "operator": 7, "operand": 1, "value": request_refid, "data_type": 10},
            ],
            "pageIndex": page_index,
            "pageSize": page_size,
            "useSp": False,
            "view": 66,
            "summaryColumns": [3870, 308, 1455, 5350],
        }
