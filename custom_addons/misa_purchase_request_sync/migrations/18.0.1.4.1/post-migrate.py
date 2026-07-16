# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Post-migration script: Đánh lại STT cho toàn bộ PR lines cũ khi nâng cấp module."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    pr_model = env["purchase.request"]
    affected_prs = 0
    affected_lines = 0

    for pr in pr_model.search([]):
        lines = pr.line_ids.sorted(key=lambda l: l.id)
        need_update = False
        for idx, line in enumerate(lines, 1):
            if line.sequence != idx:
                line.write({"sequence": idx})
                affected_lines += 1
                need_update = True
        if need_update:
            affected_prs += 1

    _logger.info(
        "post-migrate fix_pr_line_sequence: Đã đánh lại STT cho %d dòng thuộc %d YCMH.",
        affected_lines,
        affected_prs,
    )
