# -*- coding: utf-8 -*-
{
    'name': 'HLV POS Report',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Tích hợp các biên bản từ hlv_a4_report vào POS',
    'description': """
        Module này cho phép in các biên bản PDF (A4/A5) từ module hlv_a4_report
        trong màn hình POS sau khi thanh toán.
        
        Tính năng:
        - Nút "In Biên Bản" trong màn hình Receipt
        - Dialog chọn mẫu biên bản để in
        - Hỗ trợ tất cả các mẫu từ hlv_a4_report (BBBG, BBGN, PX, PXBH...)
    """,
    'author': 'HLV',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'point_of_sale',
        'hlv_a4_report',
        'stock',
    ],
    'data': [],
    'assets': {
        'point_of_sale._assets_pos': [
            'hlv_pos_report/static/src/css/pos_report.css',
            'hlv_pos_report/static/src/js/models.js',
            'hlv_pos_report/static/src/js/print_report_popup.js',
            'hlv_pos_report/static/src/js/receipt_screen_extend.js',
            'hlv_pos_report/static/src/xml/print_report_popup.xml',
            'hlv_pos_report/static/src/xml/receipt_screen_extend.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
