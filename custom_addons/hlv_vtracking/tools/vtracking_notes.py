"""Chữ AI gửi lên -> nội dung hiện được trên chatter và trên form. Hàm thuần.

Nằm ở ``tools/`` chứ không ở file model vì cả model kế hoạch lẫn dịch vụ trả lời yêu cầu
đều dùng. Nhập một file MODEL từ một service là kéo lớp kế thừa ``hlv.vtracking.plan`` vào
registry trước cả model gốc — đúng lỗi "Model does not exist in registry" đã gặp thật.

Không đụng ``self.env``, không ghi gì.
"""

from markupsafe import Markup


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
