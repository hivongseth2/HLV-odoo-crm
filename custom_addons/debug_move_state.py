
# Script to check the state of the problematic move
product_ref = '1600A00163'
moves = env['stock.move'].search([
    ('product_id.default_code', '=', product_ref),
    ('state', 'not in', ('done', 'cancel'))
])

print(f"Found {len(moves)} moves for {product_ref}")
for m in moves:
    print(f"Move ID: {m.id}, State: '{m.state}', Picking: {m.picking_id.name}, Origin: {m.origin}")
