# -*- coding: utf-8 -*-
{
    "name": "HLV Chatter Collapse",
    "version": "18.0.1.0.2",
    "category": "Productivity",
    "summary": "Collapse and expand the form chatter sidebar",
    "author": "HLV",
    "license": "LGPL-3",
    "depends": ["web", "mail"],
    "assets": {
        "web.assets_backend": [
            "hlv_chatter_collapse/static/src/js/chatter_collapse.js",
            "hlv_chatter_collapse/static/src/xml/chatter_collapse.xml",
            "hlv_chatter_collapse/static/src/scss/chatter_collapse.scss",
        ],
    },
    "installable": True,
    "application": False,
}
