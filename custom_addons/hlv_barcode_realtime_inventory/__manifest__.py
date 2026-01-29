{
    'name': 'HLV Barcode Realtime Inventory Sync',
    'version': '18.0.1.0.0',
    'summary': 'Real-time sync cho barcode inventory để ngăn data loss và multi-user conflict',
    'depends': ['stock', 'stock_barcode'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'hlv_barcode_realtime_inventory/static/src/js/realtime_sync.js',
        ]
    },
    'installable': True,
    'license': 'LGPL-3',
}
