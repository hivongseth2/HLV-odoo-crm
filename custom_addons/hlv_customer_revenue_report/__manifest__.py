{
    'name': 'HLV Báo cáo Doanh thu theo Khách hàng',
    'version': '1.0',
    'category': 'Sales/Reporting',
    'summary': 'Báo cáo doanh thu xuất kho theo khách hàng / đơn hàng / công ty, có tính doanh thu xuất ròng sau trả hàng',
    'description': """
        Báo cáo doanh thu dựa trên các phiếu xuất kho (giao hàng) đã hoàn thành, gắn với dòng đơn bán:
        - Nhóm theo Khách hàng (khách hàng thương mại - commercial partner của đơn bán).
        - Nhóm theo Đơn hàng / Công ty (đa công ty).
        - Tính doanh thu xuất kho gộp, tiền hàng trả lại và doanh thu xuất ròng (đã trừ trả hàng),
          dựa theo cơ chế trả hàng chuẩn của Odoo (stock.move.origin_returned_move_id).
        - List, Pivot, Graph đầy đủ sort/filter/group by.
    """,
    'author': 'Antigravity',
    'depends': ['sale', 'sale_stock', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/customer_revenue_report_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
