from odoo import api, fields, models, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    hlv_barcode_auto_cleared = fields.Boolean(
        string="Đã tự động xóa SL",
        default=False,
        copy=False,
        help="Cờ đánh dấu phiếu đã được tự động làm mới số lượng khi quét lần đầu tiên.",
    )

    def _hlv_mobile_sale_order(self):
        self.ensure_one()
        sale_order = self.sale_id if 'sale_id' in self._fields else self.env['sale.order']
        if not sale_order:
            sale_order = self.move_ids.mapped('sale_line_id.order_id')[:1]
        return sale_order

    def _hlv_mobile_is_sale_pick_picking(self):
        self.ensure_one()
        if getattr(self, 'return_id', False):
            return False
        sequence_code = (self.picking_type_id.sequence_code or '').upper()
        type_name = (self.picking_type_id.name or '').lower()
        is_pick_type = 'PICK' in sequence_code or 'pick' in type_name or 'lay hang' in type_name or 'lấy hàng' in type_name
        return bool(is_pick_type and self._hlv_mobile_sale_order())

    def _hlv_mobile_is_shopee_sale_pick(self):
        self.ensure_one()
        sale_order = self._hlv_mobile_sale_order()
        return bool(
            self._hlv_mobile_is_sale_pick_picking()
            and sale_order
            and (
                getattr(sale_order, 'shopee_order_ref', False)
                or getattr(sale_order, 'shopee_shop_id', False)
            )
        )

    def _hlv_mobile_packer_display_name(self, user):
        if not user:
            return ''
        if hasattr(self, '_packer_display_name'):
            return self._packer_display_name(user)
        return getattr(user, 'x_packer_name', None) or user.name or ''

    def _hlv_mobile_is_pick_manager(self, user=None):
        user = user or self.env.user
        if hasattr(self, '_is_pack_manager'):
            return self._is_pack_manager(user)
        return bool(user._is_superuser())

    def _hlv_mobile_assign_default_shopee_picker(self):
        if self.env.context.get('hlv_skip_shopee_default_picker'):
            return True
        now = fields.Datetime.now()
        for picking in self:
            if not picking.exists() or not picking._hlv_mobile_is_shopee_sale_pick():
                continue
            if picking.x_pack_packer_user_id:
                continue
            picker = picking.company_id.hlv_barcode_shopee_default_picker_user_id
            if not picker:
                continue
            vals = {'x_pack_packer_user_id': picker.id}
            if 'x_pack_assigned_by_id' in picking._fields:
                vals['x_pack_assigned_by_id'] = self.env.uid
            if 'x_pack_assigned_at' in picking._fields:
                vals['x_pack_assigned_at'] = now
            picking.sudo().with_context(hlv_skip_shopee_default_picker=True).write(vals)
        return True

    def _check_hlv_mobile_pick_assignment_access(self, user=None, raise_exception=True):
        user = user or self.env.user
        for picking in self:
            if not picking._hlv_mobile_is_sale_pick_picking():
                continue
            picking._hlv_mobile_assign_default_shopee_picker()
            if picking._hlv_mobile_is_pick_manager(user):
                continue
            assigned_user = picking.x_pack_packer_user_id
            if assigned_user and assigned_user.id == user.id:
                continue
            assigned_name = picking._hlv_mobile_packer_display_name(assigned_user) if assigned_user else _('chưa assign')
            message = _('Bạn không được assign xử lý phiếu lấy hàng này. Người xử lý: %s') % assigned_name
            if raise_exception:
                raise UserError(message)
            return False
        return True

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        pickings._hlv_mobile_assign_default_shopee_picker()
        return pickings

    def write(self, vals):
        res = super().write(vals)
        trigger_fields = {'sale_id', 'group_id', 'origin', 'picking_type_id', 'company_id'}
        if vals and trigger_fields.intersection(vals) and not self.env.context.get('hlv_skip_shopee_default_picker'):
            self._hlv_mobile_assign_default_shopee_picker()
        return res

    def action_confirm(self):
        res = super().action_confirm()
        self._hlv_mobile_assign_default_shopee_picker()
        return res


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves.mapped('picking_id')._hlv_mobile_assign_default_shopee_picker()
        return moves

    def write(self, vals):
        res = super().write(vals)
        if vals and {'sale_line_id', 'picking_id'}.intersection(vals):
            self.mapped('picking_id')._hlv_mobile_assign_default_shopee_picker()
        return res

    def _action_confirm(self, *args, **kwargs):
        moves = super()._action_confirm(*args, **kwargs)
        moves.mapped('picking_id')._hlv_mobile_assign_default_shopee_picker()
        return moves
