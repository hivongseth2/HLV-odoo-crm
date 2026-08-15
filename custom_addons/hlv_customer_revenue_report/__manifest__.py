{
    'name': 'HLV Báo cáo Doanh thu theo Khách hàng',
    'version': '1.0',
    'category': 'Sales/Reporting',
    'summary': 'Dashboard doanh thu theo khách hàng: đặt hàng / trả hàng / xuất ròng theo tháng, có drawer chi tiết và xuất Excel',
    'description': """
        Dashboard (OWL) tra cứu doanh thu theo khách hàng, dựa trên các phiếu xuất kho (giao hàng)
        đã hoàn thành, gắn với dòng đơn bán:
        - Danh sách khách hàng / shop Shopee, sort theo cột, xem doanh thu từng tháng: tiền đặt hàng
          (gộp), tiền trả hàng, doanh thu xuất ròng.
        - Đơn Shopee được gộp theo shop (shopee_shop_id) thay vì theo contact chung chung, có filter
          Tất cả / Chỉ Shopee / Không phải Shopee.
        - Tính doanh thu xuất ròng dựa theo cơ chế trả hàng chuẩn của Odoo (stock.move.origin_returned_move_id).
        - Click 1 tháng để mở drawer xem chi tiết từng đơn hàng trong tháng đó.
        - Xuất Excel (tổng hợp theo tháng + chi tiết theo đơn hàng).
    """,
    'author': 'Antigravity',
    'depends': ['sale', 'sale_stock', 'stock', 'sale_shopee'],
    'data': [
        'security/ir.model.access.csv',
        'views/customer_revenue_report_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_customer_revenue_report/static/src/scss/customer_revenue_dashboard.scss',
            'hlv_customer_revenue_report/static/src/xml/customer_revenue_dashboard.xml',
            'hlv_customer_revenue_report/static/src/js/customer_revenue_dashboard.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
