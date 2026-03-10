# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID, registry
import os

dbname = 'hoanglongvu-stagin-27232893'
reg = registry(dbname)
with reg.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    o = env['pos.order']
    l = env['pos.order.line']
    
    with open('methods_log.txt', 'w', encoding='utf-8') as f:
        f.write(f"ORDER PREPARE METHODS: {[m for m in dir(o) if '_prepare' in m]}\n")
        f.write(f"LINE PREPARE METHODS: {[m for m in dir(l) if '_prepare' in m]}\n")
        
        # Check specific method signatures
        for m_name in ['_prepare_order_line_move_vals', '_prepare_stock_move_vals', '_get_stock_move_vals']:
            if hasattr(o, m_name):
                f.write(f"Order has {m_name}\n")
            if hasattr(l, m_name):
                f.write(f"Line has {m_name}\n")
print("Done. Check methods_log.txt")
