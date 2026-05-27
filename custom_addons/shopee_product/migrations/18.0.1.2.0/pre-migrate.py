# -*- coding: utf-8 -*-
"""Migration 18.0.1.2.0: store Shopee model IDs as varchar."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name = 'shopee_product_model'
          AND column_name = 'shopee_model_id'
    """)
    row = cr.fetchone()
    if row and row[0] in ('integer', 'bigint', 'int4', 'int8'):
        _logger.info(
            "shopee_product migration: altering shopee_model_id from %s to varchar(64)",
            row[0],
        )
        cr.execute("""
            ALTER TABLE shopee_product_model
            ALTER COLUMN shopee_model_id TYPE varchar(64)
            USING shopee_model_id::varchar
        """)
