"""Phiếu yêu cầu của nhân viên, phía API: lấy việc, nhận việc, trả lời.

Luật trạng thái nằm ở ``tools/vtracking_request`` và ``models/vtracking_ai_request``;
file này chỉ nối API với chúng và dựng dữ liệu bối cảnh cho AI đọc.
"""

from odoo.exceptions import UserError

from ...models.vtracking_plan_notes import format_reasoning
from .serialize import iso_datetime

VERDICTS = ('feasible', 'conditional', 'not_feasible', 'info')
MAX_ANSWER_LENGTH = 8000


def request_block(record):
    """Một phiếu yêu cầu ở dạng dict. Chỉ nêu id của chứng từ liên quan — chi tiết đơn,
    phiếu, kế hoạch đã có endpoint riêng, không nhân bản dữ liệu ở đây."""
    return {
        'id': record.id,
        'state': record.state,
        'approved': record.approved,
        'request_type': record.request_type,
        'request_type_label': dict(record._fields['request_type'].selection)[record.request_type],
        'message': record.message,
        'requester': record.requester_id.name,
        'created_at': iso_datetime(record.create_date),
        'waiting_minutes': record.waiting_minutes,
        'sale_order_id': record.sale_order_id.id or None,
        'sale_order_name': record.sale_order_id.name or None,
        'picking_id': record.picking_id.id or None,
        'picking_name': record.picking_id.name or None,
        'plan_id': record.plan_id.id or None,
        'plan_name': record.plan_id.name or None,
        'plan_state': record.plan_id.state or None,
        'desired_date': str(record.desired_date) if record.desired_date else None,
        'desired_session': record.desired_session or None,
        'verdict': record.verdict or None,
        'applied': record.applied,
        'attempt_count': record.attempt_count,
    }


def list_requests(env, company, params):
    """Phiếu theo trạng thái. Mặc định ``pending`` — đúng thứ worker cần."""
    domain = [('company_id', '=', company.id)]
    state = params.get('state') or 'pending'
    if state != 'all':
        domain.append(('state', '=', state))
    Request = env['hlv.vtracking.ai.request']
    records = Request.search(domain, limit=params['limit'], offset=params['offset'],
                             order='create_date asc')
    return {
        'total': Request.search_count(domain),
        'requests': [request_block(record) for record in records],
    }


def claim_request(record, body):
    """Nhận việc. ``claimed: false`` nghĩa là máy khác đã nhận trước — bỏ qua, đừng thử lại."""
    claimed = record.claim(body.get('worker') or '')
    return {'claimed': claimed, 'request': request_block(record)}


def answer_request(record, body, actor):
    """AI trả lời. ``applied: true`` chỉ khi ĐÃ thật sự sửa kế hoạch nháp xong."""
    verdict = body.get('verdict')
    if verdict not in VERDICTS:
        raise UserError('"verdict" phải là một trong: %s.' % ', '.join(VERDICTS))
    answer = (body.get('answer') or '').strip()
    if not answer:
        raise UserError('Thiếu "answer" — người gửi phải đọc được vì sao.')
    if len(answer) > MAX_ANSWER_LENGTH:
        raise UserError('"answer" dài quá %s ký tự.' % MAX_ANSWER_LENGTH)
    if record.state != 'processing':
        raise UserError('Phiếu #%s không ở trạng thái "AI đang xem" — nhận việc trước khi '
                        'trả lời.' % record.id)
    record.write_answer(verdict, format_reasoning(actor, answer), bool(body.get('applied')))
    return request_block(record)


def fail_request(record, body):
    """Ghi lại việc AI không xử lý được, để người điều phối thấy mà làm tay."""
    error = (body.get('error') or '').strip() or 'Không rõ lý do.'
    record.write_failure(error[:MAX_ANSWER_LENGTH])
    return request_block(record)
