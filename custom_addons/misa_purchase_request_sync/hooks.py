# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def fix_pr_line_sequence(cr, registry):
    """Post-init hook: đánh lại STT cho tất cả PR lines cũ khi cài/upgrade module.

    Chạy tự động ngay sau khi module được cài đặt hoặc nâng cấp.
    Với mỗi YCMH, gán sequence = 1, 2, 3... cho các dòng theo thứ tự id tăng dần.
    """
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
        "post_init_hook fix_pr_line_sequence: Đã fix %d dòng thuộc %d YCMH.",
        affected_lines,
        affected_prs,
    )