from odoo import SUPERUSER_ID, api, models, _
from odoo.exceptions import AccessError


class IrActionsActions(models.Model):
    _inherit = 'ir.actions.actions'

    @api.model
    def _hlv_default_barcode_action_ids(self):
        actions = self.env['ir.actions.client'].sudo()
        action = self.env.ref(
            'stock_barcode.stock_barcode_action_main_menu',
            raise_if_not_found=False,
        )
        if action:
            actions |= action

        actions |= self.env['ir.actions.client'].sudo().search([
            ('tag', 'in', ['stock_barcode_main_menu', 'stock_barcode.MainMenu']),
        ])
        return set(actions.ids)

    @api.model
    def _hlv_user_has_default_barcode_access(self):
        if self.env.uid == SUPERUSER_ID:
            return True

        group = self.env.ref(
            'hlv_mobile_barcode.group_stock_barcode_default_user',
            raise_if_not_found=False,
        )
        if not group:
            return False

        user_groups = self.env.user.sudo().groups_id
        if 'trans_implied_ids' in user_groups._fields:
            user_groups |= user_groups.trans_implied_ids

        return group in user_groups

    @api.model
    def _hlv_check_default_barcode_action_access(self, action_id):
        action_ids = self._hlv_default_barcode_action_ids()
        if not action_ids:
            return

        normalized_action_id = action_id
        if isinstance(action_id, str):
            if action_id.isdigit():
                normalized_action_id = int(action_id)
            else:
                action = self.env.ref(action_id, raise_if_not_found=False)
                normalized_action_id = action.id if action else action_id

        if (
            isinstance(normalized_action_id, int)
            and normalized_action_id in action_ids
            and not self._hlv_user_has_default_barcode_access()
        ):
            raise AccessError(_('Bạn không có quyền truy cập Barcode mặc định của Odoo.'))

    @api.model
    def load(self, action_id, *args, **kwargs):
        self._hlv_check_default_barcode_action_access(action_id)
        return super().load(action_id, *args, **kwargs)

    @api.model
    def _for_xml_id(self, full_xml_id):
        self._hlv_check_default_barcode_action_access(full_xml_id)
        return super()._for_xml_id(full_xml_id)
