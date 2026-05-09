# -*- coding: utf-8 -*-
"""
Migration 18.0.1.5.0
- Create hlv_loyalty_reward_request table
- Add cash_rate_per_point to hlv_loyalty_program
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        CREATE TABLE IF NOT EXISTS hlv_loyalty_reward_request (
            id              serial PRIMARY KEY,
            name            varchar NOT NULL DEFAULT 'New',
            partner_id      integer NOT NULL,
            request_type    varchar NOT NULL DEFAULT 'gift',
            package_id      integer,
            points_to_redeem integer NOT NULL DEFAULT 0,
            bank_name       varchar,
            account_number  varchar,
            account_name    varchar,
            points_required integer NOT NULL DEFAULT 0,
            cash_value      numeric NOT NULL DEFAULT 0,
            balance_at_request integer NOT NULL DEFAULT 0,
            customer_note   text,
            admin_note      text,
            state           varchar NOT NULL DEFAULT 'pending',
            date_request    timestamp without time zone DEFAULT NOW(),
            date_done       timestamp without time zone,
            done_by_id      integer,
            history_id      integer,
            voucher_id      integer,
            company_id      integer,
            create_date     timestamp without time zone DEFAULT NOW(),
            write_date      timestamp without time zone DEFAULT NOW(),
            create_uid      integer,
            write_uid       integer
        );
    """)
    cr.execute("""
        ALTER TABLE hlv_loyalty_program
        ADD COLUMN IF NOT EXISTS cash_rate_per_point numeric DEFAULT 10000;
    """)
    _logger.info("migration 18.0.1.5.0: created hlv_loyalty_reward_request + cash_rate_per_point")
