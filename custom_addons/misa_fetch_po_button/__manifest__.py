{
    'name': 'MISA PO Fetch Button',
    'version': '1.0',
    'depends': ['base', 'stock', 'purchase', 'sale', 'sales_team', 'point_of_sale', 'pos_category_import_json', 'purchase_request'],
    'author': 'Luan',
    'category': 'Purchases',
    'description': 'Fetch PO from MISA and create in Odoo',
    'data': [
        'security/ir.model.access.csv',
        'views/misa_transfer_button_view.xml',
        'views/misa_po_button_view.xml',
        'views/misa_po_sync_view.xml',
        'views/misa_combined_button_view.xml',
        'views/misa_return_button_view.xml',
        'views/sale_order_misa_sync.xml',
        'views/product_view.xml',
        'views/crm_tag_views.xml',
        'views/purchase_request_misa_view.xml',
        'wizard/misa_pos_sync_wizard_views.xml',
        'wizard/misa_tax_update_wizard_views.xml',
        'wizard/misa_tag_update_wizard_views.xml',
        'wizard/misa_purchase_request_sync_views.xml',
        'wizard/misa_shipping_address_batch_update_views.xml',
        'views/misa_invoice_search_view.xml',
    ],

    'python': [
        'models/sale_api_import_wizard.py',  # Thêm file này
    ],
    'installable': True,
    'auto_install': False,
}
