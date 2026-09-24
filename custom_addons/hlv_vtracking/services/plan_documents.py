"""Luật xếp chứng từ (phiếu giao / đơn bán) vào một kế hoạch giao hàng.

Một nguồn duy nhất cho cả hộp thoại "Xếp lên xe" lẫn API cho AI. Người bấm nút và AI gọi
API phải chịu đúng cùng một bộ luật — luật viết hai nơi thì sớm muộn AI xếp được thứ mà
người không xếp được, hoặc ngược lại.
"""

from odoo.exceptions import UserError

# Trần số chứng từ xếp một lần. Mỗi chứng từ có thể kéo theo một lượt tra toạ độ, mà tra
# là việc chậm và tốn tiền — xếp nhầm cả nghìn cái sẽ treo giao diện và đốt quota.
MAX_DOCUMENTS = 100

REASON_ALREADY_PLANNED = 'already_planned'
REASON_ORDER_CLOSED = 'order_closed'


def loadable_picking_domain(warehouse=None):
    """Domain phiếu XẾP LÊN XE ĐƯỢC: phiếu xuất, đang Sẵn sàng, chưa xếp xe, đơn chưa đóng.

    Một định nghĩa duy nhất cho hộp thoại của người dùng lẫn API cho AI — AI không được
    thấy một tập phiếu khác với tập người điều phối thấy.

    Phiếu vẫn Sẵn sàng nhưng ĐƠN đã khoá sổ/huỷ thì không còn gì để giao (thường là phiếu
    sót lại sau khi đơn được xử lý bằng đường khác). Phiếu không gắn đơn nào (chuyển kho,
    trả hàng) vẫn cho xếp.
    """
    domain = [
        ('picking_type_code', '=', 'outgoing'),
        ('state', '=', 'assigned'),
        ('plan_id', '=', False),
        '|', ('sale_id', '=', False), ('sale_id.state', 'not in', ('done', 'cancel')),
    ]
    if warehouse:
        domain.append(('picking_type_id.warehouse_id', '=', warehouse.id))
    return domain


def open_order_domain(warehouse=None):
    """Domain đơn bán CÒN PHẢI GIAO: đã xác nhận, chưa giao đủ. Đơn nháp, đơn khoá sổ, đơn
    huỷ đều không còn gì để xếp lên xe. ``delivery_status`` là trạng thái giao của Odoo:
    pending / started / partial / full."""
    domain = [('state', '=', 'sale'), ('delivery_status', '!=', 'full')]
    if warehouse:
        domain.append(('warehouse_id', '=', warehouse.id))
    return domain


def closed_order_label(document):
    """Nhãn "SO123 (đã khoá sổ)" nếu đơn của chứng từ đã đóng, ngược lại chuỗi rỗng.

    Nhận cả phiếu giao lẫn đơn bán — phiếu thì soi đơn gắn với nó. Phiếu không gắn đơn nào
    (chuyển kho, trả hàng) không bao giờ bị coi là đóng: nó không có đơn nào để đóng.
    """
    order = document if document._name == 'sale.order' else document.sale_id
    if not order or order.state not in ('done', 'cancel'):
        return ''
    return '%s (%s)' % (order.name, 'đã khoá sổ' if order.state == 'done' else 'đã huỷ')


def closed_order_labels(documents):
    """Tập nhãn các đơn đã đóng trong một recordset chứng từ."""
    return {label for label in (closed_order_label(doc) for doc in documents) if label}


def existing_plan_line(document):
    """Dòng kế hoạch đang giữ chứng từ này, hoặc recordset rỗng."""
    if document._name == 'sale.order':
        return document.vtracking_plan_line_ids[:1]
    return document.plan_line_ids[:1]


def classify_documents(documents):
    """Chia chứng từ thành phần xếp được và phần bị loại kèm lý do.

    Trả về ``(addable, rejected)``: ``addable`` là recordset, ``rejected`` là list dict
    ``{'id', 'name', 'reason', 'detail'}``.

    Chứng từ đã nằm trong kế hoạch khác bị LOẠI chứ không tự chuyển sang: chuyển xe là
    quyết định của người điều phối, không phải hệ quả phụ của một lần xếp hàng loạt.
    """
    addable = documents.browse()
    rejected = []
    for document in documents:
        line = existing_plan_line(document)
        if line:
            rejected.append({
                'id': document.id, 'name': document.name,
                'reason': REASON_ALREADY_PLANNED,
                'detail': 'Đã nằm trong kế hoạch "%s".' % line.plan_id.name,
            })
            continue
        closed = closed_order_label(document)
        if closed:
            rejected.append({
                'id': document.id, 'name': document.name,
                'reason': REASON_ORDER_CLOSED,
                'detail': 'Đơn bán %s.' % closed,
            })
            continue
        addable |= document
    return addable, rejected


def add_documents(plan, pickings=None, orders=None):
    """Xếp phiếu giao và/hoặc đơn bán vào kế hoạch, nối vào cuối thứ tự ghé.

    Trả về dict ``{'added_line_ids': [...], 'rejected': [...]}``. Không ném lỗi vì chứng
    từ bị loại — bên gọi tự quyết định đó có phải lỗi không (hộp thoại coi đơn đã đóng là
    lỗi để người dùng biết; API trả danh sách để AI tự điều chỉnh).

    Ném ``UserError`` khi vượt trần số lượng hoặc kế hoạch không còn sửa được.
    """
    plan.ensure_one()
    pickings = pickings if pickings is not None else plan.env['stock.picking']
    orders = orders if orders is not None else plan.env['sale.order']
    total = len(pickings) + len(orders)
    if total > MAX_DOCUMENTS:
        raise UserError(
            'Xếp tối đa %s chứng từ một lần, đang gửi %s. Chia nhỏ ra để việc tra toạ độ '
            'không treo hệ thống.' % (MAX_DOCUMENTS, total)
        )
    if plan.state not in ('draft', 'confirmed'):
        raise UserError(
            'Kế hoạch "%s" đang ở trạng thái %s nên không xếp thêm được.'
            % (plan.name, plan.state)
        )

    addable_pickings, rejected_pickings = classify_documents(pickings)
    addable_orders, rejected_orders = classify_documents(orders)

    sequence = max(plan.line_ids.mapped('sequence') or [0])
    values = []
    for field_name, documents in (('picking_id', addable_pickings), ('sale_order_id', addable_orders)):
        for document in documents:
            sequence += 10
            values.append({'plan_id': plan.id, field_name: document.id, 'sequence': sequence})

    lines = plan.env['hlv.vtracking.plan.line'].create(values) if values else plan.line_ids.browse()
    return {
        'added_line_ids': lines.ids,
        'rejected': rejected_pickings + rejected_orders,
    }


def get_or_create_plan(env, vehicle, day, session, start_place=None):
    """Kế hoạch của (xe, ngày, buổi); tạo mới nếu chưa có.

    Dùng lại kế hoạch trùng thay vì để ràng buộc unique ném lỗi: "xếp thêm cho xe đó buổi
    đó" là việc hợp lệ, không phải lỗi của người gọi. Trả về ``(plan, created)``.
    """
    Plan = env['hlv.vtracking.plan']
    existing = Plan.search([
        ('vehicle_id', '=', vehicle.id),
        ('date', '=', day),
        ('session', '=', session),
        ('company_id', '=', env.company.id),
    ], limit=1)
    if existing:
        return existing, False
    plan = Plan.create({
        'vehicle_id': vehicle.id,
        'date': day,
        'session': session,
        'start_place_id': start_place.id if start_place else False,
    })
    return plan, True
