{
    'name': 'Công cụ Giới hạn Số lượng Dòng Chuyển kho',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Ngăn chặn nhập số lượng vượt quá tồn kho thực tế',
    'description': '''
        Module này ngăn chặn người dùng nhập số lượng giữ tồn (quantity) vượt quá 
        tồn kho thực tế (on-hand) tại một vị trí.
        
        Tính năng:
        - Kiểm tra real-time khi thay đổi số lượng
        - Ràng buộc database để ngăn dữ liệu không hợp lệ
        - Cảnh báo popup khi cố nhập vượt quá tồn kho
        - Tự động điều chỉnh lại số lượng hợp lệ
    ''',
    'author': 'HLV Team',
    'depends': ['stock'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
