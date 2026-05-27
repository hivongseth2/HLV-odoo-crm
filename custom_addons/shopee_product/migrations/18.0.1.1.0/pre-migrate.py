# -*- coding: utf-8 -*-
"""
Migration 18.0.1.1.0: shopee_item_id Integer → Char (varchar 64)

Shopee item ID thực tế vượt quá PostgreSQL integer (max ~2.1 tỷ).
Ví dụ: 108001563706 (12 chữ số) → NumericValueOutOfRange.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name = 'shopee_product'
          AND column_name = 'shopee_item_id'
    """)
    row = cr.fetchone()
    if row and row[0] in ('integer', 'bigint', 'int4', 'int8'):
        _logger.info(
            "shopee_product migration: altering shopee_item_id from %s to varchar(64)", row[0]
        )
        cr.execute("""
            ALTER TABLE shopee_product
            ALTER COLUMN shopee_item_id TYPE varchar(64)
            USING shopee_item_id::varchar
        """)
    else:
        _logger.info(
            "shopee_product migration: shopee_item_id column type = %s, no alter needed",
            row[0] if row else 'not found',
        )
