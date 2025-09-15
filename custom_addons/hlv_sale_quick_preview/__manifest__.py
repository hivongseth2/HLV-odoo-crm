{
  "name": "HLV Sale Quick Preview",
  "version": "18.0.1.0.0",
  "summary": "Quick preview panel for sale orders (JS-only panel, no view override).",
  "category": "Sales",
  "depends": ["web", "sale"],
  "data": [
    "views/server_action.xml"
  ],
  "assets": {
    "web.assets_backend": [
      "hlv_sale_quick_preview/static/src/js/quick_panel.js",
      "hlv_sale_quick_preview/static/src/css/quick_panel.css"
    ]
  },
  "license": "LGPL-3",
  "installable": true,
  "application": false
}