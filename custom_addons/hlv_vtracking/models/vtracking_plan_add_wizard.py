from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import plan_documents
from ..tools.vtracking_channel import needs_company_truck


class HlvVtrackingPlanAddPicking(models.TransientModel):
    """Xếp phiếu giao — hoặc đơn bán chưa có phiếu — lên xe.

    Cho phép chọn kế hoạch có sẵn HOẶC khai (xe, ngày, buổi) để tạo mới ngay tại đây:
    người điều phối đang đứng ở danh sách phiếu, bắt họ sang màn khác tạo kế hoạch rồi
    quay lại là thừa một bước.
    """

    _name = 'hlv.vtracking.plan.add.picking'
    _description = 'Xếp chứng từ vào kế hoạch giao'

    source_type = fields.Selection(
        [('picking', 'Phiếu giao đã có'), ('sale', 'Đơn bán chưa có phiếu')],
        default='picking', required=True, string='Xếp theo',
        help='Chọn "Đơn bán" khi chốt chuyến từ sáng mà kho chưa soạn hàng. Phiếu xuất '
             'sinh ra sau sẽ tự gắn vào kế hoạch.',
    )
    picking_ids = fields.Many2many('stock.picking', string='Phiếu giao')
    sale_order_ids = fields.Many2many('sale.order', string='Đơn bán')

    mode = fields.Selection(
        [('existing', 'Kế hoạch có sẵn'), ('new', 'Tạo kế hoạch mới')],
        default='new', required=True, string='Xếp vào',
    )
    plan_locked = fields.Boolean(
        readonly=True,
        help='True khi mở từ bên trong một kế hoạch: lúc đó không có gì để chọn, chứng từ '
             'chỉ có thể xếp vào chính kế hoạch đang mở.',
    )
    plan_id = fields.Many2one(
        'hlv.vtracking.plan', string='Kế hoạch',
        domain="[('state', 'in', ('draft', 'confirmed'))]",
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Xe', domain="[('vtracking_enabled', '=', True)]",
    )
    date = fields.Date(string='Ngày', default=fields.Date.context_today)
    session = fields.Selection(
        [('morning', 'Sáng'), ('afternoon', 'Chiều'), ('full_day', 'Cả ngày')],
        string='Buổi', default='morning',
    )
    start_place_id = fields.Many2one(
        'hlv.vtracking.place', string='Xuất phát từ',
        domain="[('has_coords', '=', True), ('warehouse_id', '!=', False)]",
        help='Chỉ chọn được địa điểm đã gắn với một kho trong Odoo — xe luôn xuất phát từ '
             'kho, và phải biết là kho nào thì mới lọc được chứng từ của đúng kho đó.',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho xuất phát', compute='_compute_warehouse_id',
        store=True, readonly=False,
        help='Lấy theo kho gắn với địa điểm xuất phát. Dùng để lọc chứng từ của đúng kho '
             'đó — xếp phiếu kho khác lên xe đang đứng ở kho này là chuyến không chạy được.',
    )
    filter_by_warehouse = fields.Boolean(
        string='Chỉ lấy chứng từ của kho đó', default=True,
    )

    # Domain tính bằng Python thay vì nhồi biểu thức vào XML: nó phụ thuộc kho xuất phát
    # và ô "chỉ lấy chứng từ của kho đó", viết trong view sẽ thành một dòng không ai đọc nổi.
    picking_domain = fields.Binary(compute='_compute_domains')
    sale_domain = fields.Binary(compute='_compute_domains')

    already_planned_count = fields.Integer(compute='_compute_preview', string='Đã có kế hoạch')
    to_add_count = fields.Integer(compute='_compute_preview', string='Sẽ xếp')
    no_address_count = fields.Integer(compute='_compute_preview', string='Không có địa chỉ')
    not_ready_count = fields.Integer(
        compute='_compute_preview', string='Không ở trạng thái Sẵn sàng',
    )
    other_warehouse_count = fields.Integer(
        compute='_compute_preview', string='Khác kho xuất phát',
    )
    closed_order_count = fields.Integer(
        compute='_compute_preview', string='Đơn đã khoá sổ / huỷ',
    )
    no_truck_count = fields.Integer(
        compute='_compute_preview', string='Không cần xe công ty',
        help='Chứng từ ghi khách tự lấy, gửi CPN hoặc book Grab. Xếp lên xe là thừa một '
             'điểm dừng — lỗi đã xảy ra thật khi xếp tay.',
    )
    no_truck_labels = fields.Char(compute='_compute_preview', string='Cụ thể là')

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('mode', 'plan_id', 'plan_id.start_place_id', 'start_place_id')
    def _compute_warehouse_id(self):
        """Kho làm mốc để lọc chứng từ.

        Khi xếp vào kế hoạch có sẵn thì mốc là kho của CHÍNH kế hoạch đó — điểm xuất phát
        đã chọn ở ngoài, hỏi lại trong này là thừa và còn tạo ra khả năng khai hai giá trị
        khác nhau cho cùng một chuyến.
        """
        for wizard in self:
            if wizard.mode == 'existing' or wizard.plan_locked:
                place = wizard.plan_id.start_place_id
            else:
                place = wizard.start_place_id
            wizard.warehouse_id = place.warehouse_id.id or False

    @api.depends('warehouse_id', 'filter_by_warehouse')
    def _compute_domains(self):
        """Chứng từ nào được phép chọn.

        Luôn loại chứng từ đã nằm trong kế hoạch khác. Lọc theo kho là tuỳ chọn vì có
        chuyến gom hàng của hai kho — mặc định bật, vì đó là trường hợp thường gặp.
        """
        for wizard in self:
            warehouse = wizard.warehouse_id if wizard.filter_by_warehouse else None
            picking_domain = plan_documents.loadable_picking_domain(warehouse)
            sale_domain = plan_documents.open_order_domain(warehouse) + [
                ('vtracking_plan_id', '=', False),
            ]
            wizard.picking_domain = picking_domain
            wizard.sale_domain = sale_domain

    @api.depends('picking_ids', 'sale_order_ids', 'source_type', 'warehouse_id')
    def _compute_preview(self):
        for wizard in self:
            if wizard.source_type == 'picking':
                planned = wizard.picking_ids.filtered('plan_line_ids')
                addable = wizard.picking_ids - planned
                wizard.no_address_count = len(
                    addable.filtered(lambda p: not p._vtracking_delivery_address())
                )
                wizard.not_ready_count = len(addable.filtered(lambda p: p.state != 'assigned'))
                wizard.other_warehouse_count = len(addable.filtered(
                    lambda p: wizard.warehouse_id
                    and p.picking_type_id.warehouse_id != wizard.warehouse_id
                )) if wizard.warehouse_id else 0
            else:
                planned = wizard.sale_order_ids.filtered('vtracking_plan_line_ids')
                addable = wizard.sale_order_ids - planned
                wizard.no_address_count = len(addable.filtered(
                    lambda o: not o._vtracking_delivery_address()
                ))
                wizard.not_ready_count = 0
                wizard.other_warehouse_count = len(addable.filtered(
                    lambda o: wizard.warehouse_id and o.warehouse_id != wizard.warehouse_id
                )) if wizard.warehouse_id else 0
            wizard.already_planned_count = len(planned)
            wizard.to_add_count = len(addable)
            wizard.closed_order_count = len(plan_documents.closed_order_labels(addable))
            wizard._set_no_truck(addable)

    def _set_no_truck(self, documents):
        """Đếm chứng từ mà xe công ty không phải chạy.

        Cảnh báo chứ không chặn: ô "hình thức giao hàng" là chữ gõ tay, đọc sai một dòng mà
        chặn luôn thì người điều phối không xếp được đơn đáng xếp. Nêu tên ra để họ tự quyết.
        """
        self.ensure_one()
        odd = [
            document for document in documents
            if not needs_company_truck(document._vtracking_delivery_channel())
        ]
        self.no_truck_count = len(odd)
        names = [document.display_name for document in odd[:5]]
        if len(odd) > 5:
            names.append('và %s cái nữa' % (len(odd) - 5))
        self.no_truck_labels = ', '.join(names)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids') or []
        active_model = self.env.context.get('active_model')
        if active_model == 'stock.picking' and active_ids:
            values['source_type'] = 'picking'
            values['picking_ids'] = [fields.Command.set(active_ids)]
        elif active_model == 'sale.order' and active_ids:
            values['source_type'] = 'sale'
            values['sale_order_ids'] = [fields.Command.set(active_ids)]
        if self.env.context.get('default_plan_id'):
            # Mở từ bên trong một kế hoạch: khoá luôn đích đến, không hỏi lại.
            values['mode'] = 'existing'
            values['plan_locked'] = True
        return values

    # ------------------------------------------------------------------
    # Hành động
    # ------------------------------------------------------------------
    def action_add(self):
        """Xếp chứng từ đang chọn vào kế hoạch. Luật xếp nằm ở ``services/plan_documents``."""
        self.ensure_one()
        plan = self._get_or_create_plan()
        result = plan_documents.add_documents(
            plan,
            pickings=self.picking_ids if self.source_type == 'picking' else None,
            orders=self.sale_order_ids if self.source_type == 'sale' else None,
        )
        # Với người bấm nút, đơn đã đóng là LỖI phải thấy chứ không lặng lẽ bỏ qua: họ
        # cần biết đơn nào đã đóng, không phải chỉ thấy số xếp được ít hơn dự kiến.
        closed = [
            item['detail'] for item in result['rejected']
            if item['reason'] == plan_documents.REASON_ORDER_CLOSED
        ]
        if closed:
            raise UserError(
                'Không xếp được vì có đơn đã khoá sổ hoặc đã huỷ: %s '
                'Bỏ những chứng từ này ra rồi thử lại.' % ' '.join(sorted(closed))
            )
        if not result['added_line_ids']:
            raise UserError('Mọi chứng từ đang chọn đều đã nằm trong một kế hoạch giao.')
        return {
            'type': 'ir.actions.act_window',
            'name': plan.name,
            'res_model': 'hlv.vtracking.plan',
            'res_id': plan.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _get_or_create_plan(self):
        """Kế hoạch đích: cái đang chọn, hoặc cái của (xe, ngày, buổi) vừa khai."""
        self.ensure_one()
        if self.mode == 'existing':
            if not self.plan_id:
                raise UserError('Chưa chọn kế hoạch để xếp vào.')
            return self.plan_id
        if not self.vehicle_id:
            raise UserError('Chưa chọn xe cho kế hoạch mới.')
        plan, _created = plan_documents.get_or_create_plan(
            self.env, self.vehicle_id, self.date, self.session, self.start_place_id,
        )
        return plan
