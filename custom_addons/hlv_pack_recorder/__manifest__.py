# -*- coding: utf-8 -*-
{
    "name": "HLV Pack Recorder",
    "version": "18.0.1.0.0",
    "summary": "Ghi video đóng gói phía server: mỗi camera một file, không nén lại",
    "description": """
Agent chạy tại kho nhận lệnh từ Odoo và dùng ffmpeg -c copy ghi thẳng luồng RTSP
của từng camera thành một file riêng. Không ghép hình, không nén lại, không phụ
thuộc trình duyệt có mở hay không.

Odoo KHÔNG lưu URL/mật khẩu camera — agent tự giữ trong file cấu hình của nó,
Odoo chỉ gửi mã camera. Token agent rò ra ngoài cũng không lộ được camera.
    """,
    "author": "HLV",
    "category": "Warehouse",
    "depends": ["stock", "custom_barcode_scan_redirect"],
    "data": [
        "security/ir.model.access.csv",
        "views/pack_station_views.xml",
        "views/pack_recording_views.xml",
        "views/menu.xml",
        "views/pack_scan_template_inherit.xml",
        "data/pack_recording_cron.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
