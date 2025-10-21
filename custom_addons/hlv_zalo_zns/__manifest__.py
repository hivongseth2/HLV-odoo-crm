{
    "name": "HLV Zalo ZNS sender",
    "version": "1.0.0",
    "category": "Tools",
    "summary": "Authenticate Zalo OA and send ZNS when pickings complete",
    "depends": ["stock", "base"],
    "data": [
        "security/ir.model.access.csv",
        "views/zns_config_views.xml",
        "data/cron_refresh_token.xml"
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3"
}
