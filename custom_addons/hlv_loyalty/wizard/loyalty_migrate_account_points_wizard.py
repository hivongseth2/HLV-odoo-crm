# -*- coding: utf-8 -*-
import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)


class HlvLoyaltyMigrateAccountPointsWizard(models.TransientModel):
    _name = 'hlv.loyalty.migrate.account.points.wizard'
    _description = 'Wizard chuyển dữ liệu điểm cũ (cấp công ty) vào tài khoản Loyalty'

    result_log = fields.Text(string='Kết quả', readonly=True)

    def action_run_migration(self):
        """Gán account_id cho các bản ghi lịch sử/voucher/yêu cầu đổi thưởng
        cũ (trước khi có tính năng nhiều tài khoản/công ty) vào "tài khoản
        đầu tiên" của công ty tương ứng.

        Chạy thủ công theo yêu cầu (không tự động khi upgrade module) vì
        đây là thao tác 1 lần trên dữ liệu điểm thật của khách hàng.
        """
        self.ensure_one()
        History = self.env['hlv.loyalty.history'].sudo()
        Voucher = self.env['hlv.loyalty.voucher'].sudo()
        RewardRequest = self.env['hlv.loyalty.reward.request'].sudo()
        Account = self.env['hlv.loyalty.portal.account'].sudo()

        orphan_history = History.search([('account_id', '=', False)])
        root_partner_ids = set(orphan_history.mapped('partner_id').ids)

        processed = []
        skipped = []

        for root_id in root_partner_ids:
            root = self.env['res.partner'].browse(root_id)
            accounts = Account.search([
                ('partner_id', '=', root_id),
                ('active', '=', True),
            ], order='id asc')
            if not accounts:
                skipped.append(root.name or f'#{root_id}')
                continue

            target_account = accounts.filtered('is_default')[:1] or accounts[:1]
            family_ids = [root_id] + root.child_ids.ids

            hist_to_migrate = History.search([
                ('partner_id', 'in', family_ids),
                ('account_id', '=', False),
            ])
            voucher_to_migrate = Voucher.search([
                ('partner_id', 'in', family_ids),
                ('account_id', '=', False),
            ])
            request_to_migrate = RewardRequest.search([
                ('partner_id', 'in', family_ids),
                ('account_id', '=', False),
            ])

            hist_to_migrate.write({'account_id': target_account.id})
            voucher_to_migrate.write({'account_id': target_account.id})
            request_to_migrate.write({'account_id': target_account.id})

            if not accounts.filtered('is_default'):
                target_account.write({'is_default': True})

            processed.append(
                f'- {root.name}: {len(hist_to_migrate)} lịch sử điểm, '
                f'{len(voucher_to_migrate)} voucher, {len(request_to_migrate)} yêu cầu đổi thưởng '
                f'→ tài khoản "{target_account.display_name}".'
            )
            _logger.info(
                'Loyalty migrate: công ty %s -> tài khoản %s (%d history, %d voucher, %d request)',
                root.name, target_account.username,
                len(hist_to_migrate), len(voucher_to_migrate), len(request_to_migrate),
            )

        lines = [f'Đã xử lý {len(processed)} công ty:'] + processed
        if skipped:
            lines.append('')
            lines.append(
                f'Bỏ qua {len(skipped)} công ty chưa có tài khoản Loyalty nào '
                '(cần tạo tài khoản Portal thủ công trước rồi chạy lại):'
            )
            lines.extend(f'- {name}' for name in skipped)
        if not processed and not skipped:
            lines = ['Không có dữ liệu điểm cũ nào cần chuyển (mọi bản ghi đã có tài khoản).']

        self.result_log = '\n'.join(lines)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
