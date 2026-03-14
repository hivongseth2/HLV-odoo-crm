{
    'name': 'HLV Sale Delivery Planning',
    'version': '18.0.1.0.0',
    'summary': 'Điều phối giao hàng: Bán hàng -> Mua hàng',
    'description': 'Dashboard trực quan bằng OWL quản lý kế hoạch giao hàng từ đơn bán và tiến độ hàng từ đơn mua.',
    'category': 'Sales',
    'author': 'HLV',
    'depends': ['sale_management', 'purchase_stock'],
    'data': [
        'views/delivery_planner_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner.scss',
            # Sub-templates (phải đăng ký trước main template)
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_kpi.xml',
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_filters.xml',
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_so_card.xml',
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_drawer.xml',
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_modal.xml',
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_kanban.xml',
            # Main template
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner.xml',
            # JS utils (phải đăng ký trước main component)
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_utils.js',
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner.js',
            # Viewer mode: ẩn navbar khi mở từ /sale_plan
            'hlv_sale_delivery_planning/static/src/hide_navbar_viewer.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
