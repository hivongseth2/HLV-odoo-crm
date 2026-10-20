# -*- coding: utf-8 -*-
"""
check_po_state_back_to_sent.py
==============================
Vì sao đơn mua đã xác nhận ("Đơn mua hàng") lại nhảy ngược về "RFQ đã gửi" dù form không có nút
nào để lùi? VD DMH24079 (20/10/2026): 08:13 RFQ → Đơn mua hàng, 08:15 Đơn mua hàng → RFQ đã gửi,
08:23 xác nhận lại — cả ba dòng đều do cùng một người dùng.

Dò code (core Odoo 18 + custom_addons) thì CHỈ MỘT chỗ ghi state='sent' mà không kiểm trạng thái hiện tại:
    purchase/models/purchase_order.py  print_quotation():  self.write({'state': "sent"})
Nút "In RFQ" (print_quotation, phím tắt Alt+K) chỉ hiện khi đơn còn nháp / RFQ đã gửi, nhưng nếu người dùng
còn MỞ form cũ ở tab khác (chưa tải lại, vẫn thấy đơn là RFQ) rồi bấm "In RFQ" thì server vẫn chạy và
kéo đơn đã xác nhận về 'sent'. Các đường khác (gửi mail RFQ: mark_rfq_as_sent) chỉ đổi đơn đang 'draft'.
Ghi chú: in qua menu bánh răng "In → Yêu cầu báo giá" thì KHÔNG đổi state (gọi thẳng report).

Script in ra để xác nhận / loại trừ:
  A. Thông tin đơn + mốc trạng thái (mail.tracking.value của field state), lần lùi được đánh dấu <<<.
  B. Quanh mỗi lần lùi (±WINDOW_SEC giây): mọi message / tracking / file đính kèm / mail / phiếu kho /
     đề nghị sửa của NCC / thay đổi trạng thái MISA — cái gì xảy ra cùng lúc. Lần lùi mà message chỉ có
     đúng một tracking 'state' và không kèm gì khác là dấu vân tay của print_quotation.
  C. Code: mọi lớp đang định nghĩa print_quotation / write / button_draft / action_rfq_send / message_post
     trên purchase.order (dấu * = không phải core), và kiểm print_quotation core còn ghi state vô điều kiện.
  D. View form purchase.order thực tế (đã gộp Studio / module): nút print_quotation hiện khi nào.
  E. Automation rule / server action trên purchase.order có đụng tới state.
  F. Quét SCAN_DAYS ngày: các đơn khác cũng lùi từ đã xác nhận về RFQ — ai, cách lần xác nhận bao lâu.

CHỈ ĐỌC — không write/create/unlink gì.
Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_po_state_back_to_sent.py
"""
import inspect
import logging
import warnings
from datetime import timedelta

import pytz
from lxml import etree

# get_views dựng lại registry trigger → in hàng loạt UserWarning "should be searchable" kèm stack, che mất kết quả.
warnings.filterwarnings('ignore')
logging.getLogger('py.warnings').setLevel(logging.ERROR)

ORDERS = ['DMH24079']
SCAN_DAYS = 30
WINDOW_SEC = 90
TZ = pytz.timezone('Asia/Ho_Chi_Minh')
SEP = "=" * 100
SUB = "-" * 100

CONFIRMED = ('purchase', 'done')
RFQ = ('draft', 'sent', 'to approve')
PO_METHODS = ['print_quotation', 'write', 'button_draft', 'action_rfq_send', 'message_post',
              'button_confirm', 'button_approve', 'button_unlock']


def local(dt):
    if not dt:
        return '-'
    return pytz.utc.localize(dt).astimezone(TZ).strftime('%d/%m/%Y %H:%M:%S')


def owner_file(cls):
    try:
        return inspect.getsourcefile(cls) or '?'
    except TypeError:
        return '?'


def is_custom(path):
    """Odoo.sh để repo nhà ở /src/user/, máy tự dựng thì ở custom_addons/."""
    norm = path.replace(chr(92), '/')
    return 'custom_addons' in norm or '/src/user/' in norm


def state_label_map():
    """Nhãn → mã state. Tracking lưu NHÃN theo ngôn ngữ của người thao tác, nên gom mọi ngôn ngữ đang bật."""
    field = env['purchase.order']._fields['state']
    mapping = {}
    for lang, _name in env['res.lang'].get_installed():
        for key, label in field._description_selection(env(context={'lang': lang})):
            mapping[label] = key
    for key, _label in field.selection:
        mapping[key] = key
    return mapping


LABELS = state_label_map()
STATE_FIELD = env['ir.model.fields']._get('purchase.order', 'state')


def state_trackings(domain_extra):
    return env['mail.tracking.value'].sudo().search([
        ('field_id', '=', STATE_FIELD.id),
        ('mail_message_id.model', '=', 'purchase.order'),
    ] + domain_extra, order='id')


def as_steps(trackings):
    """[(tracking, old_key, new_key)] — key None nếu nhãn lạ (đổi tên selection sau này)."""
    return [(t, LABELS.get(t.old_value_char), LABELS.get(t.new_value_char)) for t in trackings]


def is_backward(old, new):
    return old in CONFIRMED and new in RFQ


def who(message):
    user = message.create_uid
    return f"author={message.author_id.name or '-'} | create_uid={user.login or '-'} (id={user.id})"


# ─────────────────────────────────────────────────────────────────────────────
def section_timeline(po):
    print(f"\n{SEP}\n  A. {po.name} (id={po.id})\n{SEP}")
    print(f"  state hiện tại   : {po.state}")
    print(f"  date_approve     : {local(po.date_approve)}")
    print(f"  tạo              : {local(po.create_date)} bởi {po.create_uid.login}")
    print(f"  sửa cuối         : {local(po.write_date)} bởi {po.write_uid.login}")
    if 'misa_purchase_order_state' in po._fields:
        print(f"  MISA state       : {po.misa_purchase_order_state} "
              f"(đổi lúc {local(po.misa_purchase_order_state_updated_at)})")
    steps = as_steps(state_trackings([('mail_message_id.res_id', '=', po.id)]))
    print(f"\n  Mốc trạng thái ({len(steps)}):")
    backs = []
    for t, old, new in steps:
        msg = t.mail_message_id
        mark = '  <<< LÙI' if is_backward(old, new) else ''
        print(f"    {local(msg.date)}  {t.old_value_char!s:>18} → {t.new_value_char!s:<18} "
              f"msg={msg.id}  {who(msg)}{mark}")
        if is_backward(old, new):
            backs.append(t)
    if not backs:
        print("  (không thấy lần lùi nào trong tracking)")
    return backs


def print_message(msg, indent="      "):
    body = (msg.body or '').replace('\n', ' ')
    body = etree.HTML(body).xpath('string()') if body.strip() else ''
    print(f"{indent}msg {msg.id}  {local(msg.date)}  type={msg.message_type}  "
          f"subtype={msg.subtype_id.name or '-'}  {who(msg)}")
    if body:
        print(f"{indent}  body: {body[:160]}")
    for tv in msg.sudo().tracking_value_ids:
        print(f"{indent}  • {tv.field_id.name}: {tv.old_value_char or tv.old_value_integer or tv.old_value_float or ''}"
              f" → {tv.new_value_char or tv.new_value_integer or tv.new_value_float or ''}")
    for att in msg.attachment_ids:
        print(f"{indent}  📎 {att.name}")


def section_around(po, back):
    msg = back.mail_message_id
    start, end = msg.date - timedelta(seconds=WINDOW_SEC), msg.date + timedelta(seconds=WINDOW_SEC)
    window = [('create_date', '>=', start), ('create_date', '<=', end)]
    print(f"\n{SEP}\n  B. QUANH LẦN LÙI {local(msg.date)} (±{WINDOW_SEC}s) — msg {msg.id}\n{SEP}")

    only_state = len(msg.sudo().tracking_value_ids) == 1 and not msg.body and not msg.attachment_ids
    print(f"  Message lùi chỉ có đúng tracking state, không body/file: {'CÓ' if only_state else 'KHÔNG'}"
          + ("  → khớp print_quotation (write mỗi state)" if only_state else ""))

    print(f"\n  {SUB}\n  Message trên đơn trong cửa sổ\n  {SUB}")
    msgs = env['mail.message'].sudo().search([
        ('model', '=', 'purchase.order'), ('res_id', '=', po.id),
        ('date', '>=', start), ('date', '<=', end)], order='date, id')
    for m in msgs:
        print_message(m)

    print(f"\n  {SUB}\n  File đính kèm tạo trên đơn (report có lưu file sẽ hiện ở đây)\n  {SUB}")
    atts = env['ir.attachment'].sudo().search([('res_model', '=', 'purchase.order'), ('res_id', '=', po.id)] + window)
    for a in atts:
        print(f"      {local(a.create_date)}  {a.name}  bởi {a.create_uid.login}")
    if not atts:
        print("      (không có — report RFQ mặc định không lưu file, nên vắng file KHÔNG loại trừ việc bấm In)")

    print(f"\n  {SUB}\n  Mail gửi đi từ đơn\n  {SUB}")
    mails = env['mail.mail'].sudo().search([('model', '=', 'purchase.order'), ('res_id', '=', po.id)] + window)
    for m in mails:
        print(f"      {local(m.create_date)}  state={m.state}  to={m.email_to or m.recipient_ids.mapped('email')}"
              f"  subject={m.subject}")
    if not mails:
        print("      (không có)")

    print(f"\n  {SUB}\n  Phiếu kho của đơn\n  {SUB}")
    for p in po.sudo().picking_ids:
        print(f"      {p.name}  state={p.state}  tạo {local(p.create_date)}  sửa {local(p.write_date)}")

    if 'hlv.po.revision' in env:
        revs = env['hlv.po.revision'].sudo().search([('purchase_order_id', '=', po.id)])
        print(f"\n  {SUB}\n  Đề nghị sửa đơn của NCC (hlv.po.revision): {len(revs)}\n  {SUB}")
        for r in revs:
            print(f"      #{r.number} state={r.state} tạo {local(r.create_date)} sửa {local(r.write_date)}")

    print(f"\n  {SUB}\n  Phiên đăng nhập của người thao tác (res.users.log) trong ngày\n  {SUB}")
    local_midnight = pytz.utc.localize(msg.date).astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    day = local_midnight.astimezone(pytz.utc).replace(tzinfo=None)
    logs = env['res.users.log'].sudo().search([
        ('create_uid', '=', msg.create_uid.id),
        ('create_date', '>=', day), ('create_date', '<', day + timedelta(days=1))], order='id')
    print("      " + (", ".join(local(log.create_date)[11:] for log in logs) or "(không có)"))


def section_code():
    print(f"\n{SEP}\n  C. CODE TRÊN purchase.order (dấu * = không phải core Odoo)\n{SEP}")
    model_cls = type(env['purchase.order'])
    for method in PO_METHODS:
        owners = [c for c in model_cls.__mro__ if method in c.__dict__ and c.__module__.startswith('odoo.addons.')]
        tag = '  <<< CUSTOM' if any(is_custom(owner_file(c)) for c in owners) else ''
        print(f"    {method}{tag}")
        for c in owners:
            mark = '    * ' if is_custom(owner_file(c)) else '      '
            print(f"{mark}{c.__module__}  ({owner_file(c)})")
    core = next((c for c in reversed(model_cls.__mro__)
                 if 'print_quotation' in c.__dict__ and c.__module__.startswith('odoo.addons.purchase.')), None)
    if core:
        src = inspect.getsource(core.__dict__['print_quotation'])
        print("\n  print_quotation core:")
        for line in src.strip().splitlines():
            print(f"      {line}")
        if "'state'" in src and 'filtered' not in src:
            print("  → GHI state='sent' VÔ ĐIỀU KIỆN: đơn đã xác nhận mà bị gọi hàm này là lùi về RFQ đã gửi.")


def section_view():
    print(f"\n{SEP}\n  D. NÚT print_quotation TRONG FORM ĐƠN MUA (arch đã gộp)\n{SEP}")
    arch = env['purchase.order'].get_views([(False, 'form')])['views']['form']['arch']
    root = etree.fromstring(arch.encode())
    buttons = root.xpath("//button[@name='print_quotation']")
    for b in buttons:
        print(f"    string={b.get('string')!r}  invisible={b.get('invisible')!r}  hotkey={b.get('data-hotkey')!r}")
    if not buttons:
        print("    (không có nút)")
    other = root.xpath("//button[@type='object'][contains(@name,'draft') or contains(@name,'rfq')]")
    for b in other:
        print(f"    khác: name={b.get('name')} string={b.get('string')!r} invisible={b.get('invisible')!r}")
    print("  Nếu mọi invisible đều chặn khi state='purchase' thì đường còn lại là form CŨ ở tab khác "
          "(vẫn hiển thị RFQ) — bấm In RFQ / Alt+K ở đó.")


def section_automation():
    print(f"\n{SEP}\n  E. AUTOMATION / SERVER ACTION TRÊN purchase.order\n{SEP}")
    found = False
    if 'base.automation' in env:
        for rule in env['base.automation'].sudo().search([('model_id.model', '=', 'purchase.order')]):
            found = True
            codes = ' | '.join((a.code or '')[:200].replace('\n', ' ') for a in rule.action_server_ids)
            print(f"    [rule] {rule.name}  active={rule.active}  trigger={rule.trigger}  code={codes or '-'}")
    actions = env['ir.actions.server'].sudo().search([
        ('model_id.model', '=', 'purchase.order'), ('state', 'in', ('code', 'object_write'))])
    for act in actions:
        code = act.code or ''
        fields_written = act.update_field_id.name if 'update_field_id' in act._fields else ''
        if 'state' in code or fields_written == 'state' or 'print_quotation' in code:
            found = True
            print(f"    [action] {act.name} (id={act.id}) type={act.state} field={fields_written or '-'}"
                  f"  code={code[:200].replace(chr(10), ' ')}")
    if not found:
        print("    (không có cái nào đụng tới state)")


def section_scan():
    print(f"\n{SEP}\n  F. {SCAN_DAYS} NGÀY GẦN ĐÂY: ĐƠN KHÁC CŨNG LÙI TỪ ĐÃ XÁC NHẬN VỀ RFQ\n{SEP}")
    since = env.cr.now() - timedelta(days=SCAN_DAYS)
    steps = as_steps(state_trackings([('create_date', '>=', since)]))
    backs = [(t, old, new) for t, old, new in steps if is_backward(old, new)]
    by_user = {}
    for t, _old, new in backs:
        msg = t.mail_message_id
        po = env['purchase.order'].sudo().browse(msg.res_id)
        confirm = env['mail.tracking.value'].sudo().search([
            ('field_id', '=', STATE_FIELD.id), ('mail_message_id.model', '=', 'purchase.order'),
            ('mail_message_id.res_id', '=', po.id), ('id', '<', t.id)], order='id desc', limit=1)
        gap = (msg.date - confirm.mail_message_id.date).total_seconds() / 60 if confirm else None
        gap_txt = f"{gap:.1f} phút sau lần đổi trước" if gap is not None else "-"
        print(f"    {po.name:<12} {local(msg.date)}  → {new:<10} {gap_txt:<26} {msg.create_uid.login}"
              f"  hiện tại={po.state}")
        by_user[msg.create_uid.login] = by_user.get(msg.create_uid.login, 0) + 1
    print(f"\n  Tổng {len(backs)} lần lùi.  Theo người: {by_user or '-'}")
    if backs and all(new == 'sent' for _t, _o, new in backs):
        print("  Mọi lần lùi đều về đúng 'sent' (không phải 'draft') — khớp print_quotation, "
              "không phải button_draft (Đặt về nháp).")


for name in ORDERS:
    order = env['purchase.order'].sudo().search([('name', '=', name)], limit=1)
    if not order:
        print(f"\n  ❌ Không thấy đơn mua {name}")
        continue
    for back_step in section_timeline(order):
        section_around(order, back_step)
section_code()
section_view()
section_automation()
section_scan()
print(f"\n{SEP}\n  XONG (chỉ đọc)\n{SEP}")
