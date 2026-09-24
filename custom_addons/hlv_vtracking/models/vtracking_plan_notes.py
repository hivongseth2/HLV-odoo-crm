"""Chỗ AI ghi lại LÝ GIẢI của nó cho một kế hoạch.

Vì sao cần: tờ kế hoạch in ra có danh sách điểm, nhưng không có câu *"Coherent không đi vì
trễ khai hải quan 26 ngày"*. Người điều phối mở kế hoạch lên chỉ thấy KẾT QUẢ, không thấy
AI đã cân nhắc gì và bỏ gì — nên không kiểm được nó đúng hay sai, và cũng không học được
gì từ nó.

Hai chỗ chứa, cố ý khác nhau:

* **chatter** — dòng suy luận, đọc một lần rồi thôi, có dấu thời gian và tên khoá API.
* ``ai_excluded_note`` — danh sách đơn BỊ LOẠI kèm lý do, nằm ngay trên form để người điều
  phối soát trước khi xác nhận. Đây là thứ hay sai nhất, nên phải nhìn thấy chứ không phải
  cuộn chatter đi tìm.
"""

from odoo import fields, models
from odoo.exceptions import UserError

from ..tools.vtracking_notes import format_excluded, format_reasoning

MAX_NOTE_LENGTH = 8000


class HlvVtrackingPlanNotes(models.Model):
    _inherit = 'hlv.vtracking.plan'

    ai_excluded_note = fields.Text(
        string='Đơn bị loại và lý do', copy=False,
        help='AI ghi vào đây những đơn nó đã cân nhắc nhưng không xếp, kèm lý do. Soát ô '
             'này trước khi xác nhận: bỏ sót một đơn đáng giao tốn hơn xếp thừa một đơn.',
    )
    ai_reasoning_at = fields.Datetime(string='AI ghi lý giải lúc', readonly=True, copy=False)

    def write_ai_notes(self, reasoning=None, excluded=None, actor='AI'):
        """Ghi lý giải vào chatter và danh sách đơn bị loại vào form.

        Truyền cái nào ghi cái đó — gọi lại chỉ với ``excluded`` thì phần lý giải cũ trên
        chatter vẫn còn nguyên, vì chatter là nhật ký chứ không phải một ô bị ghi đè.

        ``excluded`` GHI ĐÈ ô cũ chứ không nối thêm: nó là ảnh chụp của lần cân nhắc gần
        nhất, nối thêm sẽ thành một danh sách dài lẫn lộn đơn đã xếp rồi.
        """
        self.ensure_one()
        reasoning = (reasoning or '').strip()
        if reasoning and len(reasoning) > MAX_NOTE_LENGTH:
            raise UserError(
                'Lý giải dài quá %s ký tự. Tóm tắt lại — chatter là chỗ đọc, không phải '
                'chỗ đổ log.' % MAX_NOTE_LENGTH
            )
        values = {'ai_reasoning_at': fields.Datetime.now()}
        if excluded is not None:
            values['ai_excluded_note'] = format_excluded(excluded)
        self.write(values)
        if reasoning:
            self.message_post(body=format_reasoning(actor, reasoning), message_type='notification')
        return True
