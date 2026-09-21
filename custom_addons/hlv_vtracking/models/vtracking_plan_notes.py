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

from markupsafe import Markup

from odoo import fields, models
from odoo.exceptions import UserError

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


def format_reasoning(actor, reasoning):
    """Lý giải dạng chữ -> HTML an toàn để đăng lên chatter.

    Odoo 17+ escape mọi ``body`` kiểu ``str``, nên truyền chuỗi có ``<br/>`` thì chatter
    hiện nguyên thẻ ra. Phải là ``Markup`` — nhưng KHÔNG được bọc thẳng chuỗi AI gửi vào,
    vì như vậy bên gọi API chèn được HTML tuỳ ý vào chatter. Ở đây chỉ phần khung là
    Markup; từng dòng nội dung đi qua ``Markup % ...`` / ``join`` nên vẫn bị escape.

    Hiểu hai quy ước đơn giản để chatter dễ đọc:
    - dòng viết HOA toàn bộ và kết thúc bằng ``:`` -> tiêu đề in đậm
    - dòng rỗng -> ngắt đoạn
    """
    rows = []
    for line in reasoning.split('\n'):
        text = line.strip()
        if not text:
            # Nối bằng <br/> nên một dòng rỗng tự thành đúng một dòng trống.
            rows.append(Markup(''))
        elif text.endswith(':') and text == text.upper() and any(c.isalpha() for c in text):
            rows.append(Markup('<b>%s</b>') % text)
        else:
            rows.append(Markup('%s') % text)
    body = Markup('<br/>').join(rows)
    return Markup('<b>AI (%s) lý giải:</b><br/>%s') % (actor, body)


def format_excluded(excluded):
    """Danh sách đơn bị loại -> chuỗi đọc được. Rỗng trả về False để ô trống hẳn.

    Nhận list dict ``{'name'/'order_name', 'reason'}``, hoặc list chuỗi, hoặc một chuỗi
    sẵn. Nhận nhiều dạng vì bên gọi là AI — bắt nó nhớ đúng một dạng chỉ tạo thêm chỗ hỏng.
    """
    if not excluded:
        return False
    if isinstance(excluded, str):
        return excluded.strip() or False
    lines = []
    for item in excluded:
        if isinstance(item, dict):
            label = item.get('name') or item.get('order_name') or item.get('reference') or '?'
            reason = (item.get('reason') or '').strip()
            lines.append('· %s — %s' % (label, reason) if reason else '· %s' % label)
        else:
            lines.append('· %s' % item)
    return '\n'.join(lines) or False
