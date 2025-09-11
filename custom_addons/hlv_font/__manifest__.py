# hlv_font/__manifest__.py
{
    "name": "HLV Global PDF Font",
    "summary": "Áp font Times New Roman (hoặc bất kỳ font TTF) cho toàn bộ báo cáo PDF",
    "version": "18.0.1.0.0",
    "author": "HLV",
    "website": "",
    "license": "LGPL-3",
    "category": "Reporting",
    "depends": ["web"],
    "data": [
        "views/report_font.xml",
         "views/assets.xml",
    ],
    "assets": {},
    "installable": True,
    "application": False,
}
