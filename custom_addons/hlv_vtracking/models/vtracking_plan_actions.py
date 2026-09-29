"""Các nút bấm trên kế hoạch giao hàng.

Tách khỏi ``vtracking_plan.py`` để file đó chỉ còn khai field và compute — hai thứ đọc
cùng nhau thì hiểu được mô hình dữ liệu, còn trộn thêm chục hành động vào thì phải cuộn
qua chúng mới thấy field tiếp theo.
"""

from odoo import models
from odoo.exceptions import UserError

from odoo.addons.hlv_vtracking.tools.vtracking_planning import nearest_first_order
from odoo.addons.hlv_vtracking.tools.vtracking_blocking import PROCEDURE_LABELS

from ..services import vtracking_autoload


class HlvVtrackingPlanActions(models.Model):
    _inherit = 'hlv.vtracking.plan'

    def action_confirm(self):
        for plan in self:
            if not plan.line_ids:
                raise UserError('Kế hoạch "%s" chưa có phiếu nào.' % plan.name)
            plan._check_procedures()
        self.write({'state': 'confirmed'})
        return True

    def _check_procedures(self):
        """Chặn xác nhận khi còn điểm chưa xong thủ tục vào cổng.

        Đây là chỗ CHẶN chứ không phải cảnh báo: xe tới khu chế xuất mà chưa khai hải quan
        thì bảo vệ không cho vào, hàng phải chở về kho — mất trắng cả lượt chạy lẫn chỗ của
        những điểm khác lẽ ra xếp được. Lỗi này đã xảy ra thật ngay ngày đầu chạy tay.

        Xong thủ tục rồi thì tích ô "Thủ tục đã xong" trên dòng. Không có đường vòng nào
        khác — cố tình bỏ qua thì phải gỡ điểm đó khỏi kế hoạch.
        """
        self.ensure_one()
        blocked = self.line_ids.filtered('procedure_blocked')
        if not blocked:
            return True
        detail = '\n'.join(
            '  · %s — %s' % (
                line.display_reference,
                PROCEDURE_LABELS.get(line.procedure_required, line.procedure_required),
            )
            for line in blocked
        )
        raise UserError(
            'Kế hoạch "%s" còn %s điểm chưa xong thủ tục vào cổng:\n\n%s\n\n'
            'Làm xong thủ tục thì tích ô "Thủ tục đã xong" trên từng dòng rồi xác nhận lại.'
            % (self.name, len(blocked), detail)
        )

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

    def action_autoload_documents(self):
        """Dọn và xếp lại kế hoạch theo dữ liệu mới nhất, sắp thứ tự ghé, rồi nhờ AI soát.

        Ba bước, mỗi bước một vai: máy áp LUẬT (phiếu nào xếp được, cụm nào, trần điểm),
        AI đọc những gì luật không nói được (đơn trễ hẹn, toạ độ trông sai, điểm lẻ nên
        gom), người điều phối QUYẾT.

        Chỉ là ĐỀ XUẤT: kế hoạch vẫn ở trạng thái nháp sau cả ba bước. Việc chọn nằm ở
        ``services/vtracking_autoload``.
        """
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(
                'Kế hoạch "%s" đã chốt nên máy không tự gỡ hay thêm nữa — tài xế đang cầm '
                'tờ đó đi. Thủ kho sửa tay bằng nút "Thêm phiếu / đơn", hoặc bấm "Về nháp" '
                'rồi lập lại.' % self.name
            )
        if not self.start_place_id.warehouse_id:
            raise UserError(
                'Điểm xuất phát "%s" chưa gắn kho trong Odoo, nên máy không biết lấy phiếu '
                'của kho nào. Khai ô "Kho trong Odoo" ở địa điểm đó rồi bấm lại.'
                % (self.start_place_id.name or 'chưa chọn')
            )
        summary = vtracking_autoload.autoload(self)
        summary['request'] = (vtracking_autoload.review_request(self, summary)
                              if summary['added'] else None)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Lên kế hoạch giao hàng',
                'message': self._autoload_message(summary),
                'type': 'success' if summary['added'] else 'warning',
                'sticky': True,
            },
        }

    @staticmethod
    def _autoload_message(summary):
        """Câu tóm tắt cho người bấm nút: xếp được gì, còn dư gì, bỏ gì và VÌ SAO bỏ."""
        dong = []
        if summary.get('removed'):
            dong.append('Gỡ %s dòng không còn gì để giao (phiếu đã xuất xong hoặc đã huỷ).'
                        % summary['removed'])
        if not summary['zone']:
            dong.append('Không còn phiếu nào chưa xếp thuộc cụm của chuyến này.')
        else:
            dong.append('Cụm %s: xếp thêm %s phiếu vào %s điểm dừng.'
                        % (summary['zone'].name, summary['added'], summary['stops']))
        if summary['left_out']:
            dong.append('Vượt trần điểm của cụm nên để lại cho chuyến khác: %s.'
                        % ', '.join(summary['left_out'][:5]))
        for ly_do, phieu in summary['skipped'].items():
            dong.append('Bỏ %s phiếu — %s.' % (len(phieu), ly_do))
        request = summary.get('request')
        if request:
            dong.append('Đã gửi AI soát lại (%s). Kế hoạch vẫn là bản nháp cho tới khi '
                        'bạn bấm Chốt.' % request.name)
        elif summary.get('added'):
            dong.append('CHƯA gửi AI soát: công ty chưa khai "Tài khoản worker AI" ở '
                        'Cấu hình, nên phiếu yêu cầu sẽ không ai nhận.')
        return '\n'.join(dong)

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
