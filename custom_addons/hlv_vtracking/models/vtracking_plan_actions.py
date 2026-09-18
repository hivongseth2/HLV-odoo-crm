"""Các nút bấm trên kế hoạch giao hàng.

Tách khỏi ``vtracking_plan.py`` để file đó chỉ còn khai field và compute — hai thứ đọc
cùng nhau thì hiểu được mô hình dữ liệu, còn trộn thêm chục hành động vào thì phải cuộn
qua chúng mới thấy field tiếp theo.
"""

from odoo import models
from odoo.exceptions import UserError

from odoo.addons.hlv_vtracking.tools.vtracking_planning import nearest_first_order


class HlvVtrackingPlanActions(models.Model):
    _inherit = 'hlv.vtracking.plan'

    def action_confirm(self):
        for plan in self:
            if not plan.line_ids:
                raise UserError('Kế hoạch "%s" chưa có phiếu nào.' % plan.name)
        self.write({'state': 'confirmed'})
        return True

    def action_back_to_draft(self):
        self.write({'state': 'draft'})
        return True

    def action_done(self):
        self.write({'state': 'done'})
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True

    def action_refresh_lines(self):
        """Đọc lại địa chỉ, tiền và toạ độ từ phiếu.

        Cần nút này vì dòng kế hoạch chụp lại số liệu lúc xếp: phiếu sửa tiền hay sửa địa
        chỉ sau đó thì kế hoạch không tự biết. Chụp lại chứ không đọc thẳng để con số trên
        kế hoạch đã chốt không đổi sau lưng người điều phối.
        """
        self.mapped('line_ids')._sync_from_source()
        return True

    def action_add_documents(self):
        """Mở hộp thoại xếp thêm phiếu/đơn vào chính kế hoạch này."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Xếp thêm vào %s' % self.name,
            'res_model': 'hlv.vtracking.plan.add.picking',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_plan_id': self.id, 'default_mode': 'existing'},
        }

    def action_resequence_by_distance(self):
        """Sắp thứ tự ghé theo "đi tới điểm gần nhất chưa ghé".

        Không phải lời giải tối ưu, chỉ là điểm khởi đầu đỡ tệ hơn thứ tự nhập tay — người
        điều phối vẫn kéo tay lại được. Thuật toán ở ``tools/vtracking_planning``.
        """
        for plan in self:
            lines = plan._ordered_lines()
            points = [
                (line.id, (line.latitude, line.longitude) if line.latitude and line.longitude else None)
                for line in lines
            ]
            order = nearest_first_order(plan._route_start(), points)
            by_id = {line.id: line for line in lines}
            for position, line_id in enumerate(order, start=1):
                by_id[line_id].sequence = position * 10
        return True

    def action_open_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Phiếu trong %s' % self.name,
            'res_model': 'hlv.vtracking.plan.line',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }
