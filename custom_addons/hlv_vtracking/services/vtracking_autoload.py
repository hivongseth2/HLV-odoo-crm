"""Tự chọn phiếu xuất cho một kế hoạch — phần việc sau nút "Lên kế hoạch giao hàng".

Vì sao cần: người điều phối mở kế hoạch rỗng rồi phải tự lọc trong hàng trăm phiếu xem
phiếu nào đã đóng gói xong, phiếu nào vướng hải quan, phiếu nào khách tự lấy, phiếu nào
cùng cụm với nhau. Máy làm được đúng việc đó bằng những quy tắc ĐÃ có trong module.

Xếp xong thì gửi một phiếu yêu cầu để AI soát lại (``review_request``): máy áp luật,
còn những thứ luật không nói được — đơn trễ hẹn nên ưu tiên, khách có hai nhà máy, con số
km vô lý vì toạ độ sai — cần có người hoặc AI đọc. AI sửa trên bản NHÁP, người điều phối
xem bản cuối rồi mới chốt.

Ba điều file này KHÔNG làm, có chủ đích:

* **không chốt kế hoạch** — chỉ xếp vào bản nháp, người bấm Chốt;
* **không đoán cụm** — cụm lấy từ điểm giao của khách. Khách chưa có điểm thì báo ra để
  người khai, chứ không gán bừa vào cụm gần nhất;
* **không vượt trần điểm của cụm** — phần dư được liệt kê để xếp sang chuyến khác.

Đơn vị đếm là ĐIỂM DỪNG, không phải phiếu: năm phiếu cùng một nhà máy là một lần xe dừng.
"""

import logging
from collections import defaultdict

from ..tools.vtracking_blocking import blocking_flags
from ..tools.vtracking_channel import needs_company_truck
from . import plan_documents
from .vtracking_place_lookup import places_by_root_partner

_logger = logging.getLogger(__name__)


def candidates(env, plan):
    """Phiếu xếp được, gom theo cụm rồi theo điểm dừng.

    Trả ``(by_zone, skipped)``:

    * ``by_zone`` — ``{zone: {điểm giao: recordset phiếu}}``
    * ``skipped`` — ``{lý do: [tên phiếu]}`` để báo lại cho người bấm nút

    Đọc kho của chính kế hoạch (qua điểm xuất phát): phiếu của kho khác thì xe này không
    lấy được. Điểm xuất phát chưa gắn kho thì lấy phiếu của mọi kho — bên gọi phải chặn
    trước, xem ``action_autoload_documents``.
    """
    warehouse = plan.start_place_id.warehouse_id
    pickings = env['stock.picking'].search(
        plan_documents.loadable_picking_domain(warehouse)
    )
    places = places_by_root_partner(env, plan.company_id or env.company)

    by_zone = defaultdict(lambda: defaultdict(lambda: env['stock.picking']))
    skipped = defaultdict(list)
    for picking in pickings:
        order = picking.sale_id
        channel = order._vtracking_delivery_channel() if order else ''
        place = places.get(picking.partner_id.commercial_partner_id.id)
        flags = blocking_flags(place.profile_id.procedure_required if place else None,
                               channel or None,
                               procedure_ready=picking.vtracking_procedure_ready)
        hard = [flag for flag in flags if flag['hard']]
        if hard:
            skipped[hard[0]['label']].append(picking.name)
        elif not needs_company_truck(channel or None):
            skipped['Khách tự lấy / chuyển phát / Grab — xe công ty không phải chạy'].append(
                picking.name)
        elif not place or not place.zone_id:
            skipped['Khách chưa có điểm giao nên chưa biết thuộc cụm nào'].append(picking.name)
        else:
            by_zone[place.zone_id][place] |= picking
    return by_zone, skipped


def choose_zone(by_zone, plan):
    """Cụm sẽ xếp cho chuyến này.

    Kế hoạch đã có cụm (do người đặt, hoặc do các điểm đang có) thì giữ nguyên cụm đó —
    máy không được kéo chuyến sang vùng khác sau lưng người điều phối. Chưa có gì thì chọn
    cụm nhiều điểm nhất: chuyến đầy là chuyến đáng chạy.
    """
    if plan.zone_id:
        return plan.zone_id if plan.zone_id in by_zone else None
    if not by_zone:
        return None
    return max(by_zone, key=lambda zone: (len(by_zone[zone]), zone.id))


def drop_stale_lines(plan):
    """Gỡ các dòng không còn gì để giao: phiếu đã xuất xong hoặc đã huỷ. Trả về số dòng gỡ.

    Chỉ chạy trên bản NHÁP. Kế hoạch đã chốt thì tài xế đang cầm tờ đó đi, và dòng đã giao
    xong còn để đối chiếu kế hoạch với thực tế — sửa sau lưng họ là xoá mất dấu vết.
    """
    bo = plan.line_ids.filtered(lambda line: line.picking_id.state in ('done', 'cancel'))
    if not bo:
        return 0
    nhan = ', '.join(bo.mapped('display_reference'))
    plan.message_post(
        body='Đã gỡ %s dòng vì phiếu đã xuất xong hoặc đã huỷ: %s.' % (len(bo), nhan),
        message_type='notification',
    )
    count = len(bo)
    bo.unlink()
    return count


def autoload(plan):
    """Dọn rồi xếp lại ``plan`` theo dữ liệu MỚI NHẤT, rồi sắp thứ tự ghé.

    Một lần bấm làm trọn việc: gỡ những dòng không còn gì để giao, thêm phiếu mới kho vừa
    soạn xong, sắp lại thứ tự. Người điều phối không phải nhớ bấm mấy nút theo thứ tự nào.

    Dư trần thì xếp các điểm **tới hẹn sớm nhất** trước — phần còn lại nằm trong
    ``left_out`` để người điều phối mở chuyến khác.
    """
    plan.ensure_one()
    removed = drop_stale_lines(plan)
    by_zone, skipped = candidates(plan.env, plan)
    zone = choose_zone(by_zone, plan)
    if not zone:
        return {'zone': None, 'added': 0, 'removed': removed, 'stops': 0,
                'left_out': [], 'skipped': dict(skipped)}

    stops = sorted(
        by_zone[zone].items(),
        key=lambda item: min(item[1].mapped('scheduled_date') or [False]) or False,
    )
    con_trong = max((zone.max_stops or 0) - plan.stop_count, 0) if zone.max_stops else len(stops)
    chon, du = stops[:con_trong], stops[con_trong:]

    pickings = plan.env['stock.picking']
    for _place, group in chon:
        pickings |= group
    added = 0
    if pickings:
        added = len(plan_documents.add_documents(plan, pickings=pickings)['added_line_ids'])
        plan.action_resequence_by_distance()

    _logger.info('V-Tracking: nút lên kế hoạch xếp %s phiếu (%s điểm) cụm %s vào %s.',
                 added, len(chon), zone.name, plan.name)
    return {
        'zone': zone,
        'added': added,
        'removed': removed,
        'stops': len(chon),
        'left_out': [place.name for place, _group in du],
        'skipped': dict(skipped),
    }


def review_request(plan, summary):
    """Tạo phiếu yêu cầu để AI soát lại kế hoạch vừa xếp. Trả phiếu, hoặc recordset rỗng.

    Rỗng khi công ty chưa khai tài khoản worker AI: lúc đó không ai nhận phiếu, tạo ra chỉ
    để nằm đọng. Bên gọi phải nói rõ điều đó cho người bấm nút.
    """
    Request = plan.env['hlv.vtracking.ai.request']
    if not plan.company_id.sudo().ai_worker_user_id:
        return Request.browse()

    bo_qua = '; '.join('%s: %s phiếu' % (ly_do, len(phieu))
                       for ly_do, phieu in summary['skipped'].items())
    message = (
        'Máy vừa tự xếp %s phiếu vào %s điểm dừng của cụm %s. Nhờ soát lại: thứ tự ghé có '
        'hợp lý không, có điểm nào giờ tới vô lý vì toạ độ sai không, đơn nào trễ hẹn mà '
        'bị bỏ lại không, và có nên gom thêm điểm lẻ của cụm bên cạnh không.'
        % (summary['added'], summary['stops'], summary['zone'].name)
    )
    if summary['left_out']:
        message += ' Dư trần điểm nên để lại: %s.' % ', '.join(summary['left_out'])
    if bo_qua:
        message += ' Đã bỏ — %s.' % bo_qua
    return Request.create({
        'request_type': 'question',
        'plan_id': plan.id,
        'message': message,
        'company_id': plan.company_id.id,
        'review_round': 1,
    })
