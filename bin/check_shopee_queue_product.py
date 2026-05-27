# -*- coding: utf-8 -*-
"""
Run inside Odoo shell:

    exec(open('bin/check_shopee_queue_product.py', encoding='utf-8').read())

Optional before exec if you want to test marking queue manually:

    RUN_MARK = True
    exec(open('bin/check_shopee_queue_product.py', encoding='utf-8').read())

This script diagnoses why Shopee stock sync queue is empty for one product.
It prints product mapping, stock update mode, fixed location quantities,
recent pickings/moves, and stock sync logs.
"""

from odoo import fields

TARGET_NAME = globals().get(
    'TARGET_NAME',
    'Quạt pin công nghiệp M18 ARFHP-0 MILWAUKEE',
)
RUN_MARK = bool(globals().get('RUN_MARK', False))
LIMIT = int(globals().get('LIMIT', 10))


def p(title):
    print('\n' + '=' * 90)
    print(title)
    print('=' * 90)


def line(label, value):
    print('%-32s %s' % (label + ':', value))


def safe_name(rec):
    return rec.display_name if rec else ''


def qty_for_product_location(product, location):
    Location = env['stock.location'].sudo()
    Quant = env['stock.quant'].sudo()
    loc_ids = Location.search([
        ('id', 'child_of', location.id),
        ('usage', '=', 'internal'),
    ]).ids
    quants = Quant.search([
        ('product_id', '=', product.id),
        ('location_id', 'in', loc_ids),
    ])
    quantity = sum(quants.mapped('quantity')) if 'quantity' in Quant._fields else 0
    reserved = sum(quants.mapped('reserved_quantity')) if 'reserved_quantity' in Quant._fields else 0
    available_quant = 0
    if 'available_quantity' in Quant._fields:
        available_quant = sum(quants.mapped('available_quantity'))
    qty_context = product.with_context(location=loc_ids).qty_available
    return loc_ids, quants, quantity, reserved, available_quant, qty_context


p('Shopee queue diagnosis')
line('Target name', TARGET_NAME)
line('RUN_MARK', RUN_MARK)
line('Now', fields.Datetime.now())

SP = env['shopee.product'].sudo()
products = SP.search([
    '|', '|',
    ('item_name', 'ilike', TARGET_NAME),
    ('item_sku', 'ilike', TARGET_NAME),
    ('shopee_item_id', 'ilike', TARGET_NAME),
], limit=LIMIT)

if not products:
    p('NO shopee.product found')
    print('Try overriding TARGET_NAME before exec, for example:')
    print("TARGET_NAME = 'M18 ARFHP-0'; exec(open('bin/check_shopee_queue_product.py', encoding='utf-8').read())")
    raise SystemExit

line('Matched shopee.product count', len(products))

for sp in products:
    p('Shopee product #%s' % sp.id)
    line('Name', sp.item_name)
    line('SKU', sp.item_sku)
    line('Shop', safe_name(sp.shop_id))
    line('Shopee Item ID', sp.shopee_item_id)
    line('Status', sp.item_status)
    line('has_model', sp.has_model)
    line('category_id', sp.category_id)
    line('stock_update_mode', sp.stock_update_mode)
    line('stock_warehouse_id', safe_name(sp.stock_warehouse_id))
    line('stock_location_id', safe_name(sp.stock_location_id))
    line('pending_stock_sync', sp.pending_stock_sync)
    line('pending_sync_since', sp.pending_sync_since)
    line('total_available_stock cached', sp.total_available_stock)

    direct_product = sp.odoo_product_id
    mapped_products = sp.mapped_product_ids
    effective_products = mapped_products or direct_product

    p('Mapping')
    line('odoo_product_id', '%s | %s' % (direct_product.id, safe_name(direct_product)) if direct_product else 'False')
    line('mapped_product_ids', ', '.join('%s | %s' % (x.id, x.display_name) for x in mapped_products) or 'False')
    line('effective products', ', '.join('%s | %s' % (x.id, x.display_name) for x in effective_products) or 'False')

    try:
        mappings = sp.shopee_item_mapping_ids
        line('shopee.item mappings', len(mappings))
        for m in mappings[:10]:
            cols = []
            for fname in ['id', 'shopee_item_identifier', 'product_id', 'shop_id']:
                if fname in m._fields:
                    val = m[fname]
                    if hasattr(val, 'display_name'):
                        val = '%s | %s' % (val.id, val.display_name)
                    cols.append('%s=%s' % (fname, val))
            print('  - ' + '; '.join(cols))
    except Exception as e:
        line('shopee.item mappings ERROR', repr(e))

    p('Stock calculation')
    if not effective_products:
        print('No product.product mapping, queue mark and stock push cannot know which Odoo stock changed.')
    for prod in effective_products:
        line('Product', '%s | %s' % (prod.id, prod.display_name))
        line('default_code', prod.default_code)
        line('qty_available total', prod.qty_available)
        line('virtual_available total', prod.virtual_available)
        if sp.stock_update_mode == 'warehouse' and sp.stock_warehouse_id:
            line('qty_available warehouse', prod.with_context(warehouse=sp.stock_warehouse_id.id).qty_available)
        if sp.stock_update_mode == 'fixed_location' and sp.stock_location_id:
            loc_ids, quants, quantity, reserved, available_quant, qty_context = qty_for_product_location(prod, sp.stock_location_id)
            line('fixed location root', '%s | %s' % (sp.stock_location_id.id, sp.stock_location_id.complete_name))
            line('child internal loc ids', loc_ids)
            line('quant rows', len(quants))
            line('sum quant.quantity', quantity)
            line('sum quant.reserved_quantity', reserved)
            line('sum quant.available_quantity', available_quant)
            line('product.with_context(location=child_ids).qty_available', qty_context)
            for q in quants[:20]:
                available_txt = ''
                if 'available_quantity' in q._fields:
                    available_txt = ' available=%s' % q.available_quantity
                print('  - quant id=%s loc=%s qty=%s reserved=%s%s lot=%s' % (
                    q.id,
                    q.location_id.complete_name,
                    getattr(q, 'quantity', None),
                    getattr(q, 'reserved_quantity', None),
                    available_txt,
                    safe_name(q.lot_id) if 'lot_id' in q._fields else '',
                ))

    p('Recent stock moves / pickings for effective products')
    product_ids = effective_products.ids
    Move = env['stock.move'].sudo()
    if product_ids:
        moves = Move.search([
            ('product_id', 'in', product_ids),
            ('state', '=', 'done'),
        ], order='date desc, id desc', limit=10)
        line('done stock.move count shown', len(moves))
        for m in moves:
            print('  - move=%s date=%s picking=%s picking_state=%s product=%s qty=%s src=%s dest=%s' % (
                m.id,
                m.date,
                safe_name(m.picking_id),
                m.picking_id.state if m.picking_id else '',
                m.product_id.display_name,
                m.product_uom_qty,
                m.location_id.complete_name,
                m.location_dest_id.complete_name,
            ))
    else:
        print('Skipped: no effective product ids')

    p('Stock sync logs')
    Log = env['shopee.stock.sync.log'].sudo()
    logs = Log.search([('shopee_product_id', '=', sp.id)], order='triggered_at desc, id desc', limit=20)
    line('logs shown', len(logs))
    for log in logs:
        print('  - log=%s state=%s trigger=%s synced=%s mode=%s stock_qty=%s error=%s' % (
            log.id,
            log.state,
            log.triggered_at,
            log.synced_at,
            log.stock_update_mode,
            log.stock_qty,
            (log.error_message or '').replace('\n', ' ')[:240],
        ))

    p('Manual mark queue test')
    if not product_ids:
        print('Cannot test _mark_for_stock_sync because product_ids is empty.')
    elif RUN_MARK:
        before_pending = sp.pending_stock_sync
        before_log_count = Log.search_count([('shopee_product_id', '=', sp.id)])
        print('Calling env[\'shopee.product\']._mark_for_stock_sync(%s)' % product_ids)
        env['shopee.product']._mark_for_stock_sync(product_ids)
        env.cr.commit()
        sp.invalidate_recordset()
        after_log_count = Log.search_count([('shopee_product_id', '=', sp.id)])
        latest = Log.search([('shopee_product_id', '=', sp.id)], order='triggered_at desc, id desc', limit=1)
        line('pending before -> after', '%s -> %s' % (before_pending, sp.pending_stock_sync))
        line('log count before -> after', '%s -> %s' % (before_log_count, after_log_count))
        if latest:
            line('latest log', 'id=%s state=%s triggered_at=%s mode=%s' % (
                latest.id, latest.state, latest.triggered_at, latest.stock_update_mode,
            ))
    else:
        print('Skipped. To actually test creating queue, run:')
        print("RUN_MARK = True; exec(open('bin/check_shopee_queue_product.py', encoding='utf-8').read())")

p('Diagnosis hints')
print('1) If effective products is False: mapping missing, _mark_for_stock_sync cannot find this Shopee product from stock moves.')
print('2) If fixed location qty is 0 but you expect stock: check stock_location_id vs actual quant locations printed above.')
print('3) If recent done moves exist but no logs and RUN_MARK creates a log: trigger in stock_picking_ext did not receive those moves/products.')
print('4) If RUN_MARK creates pending log, then queue creation works; empty UI may mean cron processed it or list filter hides state done/skipped/error.')
print('5) If pending remains True but no push: run cron_process_stock_sync_queue manually and inspect latest log error.')
