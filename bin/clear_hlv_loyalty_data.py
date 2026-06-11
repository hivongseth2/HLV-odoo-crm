# -*- coding: utf-8 -*-
"""
Clear HLV Loyalty test/runtime data.

Run inside Odoo shell:
    exec(open('bin/clear_hlv_loyalty_data.py', encoding='utf-8').read())

This keeps configuration by default:
    - hlv.loyalty.program
    - hlv.loyalty.tier
    - hlv.loyalty.voucher.package

It removes runtime/test data:
    - point history
    - vouchers
    - reward requests
    - portal accounts
    - loyalty reward lines on sale orders
    - voucher links on sale orders
    - earned point marker on stock pickings
"""

DELETE_PORTAL_ACCOUNTS = True
DELETE_REWARD_REQUESTS = True
DELETE_VOUCHERS = True
DELETE_HISTORIES = True
DELETE_SALE_REWARD_LINES = True
RESET_SALE_VOUCHER_LINKS = True
RESET_PICKING_EARNED_POINTS = True

# Keep these False unless you really want to rebuild config from zero.
DELETE_VOUCHER_PACKAGES = False
DELETE_TIERS = False
DELETE_PROGRAMS = False


def _count(model_name, domain=None):
    return env[model_name].sudo().search_count(domain or [])


def _unlink_all(model_name, domain=None):
    records = env[model_name].sudo().search(domain or [])
    count = len(records)
    if records:
        records.unlink()
    return count


def _write_all(model_name, vals, domain=None):
    records = env[model_name].sudo().search(domain or [])
    count = len(records)
    if records:
        records.write(vals)
    return count


def main():
    print('=== Clear HLV Loyalty runtime data ===')
    print('Before:')
    for model_name in (
        'hlv.loyalty.history',
        'hlv.loyalty.voucher',
        'hlv.loyalty.reward.request',
        'hlv.loyalty.portal.account',
        'hlv.loyalty.voucher.package',
        'hlv.loyalty.tier',
        'hlv.loyalty.program',
    ):
        print('  %-34s %s' % (model_name, _count(model_name)))

    cr = env.cr
    savepoint = getattr(cr, 'savepoint', None)
    context_manager = savepoint() if savepoint else None

    if context_manager:
        context_manager.__enter__()

    try:
        if DELETE_SALE_REWARD_LINES:
            count = _unlink_all('sale.order.line', [('is_loyalty_reward_line', '=', True)])
            print('Deleted sale loyalty reward lines:', count)

        if RESET_SALE_VOUCHER_LINKS:
            count = _write_all(
                'sale.order',
                {'loyalty_voucher_id': False, 'loyalty_voucher_code': False},
                ['|', ('loyalty_voucher_id', '!=', False), ('loyalty_voucher_code', '!=', False)],
            )
            print('Reset sale order voucher links:', count)

        if RESET_PICKING_EARNED_POINTS:
            count = _write_all(
                'stock.picking',
                {'loyalty_points_earned': 0},
                [('loyalty_points_earned', '!=', 0)],
            )
            print('Reset picking loyalty_points_earned:', count)

        # Requests hold links to histories/vouchers, so delete them first.
        if DELETE_REWARD_REQUESTS:
            count = _unlink_all('hlv.loyalty.reward.request')
            print('Deleted reward requests:', count)

        if DELETE_HISTORIES:
            count = _unlink_all('hlv.loyalty.history')
            print('Deleted point histories:', count)

        if DELETE_VOUCHERS:
            count = _unlink_all('hlv.loyalty.voucher')
            print('Deleted vouchers:', count)

        if DELETE_PORTAL_ACCOUNTS:
            count = _unlink_all('hlv.loyalty.portal.account')
            print('Deleted portal accounts:', count)

        if DELETE_VOUCHER_PACKAGES:
            count = _unlink_all('hlv.loyalty.voucher.package')
            print('Deleted voucher packages:', count)

        if DELETE_TIERS:
            count = _unlink_all('hlv.loyalty.tier')
            print('Deleted tiers:', count)

        if DELETE_PROGRAMS:
            count = _unlink_all('hlv.loyalty.program')
            print('Deleted programs:', count)

        if context_manager:
            context_manager.__exit__(None, None, None)
        cr.commit()

    except Exception as exc:
        if context_manager:
            context_manager.__exit__(type(exc), exc, exc.__traceback__)
        cr.rollback()
        raise

    print('After:')
    for model_name in (
        'hlv.loyalty.history',
        'hlv.loyalty.voucher',
        'hlv.loyalty.reward.request',
        'hlv.loyalty.portal.account',
        'hlv.loyalty.voucher.package',
        'hlv.loyalty.tier',
        'hlv.loyalty.program',
    ):
        print('  %-34s %s' % (model_name, _count(model_name)))

    print('Done.')


main()
