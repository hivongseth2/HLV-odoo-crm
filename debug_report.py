#!/usr/bin/env python3
"""
Chạy trên Odoo shell:
  odoo-bin shell -d <database> < debug_report.py
  
Hoặc paste từng dòng vào Odoo shell.
"""

# 1. Tìm report theo report_name
report = env['ir.actions.report'].search([('report_name', '=', 'stock.report_picking_copy_1')])
print("=" * 60)
print("1. REPORT INFO")
print(f"   Found: {bool(report)}")
if report:
    print(f"   ID: {report.id}")
    print(f"   name: '{report.name}'")
    print(f"   model: '{report.model}'")
    print(f"   report_name: '{report.report_name}'")
    print(f"   report_type: '{report.report_type}'")
    print(f"   name lower: '{(report.name or '').lower()}'")
    print(f"   Contains 'hoạt động lấy hàng': {'hoạt động lấy hàng' in (report.name or '').lower()}")
    print(f"   Contains 'picking': {'picking' in (report.name or '').lower()}")

# 2. Tìm tất cả report liên quan stock.picking
print("\n" + "=" * 60)
print("2. ALL STOCK.PICKING REPORTS")
all_reports = env['ir.actions.report'].search([('model', '=', 'stock.picking')])
for r in all_reports:
    print(f"   [{r.id}] name='{r.name}' | report_name='{r.report_name}'")

# 3. Check picking 38779
print("\n" + "=" * 60)
print("3. PICKING 38779 INFO")
picking = env['stock.picking'].browse(38779)
if picking.exists():
    print(f"   Name: {picking.name}")
    print(f"   State: {picking.state}")
    print(f"   Sequence code: {picking.picking_type_id.sequence_code}")
    print(f"   x_printed: {picking.x_printed}")
    print(f"   return_id: {picking.return_id}")
    print(f"   sale_id: {picking.sale_id}")
    print(f"   origin: {picking.origin}")
else:
    print("   NOT FOUND")

# 4. Check _get_report method
print("\n" + "=" * 60)
print("4. _get_report METHOD CHECK")
print(f"   hasattr _get_report: {hasattr(env['ir.actions.report'], '_get_report')}")
try:
    r = env['ir.actions.report']._get_report('stock.report_picking_copy_1')
    print(f"   _get_report result: {r}, name='{r.name}'")
except Exception as e:
    print(f"   _get_report ERROR: {type(e).__name__}: {e}")

# 5. Check override is loaded
print("\n" + "=" * 60)
print("5. OVERRIDE CHECK")
mro = type(env['ir.actions.report']).mro()
print(f"   MRO classes with 'IrActionsReport':")
for cls in mro:
    if 'IrActionsReport' in cls.__name__ or 'ir_actions_report' in str(cls):
        print(f"     - {cls.__module__}.{cls.__name__}")

print("\n" + "=" * 60)
print("DONE")
