{
    'name': 'Công cụ Giới hạn Số lượng Dòng Chuyển kho',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Ngăn chặn nhập số lượng vượt quá tồn kho thực tế + Debug tool cho assign issues',
    'description': '''
        Module này chứa 2 tính năng chính:
        
        1. KIỂM SOÁT SỐ LƯỢNG:
        - Ngăn user nhập số lượng giữ tồn vượt quá tồn kho thực tế
        - Real-time validation khi thay đổi quantity
        - Tự động điều chỉnh lại số lượng hợp lệ
        - Ràng buộc database để ngăn dữ liệu không hợp lệ
        
        2. DEBUG TOOL:
        - Phân tích chi tiết tại sao picking assign không được
        - Kiểm tra stock quants tại tất cả locations
        - Phát hiện hàng phân tán ở nhiều vị trí
        - Đề xuất giải pháp (gộp location hoặc nhập thêm hàng)
    ''',
    'author': 'HLV Team',
    'depends': ['stock'],
    'data': [
        'views/stock_picking_debug.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
