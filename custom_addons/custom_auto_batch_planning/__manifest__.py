# -*- coding: utf-8 -*-
{
    'name': "Auto Batch Planning: Pick to Out",
    'summary': """
        Tự động lập kế hoạch giao hàng (Batch Out) dựa trên kế hoạch lấy hàng (Batch Pick).
        Hỗ trợ quy trình: Gán xe cho Pick -> Tự động gán xe cho Out.
    """,
    'description': """
        Module này giúp tự động hóa quy trình đội xe và kho vận:
        1. Khi người điều phối tạo Batch cho phiếu Lấy hàng (Pick) và gán xe.
        2. Hệ thống tự động tìm phiếu Giao hàng (Out) tương ứng.
        3. Tự động tạo hoặc tìm Batch Giao hàng cho chiếc xe đó và gán phiếu Out vào.
        
        Giúp lên kế hoạch giao hàng sớm ngay từ khâu soạn hàng mà không cần chờ hàng ra tới cửa kho.
    """,
    'author': "My Company",
    'website': "https://www.yourcompany.com",
    'category': 'Inventory/Logistics',
    'version': '18.0.1.0.0',  # Hoặc 17.0 tuỳ phiên bản Odoo bạn dùng
    
    # Quan trọng: Phải có các module này thì code mới chạy được
    'depends': [
        'base',
        'stock', 
        'stock_picking_batch', # Để dùng model stock.picking.batch
        'fleet',               # Để dùng thông tin xe (vehicle_id)
    ],

    # Code của bạn chỉ xử lý logic ngầm (Backend) nên không nhất thiết phải có file XML/View
    'data': [
        'security/ir.model.access.csv', 
        'views/batch_planning_views.xml',
        'views/batch_planning_wizard_views.xml',
        'views/stock_picking_views.xml',
    ],
    
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}