from odoo import api, fields, models
from odoo.exceptions import UserError

# Trần số phiếu xếp một lần. Mỗi phiếu có thể kéo theo một lượt tra toạ độ, mà tra là
# việc chậm và tốn tiền — chọn nhầm cả nghìn phiếu sẽ treo giao diện.
MAX_PICKINGS = 100


class HlvVtrackingPlanAddPicking(models.TransientModel):
    """Xếp các phiếu giao đang chọn lên xe.

    Cho phép chọn kế hoạch có sẵn HOẶC khai (xe, ngày, buổi) để tạo mới ngay tại đây:
    người điều phối đang đứng ở danh sách phiếu, bắt họ sang màn khác tạo kế hoạch rồi
    quay lại là thừa một bước.
    """

    _name = 'hlv.vtracking.plan.add.picking'
    _description = 'Xếp phiếu vào kế hoạch giao'

    picking_ids = fields.Many2many('stock.picking', string='Phiếu giao', required=True)

    mode = fields.Selection(
        [('existing', 'Kế hoạch có sẵn'), ('new', 'Tạo kế hoạch mới')],
        default='new', required=True, string='Xếp vào',
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
        'hlv.vtracking.place', string='Xuất phát từ', domain="[('has_coords', '=', True)]",
    )

    already_planned_count = fields.Integer(compute='_compute_preview', string='Đã có kế hoạch')
    to_add_count = fields.Integer(compute='_compute_preview', string='Sẽ xếp')
    no_address_count = fields.Integer(compute='_compute_preview', string='Không có địa chỉ')
    not_ready_count = fields.Integer(
        compute='_compute_preview', string='Không ở trạng thái Sẵn sàng',
    )

    @api.depends('picking_ids')
    def _compute_preview(self):
        for wizard in self:
            planned = wizard.picking_ids.filtered('plan_line_ids')
            addable = wizard.picking_ids - planned
            wizard.already_planned_count = len(planned)
            wizard.to_add_count = len(addable)
            wizard.no_address_count = len(
                addable.filtered(lambda p: not p._vtracking_delivery_address())
            )
            # Cảnh báo chứ không chặn: phiếu chưa Sẵn sàng vẫn xếp trước được khi hàng
            # chắc chắn về kịp, còn phiếu Huỷ/Hoàn tất thì gần như luôn là chọn nhầm.
            wizard.not_ready_count = len(
                addable.filtered(lambda p: p.state != 'assigned')
            )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        picking_ids = self.env.context.get('active_ids') or []
        if self.env.context.get('active_model') == 'stock.picking' and picking_ids:
            values['picking_ids'] = [fields.Command.set(picking_ids)]
        return values

    def action_add(self):
        self.ensure_one()
        if len(self.picking_ids) > MAX_PICKINGS:
            raise UserError(
                'Chọn tối đa %s phiếu một lần. Đang chọn %s — chia nhỏ ra để việc tra toạ '
                'độ không treo màn hình.' % (MAX_PICKINGS, len(self.picking_ids))
            )

        plan = self._get_or_create_plan()
        # Phiếu đã nằm trong kế hoạch khác thì BỎ QUA chứ không chuyển sang: chuyển xe là
        # quyết định của người điều phối, không phải hệ quả phụ của một lần xếp hàng loạt.
        addable = self.picking_ids.filtered(lambda p: not p.plan_line_ids)
        if not addable:
            raise UserError('Mọi phiếu đang chọn đều đã nằm trong một kế hoạch giao.')

        start_sequence = max(plan.line_ids.mapped('sequence') or [0])
        self.env['hlv.vtracking.plan.line'].create([{
            'plan_id': plan.id,
            'picking_id': picking.id,
            'sequence': start_sequence + (index + 1) * 10,
        } for index, picking in enumerate(addable)])

        return {
            'type': 'ir.actions.act_window',
            'name': plan.name,
            'res_model': 'hlv.vtracking.plan',
            'res_id': plan.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _get_or_create_plan(self):
        """Kế hoạch đích. Tạo mới nếu người dùng chọn chế độ "mới".

        Dùng lại kế hoạch trùng (xe, ngày, buổi) nếu đã có thay vì báo lỗi ràng buộc: từ
        góc nhìn người dùng, "xếp thêm phiếu cho xe đó buổi đó" là việc hợp lệ.
        """
        self.ensure_one()
        if self.mode == 'existing':
            if not self.plan_id:
                raise UserError('Chưa chọn kế hoạch để xếp vào.')
            return self.plan_id

        if not self.vehicle_id:
            raise UserError('Chưa chọn xe cho kế hoạch mới.')
        Plan = self.env['hlv.vtracking.plan']
        existing = Plan.search([
            ('vehicle_id', '=', self.vehicle_id.id),
            ('date', '=', self.date),
            ('session', '=', self.session),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if existing:
            return existing
        return Plan.create({
            'vehicle_id': self.vehicle_id.id,
            'date': self.date,
            'session': self.session,
            'start_place_id': self.start_place_id.id or False,
        })
