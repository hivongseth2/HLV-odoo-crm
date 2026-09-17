import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Trần số đối tác xử lý một lần. Tra toạ độ là việc chậm (Nominatim 1 request/giây) và
# tốn tiền (Google tính theo lượt); người dùng chọn nhầm 5000 đối tác rồi tick "tra ngay"
# sẽ treo giao diện và đốt quota.
MAX_PARTNERS = 200


class HlvVtrackingPlaceFromPartnerWizard(models.TransientModel):
    """Tạo địa điểm trên bản đồ từ danh sách đối tác đang chọn.

    Chống trùng bằng ``partner_id``: một đối tác chỉ ứng với một địa điểm. Muốn cùng một
    đối tác có hai địa điểm (hai nhà máy chẳng hạn) thì tạo tay địa điểm thứ hai.
    """

    _name = 'hlv.vtracking.place.from.partner'
    _description = 'Tạo địa điểm từ đối tác'

    type_id = fields.Many2one(
        'hlv.vtracking.place.type', string='Loại địa điểm', required=True,
        default=lambda self: self.env['hlv.vtracking.place.type'].search([], limit=1),
    )
    partner_ids = fields.Many2many(
        'res.partner', string='Đối tác', required=True,
        domain="[('is_company', '=', True)]",
    )
    geocode_now = fields.Boolean(
        string='Tra toạ độ ngay', default=True,
        help='Tắt thì địa điểm được tạo nhưng chưa có toạ độ; tác vụ nền sẽ tra dần.',
    )
    skip_existing_count = fields.Integer(
        string='Đã có địa điểm', compute='_compute_preview',
    )
    to_create_count = fields.Integer(string='Sẽ tạo', compute='_compute_preview')

    @api.depends('partner_ids')
    def _compute_preview(self):
        for wizard in self:
            existing = wizard._existing_partner_ids()
            wizard.skip_existing_count = len(existing)
            wizard.to_create_count = len(wizard.partner_ids) - len(existing)

    def _existing_partner_ids(self):
        """Tập id đối tác đã có địa điểm — kể cả địa điểm đang lưu trữ."""
        self.ensure_one()
        if not self.partner_ids:
            return set()
        places = self.env['hlv.vtracking.place'].with_context(active_test=False).search([
            ('partner_id', 'in', self.partner_ids.ids),
        ])
        return set(places.mapped('partner_id').ids)

    def action_create_places(self):
        self.ensure_one()
        if len(self.partner_ids) > MAX_PARTNERS:
            raise UserError(
                'Chọn tối đa %s đối tác một lần. Đang chọn %s — chia nhỏ ra để việc tra '
                'toạ độ không treo màn hình.' % (MAX_PARTNERS, len(self.partner_ids))
            )
        existing = self._existing_partner_ids()
        partners = self.partner_ids.filtered(lambda p: p.id not in existing)
        if not partners:
            raise UserError('Mọi đối tác đang chọn đều đã có địa điểm trên bản đồ.')

        places = self.env['hlv.vtracking.place'].create([{
            'name': partner.name,
            'type_id': self.type_id.id,
            'partner_id': partner.id,
        } for partner in partners])

        if self.geocode_now:
            places._geocode_now_silently()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Địa điểm vừa tạo',
            'res_model': 'hlv.vtracking.place',
            'domain': [('id', 'in', places.ids)],
            'view_mode': 'list,form',
            'target': 'current',
        }
