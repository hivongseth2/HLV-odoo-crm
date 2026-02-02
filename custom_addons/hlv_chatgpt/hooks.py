# -*- coding: utf-8 -*-
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def post_init_hook(cr, registry):
    """Enable ChatGPT auto-reply for HLV livechat channels after install/upgrade.

    We keep it conservative: only channels whose name contains 'HLV' are enabled.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        channels = env['im_livechat.channel'].search([('name', 'ilike', 'HLV')])
        if channels:
            channels.write({'hlv_ai_enabled': True})
            _logger.info('HLV ChatGPT: enabled hlv_ai_enabled=True for %s livechat channel(s)', len(channels))
        else:
            _logger.info('HLV ChatGPT: no livechat channels matched for auto-enable')
    except Exception:
        _logger.exception('HLV ChatGPT: post_init_hook failed')
