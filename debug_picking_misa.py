p = env['res.partner'].browse(2308)

commercial = p.commercial_partner_id

po_count = env['purchase.order'].sudo().search_count([
    ('partner_id.commercial_partner_id', '=', commercial.id),
])

vendor_bill_count = env['account.move'].sudo().search_count([
    ('commercial_partner_id', '=', commercial.id),
    ('move_type', 'in', ('in_invoice', 'in_refund', 'in_receipt')),
])

posted_vendor_bill_count = env['account.move'].sudo().search_count([
    ('commercial_partner_id', '=', commercial.id),
    ('move_type', 'in', ('in_invoice', 'in_refund', 'in_receipt')),
    ('state', '=', 'posted'),
])

payable_entry_count = env['account.move.line'].sudo().search_count([
    ('partner_id.commercial_partner_id', '=', commercial.id),
    ('move_id.state', '=', 'posted'),
    ('move_id.move_type', '=', 'entry'),
    ('account_id.account_type', '=', 'liability_payable'),
])

print('ID:', p.id)
print('Tên:', p.name)
print('supplier_rank:', p.supplier_rank)
print('customer_rank:', p.customer_rank)
print('Đơn mua:', po_count)
print('Vendor bill tổng:', vendor_bill_count)
print('Vendor bill đã post:', posted_vendor_bill_count)
print('Bút toán phải trả:', payable_entry_count)