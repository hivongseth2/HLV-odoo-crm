{
    "name": "HLV Purchase Qty Decrease",
    "version": "18.0.1.0.0",
    "summary": "Giảm SL dòng đơn mua thì trừ thẳng vào phiếu nhập đang mở, không đẻ phiếu trả NCC",
    "description": """
        Odoo 18 tạo một move âm khi giảm SL dòng đơn mua và chỉ trừ được vào move nhận cũ khi
        khớp khoá gộp (kệ nhận, hạn giao, đơn giá...). Phiếu nhập mà kho đã chọn kệ con / đổi hạn
        thì lệch khoá, move âm bị đảo thành phiếu trả NCC (loại OUT) cho hàng chưa hề nhận.
        Module cho move âm mang khoá của move nhận còn mở để Odoo trừ thẳng vào đó.
    """,
    "category": "Inventory/Purchase",
    "author": "HLV",
    "depends": ["purchase_stock"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
