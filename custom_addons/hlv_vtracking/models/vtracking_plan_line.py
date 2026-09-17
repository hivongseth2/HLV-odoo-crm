import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HlvVtrackingPlanLine(models.Model):
    """Một phiếu giao trong kế hoạch, kèm thứ tự ghé và toạ độ điểm đến.

    Địa chỉ, tiền và toạ độ được **chụp lại** lúc xếp chứ không đọc thẳng từ phiếu mỗi
    lần hiển thị. Hai lý do: con số trên kế hoạch đã chốt không được đổi sau lưng người
    điều phối, và tra toạ độ là việc tốn tiền nên phải làm một lần rồi giữ.
    """

    _name = 'hlv.vtracking.plan.line'
    _description = 'Phiếu trong kế hoạch giao'
    _order = 'plan_id, sequence, id'
    _rec_name = 'picking_id'

    plan_id = fields.Many2one(
        'hlv.vtracking.plan', required=True, index=True, ondelete='cascade', string='Kế hoạch',
    )
    sequence = fields.Integer(default=10, string='Thứ tự ghé')
    picking_id = fields.Many2one(
        'stock.picking', string='Phiếu giao', required=True, index=True, ondelete='cascade',
    )

    # --- Chụp lại từ phiếu --------------------------------------------------
    picking_name = fields.Char(related='picking_id.name', string='Mã phiếu', store=True)
    source_name = fields.Char(
        string='Đơn bán', readonly=True,
        help='Số đơn bán gắn với phiếu. Điều phối gọi nhau bằng số đơn chứ không bằng mã '
             'phiếu xuất kho.',
    )
    partner_id = fields.Many2one(
        related='picking_id.partner_id', string='Khách hàng', store=True, readonly=True,
    )
    address = fields.Char(string='Địa chỉ giao', readonly=True)
    amount = fields.Monetary(
        string='Tiền hàng', readonly=True, currency_field='currency_id',
    )
    currency_id = fields.Many2one(related='plan_id.currency_id', readonly=True)
    scheduled_date = fields.Datetime(related='picking_id.scheduled_date', readonly=True)

    # --- Toạ độ, lấy từ kho toạ độ dùng chung -------------------------------
    address_id = fields.Many2one(
        'hlv.vtracking.address', string='Toạ độ đã tra', readonly=True, ondelete='set null',
    )
    latitude = fields.Float(related='address_id.latitude', store=True, digits=(10, 7))
    longitude = fields.Float(related='address_id.longitude', store=True, digits=(10, 7))
    geo_state = fields.Selection(related='address_id.geo_state', store=True, string='Toạ độ')
    has_coords = fields.Boolean(related='address_id.has_coords', store=True)

    # --- Thực tế (chờ hlv_barcode_shipper) ----------------------------------
    delivered = fields.Boolean(
        string='Đã giao', readonly=True, copy=False,
        help='Sẽ do module shipper đánh dấu khi tài xế quét nhận/giao phiếu.',
    )
    delivered_at = fields.Datetime(string='Giao lúc', readonly=True, copy=False)

    plan_date = fields.Date(related='plan_id.date', store=True, index=True)
    vehicle_id = fields.Many2one(related='plan_id.vehicle_id', store=True, index=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True, index=True)

    _sql_constraints = [
        # Một phiếu chỉ nằm trong một kế hoạch: hai xe cùng chở một phiếu là lỗi xếp,
        # phát hiện lúc ghi rẻ hơn phát hiện lúc tài xế đã ra đường.
        ('picking_uniq', 'unique(picking_id)',
         'Phiếu này đã nằm trong một kế hoạch giao khác.'),
    ]

    # ------------------------------------------------------------------
    # Tạo và đồng bộ
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._sync_from_picking()
        return lines

    def _sync_from_picking(self):
        """Chụp lại địa chỉ, đơn bán, tiền từ phiếu và tra toạ độ qua kho dùng chung.

        Tra toạ độ đi qua ``hlv.vtracking.address.resolve()`` — nơi duy nhất được phép
        gọi ra ngoài, và chỉ gọi khi trong kho chưa có địa chỉ đó.
        """
        Address = self.env['hlv.vtracking.address']
        for line in self:
            picking = line.picking_id
            if not picking:
                continue
            raw_address = picking._vtracking_delivery_address()
            values = {
                'address': raw_address,
                'source_name': picking._vtracking_source_name(),
                'amount': picking._vtracking_amount(),
            }
            # Địa chỉ không đổi thì giữ nguyên bản ghi toạ độ cũ, khỏi tra lại.
            if raw_address and (not line.address_id or line.address != raw_address):
                values['address_id'] = Address.resolve(raw_address).id or False
            line.write(values)
        return True

    def action_retry_geocode(self):
        """Tra lại toạ độ cho các dòng chưa có — dùng sau khi sửa địa chỉ trên phiếu."""
        Address = self.env['hlv.vtracking.address']
        for line in self:
            raw_address = line.picking_id._vtracking_delivery_address()
            if not raw_address:
                raise UserError(
                    'Phiếu %s không có địa chỉ giao. Điền ô "Địa chỉ giao hàng" trên phiếu '
                    'rồi thử lại.' % line.picking_name
                )
            record = Address.resolve(raw_address)
            if record and not record.has_coords:
                record.action_geocode_retry()
            line.write({'address': raw_address, 'address_id': record.id or False})
        return True

    def action_open_picking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
