# Script: fix_meinvoice_accepted_state.py
# Mục đích: Cập nhật state cho các hóa đơn đã có InvCode (mã CQT) nhưng vẫn ở submitted
# Chạy: python odoo-bin shell -d <DATABASE> < bin/fix_meinvoice_accepted_state.py

invoices = env['meinvoice.invoice'].sudo().search([
    ('state', '=', 'submitted'),
    ('inv_code', '!=', False),
    ('inv_code', '!=', ''),
])

print(f"Tìm thấy {len(invoices)} hóa đơn submitted nhưng đã có InvCode:")
for inv in invoices:
    print(f"  id={inv.id} | inv_no={inv.inv_no!r} | inv_code={inv.inv_code!r} | transaction_id={inv.transaction_id!r}")

if invoices:
    confirm = input("\nCập nhật tất cả lên state='accepted'? (y/n): ")
    if confirm.strip().lower() == 'y':
        from datetime import datetime as _dt
        invoices.sudo().write({
            'state': 'accepted',
            'cqt_check_queued': False,
            'cqt_checked_at': _dt.utcnow(),
        })
        # Update SO cũng backward compat
        for inv in invoices:
            if inv.sale_order_id:
                inv.sale_order_id.sudo().write({'misa_meinvoice_synced': True})
        env.cr.commit()
        print(f"✓ Đã cập nhật {len(invoices)} hóa đơn → accepted.")
    else:
        print("Huỷ.")
else:
    print("Không có hóa đơn nào cần cập nhật.")

print("\nDone.")
