import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HlvVtrackingPlanLine(models.Model):
    """Một điểm giao trong kế hoạch — trỏ tới phiếu giao, hoặc tới đơn bán khi phiếu
    chưa có.

    Vì sao cho phép chưa có phiếu: điều phối chốt "chiều nay giao đơn này" từ sáng, trong
    khi kho còn chưa soạn hàng nên phiếu xuất chưa tồn tại. Bắt phải có phiếu mới xếp được
    thì kế hoạch buổi chiều không lập được vào buổi sáng — đúng lúc cần lập nhất.

    Khi phiếu xuất của đơn đó được tạo, hệ thống tự gắn vào dòng này (xem
    ``stock.picking.create``). Trước đó, địa chỉ và tiền lấy tạm từ đơn bán.

    Địa chỉ, tiền và toạ độ được **chụp lại** chứ không đọc thẳng mỗi lần hiển thị: con số
    trên kế hoạch đã chốt không được đổi sau lưng người điều phối, và tra toạ độ là việc
    tốn tiền nên phải làm một lần rồi giữ.
    """

    _name = 'hlv.vtracking.plan.line'
    _description = 'Điểm giao trong kế hoạch'
    _order = 'plan_id, sequence, id'
    _rec_name = 'display_reference'

    plan_id = fields.Many2one(
        'hlv.vtracking.plan', required=True, index=True, ondelete='cascade', string='Kế hoạch',
    )
    sequence = fields.Integer(default=10, string='Thứ tự ghé')

    # --- Nguồn: phiếu giao, hoặc đơn bán khi phiếu chưa có ------------------
    picking_id = fields.Many2one(
        'stock.picking', string='Phiếu giao', index=True, ondelete='cascade',
    )
    sale_order_id = fields.Many2one(
        'sale.order', string='Đơn bán', index=True, ondelete='cascade',
        help='Điền khi xếp đơn vào kế hoạch lúc kho chưa soạn hàng, phiếu xuất chưa có.',
    )
    line_state = fields.Selection(
        [('waiting_picking', 'Chờ phiếu xuất'), ('ready', 'Đã có phiếu')],
        compute='_compute_line_state', store=True, string='Tình trạng', index=True,
    )
    display_reference = fields.Char(
        compute='_compute_display_reference', store=True, string='Chứng từ',
    )

    # --- Chụp lại từ nguồn --------------------------------------------------
    picking_name = fields.Char(related='picking_id.name', string='Mã phiếu', store=True)
    source_name = fields.Char(
        string='Đơn bán', readonly=True,
        help='Số đơn bán. Điều phối gọi nhau bằng số đơn chứ không bằng mã phiếu xuất kho.',
    )
    partner_id = fields.Many2one('res.partner', string='Khách hàng', readonly=True)
    address = fields.Char(string='Địa chỉ giao', readonly=True)
    amount = fields.Monetary(string='Tiền hàng', readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='plan_id.currency_id', readonly=True)
    scheduled_date = fields.Datetime(string='Ngày giao dự kiến', readonly=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho xuất', readonly=True, index=True,
    )

    # --- Điểm giao và cụm tuyến ---------------------------------------------
    place_id = fields.Many2one(
        'hlv.vtracking.place', string='Điểm giao', compute='_compute_place_id', store=True,
        help='Điểm giao vật lý ứng với khách của chứng từ này. Là nơi treo thói quen khách, '
             'và là nguồn DỰ PHÒNG để suy cụm khi địa chỉ chưa tra được toạ độ.',
    )
    zone_id = fields.Many2one(
        'hlv.vtracking.zone', string='Cụm tuyến', index=True,
        compute='_compute_zone_id', inverse='_inverse_zone_id', store=True, readonly=False,
        help='Suy từ TOẠ ĐỘ của địa chỉ giao trên chứng từ này. Sửa tay được — sửa rồi thì '
             'máy không đè lên nữa.',
    )
    zone_source = fields.Selection(
        [
            ('coords', 'Theo toạ độ'),
            ('place', 'Theo điểm giao của khách'),
            ('manual', 'Gán tay'),
            ('none', 'Chưa xác định'),
        ],
        string='Cụm suy từ', default='none', readonly=True, copy=False,
    )
    zone_distance_km = fields.Float(
        string='Cách điểm mẫu (km)', digits=(10, 2), readonly=True, copy=False,
        help='Khoảng cách tới điểm giao đã biết gần nhất. Càng nhỏ càng chắc.',
    )
    zone_uncertain = fields.Boolean(
        string='Cụm chưa chắc', readonly=True, copy=False,
        help='Điểm mẫu gần nhất ở xa, hoặc phải đoán theo khách vì chưa có toạ độ. Nên soát '
             'lại trước khi tin vào định mức thời gian.',
    )

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
        # Một phiếu / một đơn chỉ nằm trong một kế hoạch: hai xe cùng chở một chứng từ là
        # lỗi xếp, phát hiện lúc ghi rẻ hơn phát hiện lúc tài xế đã ra đường.
        # Postgres cho phép nhiều NULL trong cột unique, nên dòng chờ phiếu không vướng.
        ('picking_uniq', 'unique(picking_id)',
         'Phiếu này đã nằm trong một kế hoạch giao khác.'),
        ('sale_order_uniq', 'unique(sale_order_id)',
         'Đơn bán này đã nằm trong một kế hoạch giao khác.'),
    ]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('picking_id')
    def _compute_line_state(self):
        for line in self:
            line.line_state = 'ready' if line.picking_id else 'waiting_picking'

    @api.depends('picking_id', 'picking_id.name', 'sale_order_id', 'sale_order_id.name')
    def _compute_display_reference(self):
        for line in self:
            line.display_reference = (
                line.picking_id.name or line.sale_order_id.name or 'Chưa có chứng từ'
            )

    @api.constrains('picking_id', 'sale_order_id')
    def _check_has_source(self):
        for line in self:
            if not line.picking_id and not line.sale_order_id:
                raise ValidationError(
                    'Mỗi dòng kế hoạch phải trỏ tới một phiếu giao hoặc một đơn bán.'
                )

    # ------------------------------------------------------------------
    # Tạo và đồng bộ
    # ------------------------------------------------------------------
    @api.depends('partner_id')
    def _compute_place_id(self):
        """Ghép chứng từ với điểm giao qua PHÁP NHÂN GỐC của khách.

        Odoo sinh nhiều mã cho cùng một công ty (đo được 351 mã = 176 khách thật), nên so
        thẳng ``partner_id`` sẽ trượt phần lớn. ``commercial_partner_id`` là pháp nhân gốc.

        Điểm này KHÔNG quyết định cụm tuyến — cụm suy từ toạ độ của chính địa chỉ giao,
        xem ``_compute_zone_id``. Nó dùng để treo thói quen khách, và làm nguồn dự phòng
        khi địa chỉ chưa tra được toạ độ.
        """
        Place = self.env['hlv.vtracking.place']
        for line in self:
            root = line.partner_id.commercial_partner_id
            if not root:
                line.place_id = False
                continue
            line.place_id = Place.search([
                ('partner_id.commercial_partner_id', '=', root.id),
                ('company_id', '=', line.company_id.id or self.env.company.id),
            ], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._sync_from_source()
        return lines

    def _sync_from_source(self):
        """Chụp lại địa chỉ, khách, tiền từ nguồn và tra toạ độ qua kho dùng chung.

        Nguồn ưu tiên là PHIẾU: khi phiếu đã có thì địa chỉ trên phiếu là thứ kho thật sự
        sẽ giao tới, còn địa chỉ trên đơn chỉ là dự kiến.

        Tra toạ độ đi qua ``hlv.vtracking.address.resolve()`` — nơi duy nhất được phép gọi
        ra ngoài, và chỉ gọi khi trong kho chưa có địa chỉ đó.
        """
        Address = self.env['hlv.vtracking.address']
        for line in self:
            values = line._source_values()
            if not values:
                continue
            raw_address = values.get('address') or ''
            # Địa chỉ không đổi thì giữ nguyên bản ghi toạ độ cũ, khỏi tra lại.
            if raw_address and (not line.address_id or line.address != raw_address):
                values['address_id'] = Address.resolve(raw_address).id or False
            line.write(values)
        return True

    def _source_values(self):
        """dict giá trị chụp từ phiếu (nếu có) hoặc từ đơn bán. Rỗng nếu không có nguồn."""
        self.ensure_one()
        picking = self.picking_id
        if picking:
            return {
                'address': picking._vtracking_delivery_address(),
                'source_name': picking._vtracking_source_name(),
                'amount': picking._vtracking_amount(),
                'partner_id': picking.partner_id.id or False,
                'scheduled_date': picking.scheduled_date or False,
                'warehouse_id': picking.picking_type_id.warehouse_id.id or False,
            }

        order = self.sale_order_id
        if not order:
            return {}
        # Chưa có phiếu: lấy tạm từ đơn. Địa chỉ giao của đơn là địa chỉ DỰ KIẾN — khi
        # phiếu ra đời, `_sync_from_source` sẽ ghi đè bằng địa chỉ trên phiếu.
        return {
            'address': order._vtracking_delivery_address(),
            'source_name': order.name or '',
            'amount': order.amount_total or 0.0,
            'partner_id': order.partner_id.id or False,
            'scheduled_date': order.commitment_date or False,
            'warehouse_id': order.warehouse_id.id or False,
        }

    def action_retry_geocode(self):
        """Tra lại toạ độ — dùng sau khi sửa địa chỉ trên phiếu hoặc trên đơn."""
        Address = self.env['hlv.vtracking.address']
        for line in self:
            raw_address = (line._source_values() or {}).get('address') or ''
            if not raw_address:
                raise UserError(
                    'Chứng từ %s không có địa chỉ giao. Điền ô "Địa chỉ giao hàng" rồi '
                    'thử lại.' % line.display_reference
                )
            record = Address.resolve(raw_address)
            if record and not record.has_coords:
                record.action_geocode_retry()
            line.write({'address': raw_address, 'address_id': record.id or False})
        return True

    def action_open_source(self):
        """Mở phiếu nếu đã có, còn không thì mở đơn bán."""
        self.ensure_one()
        if self.picking_id:
            return {
                'type': 'ir.actions.act_window', 'res_model': 'stock.picking',
                'res_id': self.picking_id.id, 'view_mode': 'form', 'target': 'current',
            }
        if self.sale_order_id:
            return {
                'type': 'ir.actions.act_window', 'res_model': 'sale.order',
                'res_id': self.sale_order_id.id, 'view_mode': 'form', 'target': 'current',
            }
        raise UserError('Dòng này chưa gắn với chứng từ nào.')

    # ------------------------------------------------------------------
    # Nối phiếu mới sinh vào dòng đang chờ
    # ------------------------------------------------------------------
    @api.model
    def attach_new_pickings(self, pickings):
        """Gắn phiếu xuất mới sinh vào dòng kế hoạch đang chờ phiếu của cùng đơn bán.

        Gọi từ ``stock.picking.create``. Chỉ nhận phiếu XUẤT: đơn bán còn sinh phiếu lấy
        hàng, phiếu đóng gói — gắn nhầm thì kế hoạch trỏ vào một chứng từ không giao cho
        khách.
        """
        outgoing = pickings.filtered(
            lambda p: p.picking_type_id.code == 'outgoing' and p.sale_id
        )
        if not outgoing:
            return False
        waiting = self.sudo().search([
            ('picking_id', '=', False),
            ('sale_order_id', 'in', outgoing.mapped('sale_id').ids),
        ])
        if not waiting:
            return False
        by_order = {}
        for picking in outgoing:
            by_order.setdefault(picking.sale_id.id, picking)
        attached = self.browse()
        for line in waiting:
            picking = by_order.get(line.sale_order_id.id)
            # Phiếu đã nằm ở dòng khác thì bỏ qua: ràng buộc unique sẽ chặn, nhưng chặn
            # bằng lỗi ở giữa lúc xác nhận đơn bán thì người dùng không hiểu vì sao.
            if not picking or picking.plan_line_ids:
                continue
            line.picking_id = picking.id
            attached |= line
        if attached:
            attached._sync_from_source()
            _logger.info('V-Tracking: nối %s phiếu xuất mới vào kế hoạch đang chờ.', len(attached))
        return True
