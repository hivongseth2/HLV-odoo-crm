{
  "name": "HLV Viettel Post Integration",
  "summary": "Viettel Post (VTP) API integration: calculate fee, create/cancel orders, webhook updates",
  "version": "18.0.2.0.0",
  "category": "Inventory/Delivery",
  "author": "HLV + ChatGPT",
  "website": "https://example.com",
  "license": "LGPL-3",
  "depends": ["base", "stock", "delivery", "sale_management"],
  "data": [
    "security/ir.model.access.csv",
    "data/ir_config_parameter.xml",
    "views/res_config_settings_view.xml",
    "views/delivery_carrier_view.xml",
    "views/vtp_geo_views.xml",
    "views/vtp_sync_wizard.xml",
    "views/stock_picking_vtp_button.xml"
  ],
  "assets": {},
  "application": False,
  "installable": True
}
