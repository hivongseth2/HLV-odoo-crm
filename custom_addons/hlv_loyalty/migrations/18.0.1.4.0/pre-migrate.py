# -*- coding: utf-8 -*-
"""
Migration 18.0.1.4.0
- Add portal_ranking_desc column to hlv_loyalty_program
- Add portal_exchange_desc column to hlv_loyalty_program
"""
import logging

_logger = logging.getLogger(__name__)

_DEFAULT_RANKING = (
    'Điểm tích lũy dùng để xếp hạng thành viên, không dùng để đổi thưởng. '
    'Mỗi 100.000đ mua hàng = 1 điểm.'
)
_DEFAULT_EXCHANGE = (
    'Điểm đổi thưởng có thể dùng để đổi Voucher hoặc tiền chiết khấu. '
    'Mỗi 10.000đ chiết khấu = 1 điểm.'
)


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE hlv_loyalty_program
        ADD COLUMN IF NOT EXISTS portal_ranking_desc text;
    """)
    cr.execute("""
        ALTER TABLE hlv_loyalty_program
        ADD COLUMN IF NOT EXISTS portal_exchange_desc text;
    """)
    # Pre-fill existing rows with default text
    cr.execute(
        "UPDATE hlv_loyalty_program SET portal_ranking_desc = %s WHERE portal_ranking_desc IS NULL",
        (_DEFAULT_RANKING,),
    )
    cr.execute(
        "UPDATE hlv_loyalty_program SET portal_exchange_desc = %s WHERE portal_exchange_desc IS NULL",
        (_DEFAULT_EXCHANGE,),
    )
    _logger.info("migration 18.0.1.4.0: added portal description fields to hlv_loyalty_program")
