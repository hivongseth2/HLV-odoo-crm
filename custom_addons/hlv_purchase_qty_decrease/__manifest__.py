{
    "name": "HLV Purchase Qty Decrease",
    "version": "18.0.1.0.0",
    "summary": "Giảm SL dòng đơn mua thì trừ thẳng vào phiếu nhập đang mở, không đẻ phiếu trả NCC",
    "description": """
        Odoo 18 tạo một move âm khi giảm SL dòng đơn mua và nhờ bước gộp move trừ vào move nhận.
        Bước gộp gỡ phiếu khỏi move âm trước khi so khoá nên kệ nhận bị tính lại về kệ mặc định:
        phiếu nhập mà kho đã chọn kệ khác thì không khớp, move âm bị đảo thành phiếu trả NCC
        (loại OUT) cho hàng chưa hề nhận. Module trừ thẳng phần giảm vào move nhận còn mở.
    """,
    "category": "Inventory/Purchase",
    "author": "HLV",
    "depends": ["purchase_stock"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
