{
    'name': 'HLV Sale Delivery Planning',
    'version': '18.0.1.0.0',
    'summary': 'Điều phối giao hàng: Bán hàng -> Mua hàng',
    'description': 'Dashboard trực quan bằng OWL quản lý kế hoạch giao hàng từ đơn bán và tiến độ hàng từ đơn mua.',
    'category': 'Sales',
    'author': 'HLV',
    'depends': ['sale_management', 'purchase_stock', 'bus'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/res_users_views.xml',
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
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_table.xml',
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_transfer_modal.xml',
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_relocation_modal.xml',
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_packer_modal.xml',
            'hlv_sale_delivery_planning/static/src/components/packing_kpi/packing_kpi.xml',
            # Main template
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner.xml',
            # JS utils (phải đăng ký trước main component)
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner_utils.js',
            'hlv_sale_delivery_planning/static/src/report/picking_packer_assignment_handler.js',
            'hlv_sale_delivery_planning/static/src/components/delivery_planner/delivery_planner.js',
            'hlv_sale_delivery_planning/static/src/components/packing_kpi/packing_kpi.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
