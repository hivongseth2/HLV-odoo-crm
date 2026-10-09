# -*- coding: utf-8 -*-
"""
check_po_qty_zero_return_out.py
===============================
Vì sao sửa SL dòng đơn mua về 0 (chưa nhận hàng) lại đẻ ra phiếu XUẤT/TRẢ NCC cho các mặt hàng
chưa nhận (VD DMH23661 — M18 BLPDRC-0C0, M18 FIW212-0X0: 15 → 0)?

Cơ chế core Odoo 18 (purchase_stock + stock):
  1. purchase.order.line.write(product_qty) → _create_or_update_picking() → _prepare_stock_moves()
     tạo một move ÂM = SL mới − SL đã có trên move (0 − 15 = −15), gắn vào phiếu nhập đang mở
     đầu tiên của dòng.
  2. stock.move._action_confirm() → _merge_moves(): move âm chỉ được "trừ" vào move nhận cũ khi
     KHỚP KHOÁ GỘP (product, price_unit, location, date_deadline, description_picking,
     propagate_cancel, packaging, purchase_line_id, … + trường custom module thêm vào), và chỉ
     tìm trong ĐÚNG phiếu nhập được chọn ở bước 1.
  3. Phần âm còn lại (không khớp khoá / move nhận trong phiếu đó nhỏ hơn SL giảm) bị ĐẢO thành
     move trả hàng: đổi chiều kho → NCC, picking_type = return_picking_type_id của loại phiếu nhập
     (mặc định là loại Phiếu xuất OUT) → _assign_picking() tạo phiếu mới. Đó là "phiếu out".

Script in ra:
  A. Cấu hình ảnh hưởng khoá gộp (ir.config_parameter) + danh sách trường khoá thực tế.
  B. Mọi lớp Python (core + custom) đang override các hàm trong luồng trên.
  C. Automation rule (base.automation) đang bật trên PO / dòng PO / move / phiếu.
  D. Loại phiếu nhập của đơn: return_picking_type_id, số bước nhận, push rule ở kho nhận.
  E. Từng dòng của các đơn trong ORDERS: mọi move, và với mỗi move "trả do SL âm" — so khoá gộp
     với các move nhận của cùng dòng, chỉ ra trường lệch / dòng bị tách nhiều phiếu.
  F. Quét SCAN_DAYS ngày gần nhất: các đơn mua khác có move "trả do SL âm" (mức độ lan rộng).
  G. Module hlv_purchase_qty_decrease: đã cài chưa, cài lúc nào (so với giờ tạo phiếu trả), override
     có nằm trong chuỗi gọi không. Ở E, mỗi trường lệch được ghi chú module có chép trường đó vào
     move âm hay bỏ qua — trường lệch mà module bỏ qua là lý do module không chặn được.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_po_qty_zero_return_out.py
"""
import inspect
from datetime import timedelta

import pytz

from odoo import fields
from odoo.tools import float_round

ORDERS = ['DMH23712']
FIX_MODULE = 'hlv_purchase_qty_decrease'
SCAN_DAYS = 60
ORDER_SHOW_ALL_LINES = False  # True để in cả dòng không có move trả
TZ = pytz.timezone('Asia/Ho_Chi_Minh')
SEP = "=" * 100
SUB = "-" * 100

PO_LINE_METHODS = [
    'write', '_create_or_update_picking', '_create_stock_moves', '_prepare_stock_moves',
    '_prepare_stock_move_vals', '_get_qty_procurement', '_get_outgoing_incoming_moves',
    '_get_stock_move_price_unit', '_update_move_date_deadline',
]
MOVE_METHODS = [
    'create', 'write', '_action_confirm', '_merge_moves', '_update_candidate_moves_list',
    '_prepare_merge_moves_distinct_fields', '_prepare_merge_negative_moves_excluded_distinct_fields',
    '_merge_move_itemgetter', '_assign_picking', '_push_apply', '_search_picking_for_assignation',
]
PICKING_METHODS = ['create', 'write', '_create_backorder']
CONFIG_KEYS = [
    'stock.merge_ignore_date_deadline',
    'stock.merge_only_same_date',
    'purchase_stock.merge_different_procurement',
]
# Bị _action_confirm ghi đè khi đảo move âm thành move trả nên không so được.
UNRECOVERABLE_KEYS = {'location_final_id', 'procure_method'}


def local(dt):
    if not dt:
        return '-'
    return pytz.utc.localize(dt).astimezone(TZ).strftime('%d/%m/%Y %H:%M:%S')


def fmt_value(value):
    if hasattr(value, '_name'):
        return ','.join(value.mapped('display_name')) if value else 'False'
    return repr(value)


def owner_file(cls):
    try:
        return inspect.getsourcefile(cls) or '?'
    except TypeError:
        return '?'


def is_custom(path):
    """Odoo.sh để repo nhà ở /src/user/, máy tự dựng thì ở custom_addons/."""
    norm = path.replace(chr(92), '/')
    return 'custom_addons' in norm or '/src/user/' in norm


def print_overrides(model_name, methods):
    print(f"\n  {model_name}")
    model_cls = type(env[model_name])
    for method in methods:
        owners = [c for c in model_cls.__mro__ if method in c.__dict__ and c.__module__.startswith('odoo.addons.')]
        if not owners:
            continue
        custom = [c for c in owners if is_custom(owner_file(c))]
        tag = '  <<< CUSTOM' if custom else ''
        print(f"    {method}{tag}")
        for c in owners:
            mark = '    * ' if is_custom(owner_file(c)) else '      '
            print(f"{mark}{c.__module__}  ({owner_file(c)})")


def section_config():
    print(f"\n{SEP}\n  A. CẤU HÌNH KHOÁ GỘP MOVE\n{SEP}")
    icp = env['ir.config_parameter'].sudo()
    for key in CONFIG_KEYS:
        print(f"  {key:<45} = {icp.get_param(key)!r}")
    Move = env['stock.move']
    distinct = Move._prepare_merge_moves_distinct_fields()
    excluded = Move._prepare_merge_negative_moves_excluded_distinct_fields()
    neg_key = [f for f in distinct if f not in excluded]
    print(f"\n  Trường khoá gộp (move dương):       {distinct}")
    print(f"  Bỏ qua khi trừ move âm:             {excluded}")
    print(f"  => Khoá để move âm trừ vào move cũ: {neg_key}")
    if 'date_deadline' in neg_key:
        print("  ! date_deadline nằm trong khoá: move nhận cũ có hạn khác date_planned hiện tại của dòng"
              " là move âm KHÔNG trừ được → thành phiếu trả.")
    return neg_key


def section_overrides():
    print(f"\n{SEP}\n  B. CODE OVERRIDE TRONG LUỒNG (dấu * = không phải core Odoo)\n{SEP}")
    print_overrides('purchase.order.line', PO_LINE_METHODS)
    print_overrides('stock.move', MOVE_METHODS)
    print_overrides('stock.picking', PICKING_METHODS)


def section_automations():
    print(f"\n{SEP}\n  C. AUTOMATION RULE ĐANG BẬT\n{SEP}")
    if 'base.automation' not in env:
        print("  (base_automation chưa cài)")
        return
    models = ['purchase.order', 'purchase.order.line', 'stock.move', 'stock.picking']
    rules = env['base.automation'].sudo().search([('model_id.model', 'in', models), ('active', '=', True)])
    if not rules:
        print("  Không có.")
    for rule in rules:
        print(f"  [{rule.id}] {rule.name} | model {rule.model_id.model} | trigger {rule.trigger}"
              f" | trường {rule.trigger_field_ids.mapped('name')}")
        for action in rule.action_server_ids:
            print(f"      → action [{action.id}] {action.name} ({action.state})")
            if action.state == 'code' and action.code:
                for code_line in action.code.strip().splitlines()[:15]:
                    print(f"          | {code_line}")


def section_picking_type(order):
    ptype = order.picking_type_id
    ret = ptype.return_picking_type_id
    wh = ptype.warehouse_id
    print(f"\n  Loại phiếu nhập: [{ptype.id}] {ptype.display_name} (code {ptype.code}, prefix {ptype.sequence_code})")
    print(f"  Loại phiếu trả (return_picking_type_id): "
          f"{f'[{ret.id}] {ret.display_name} (code {ret.code}, prefix {ret.sequence_code})' if ret else 'KHÔNG CÓ'}")
    if wh:
        print(f"  Kho {wh.name}: reception_steps = {wh.reception_steps}")
    dest = ptype.default_location_dest_id
    push = env['stock.rule'].sudo().search([('action', 'in', ('push', 'pull_push')), ('location_src_id', '=', dest.id)])
    for rule in push:
        print(f"  Push rule từ {dest.display_name}: [{rule.id}] {rule.name} → {rule.location_dest_id.display_name}"
              f" (route {rule.route_id.name})")


def is_negative_return(move):
    """Move trả do SL âm: thuộc dòng PO, đi về NCC, không sinh từ wizard trả hàng."""
    return bool(move.purchase_line_id and move.location_dest_id.usage == 'supplier'
                and not move.origin_returned_move_id)


def origin_value(move, fname, as_negative_origin=False):
    """Giá trị trường của move; với move trả do SL âm thì dựng lại chiều kho trước khi bị đảo."""
    if as_negative_origin and fname == 'location_id':
        return move.location_dest_id
    if as_negative_origin and fname == 'location_dest_id':
        return move.location_id
    return move[fname]


def key_of(move, fname, value, price_digits):
    """Chuẩn hoá giá trị như _merge_move_itemgetter: float làm tròn thành chuỗi, quan hệ thành id."""
    field = move._fields[fname]
    if field.type == 'float':
        digits = price_digits if fname == 'price_unit' else (field.get_digits(env) or (False, 2))[1]
        return "{:.{p}f}".format(float_round(value, precision_digits=digits), p=digits)
    if field.type in ('many2one', 'many2many', 'one2many'):
        return tuple(sorted(value.ids))
    return value


def price_precision(move):
    prec = env['decimal.precision'].precision_get('Product Price')
    return min(move.company_id.currency_id.decimal_places, prec) if move.company_id else prec


def print_move(move):
    pick = move.picking_id
    code = move.picking_type_id.code or '-'
    flag = '  <<< TRẢ DO SL ÂM' if is_negative_return(move) else ''
    print(f"    move {move.id:<7} {pick.name or '(không phiếu)':<22} {code:<9} {move.state:<10}"
          f" {move.location_id.display_name} → {move.location_dest_id.display_name}"
          f" | yêu cầu {move.product_uom_qty:g} | thực {move.quantity:g}{flag}")
    print(f"           giá {move.price_unit:,.2f} | hạn {local(move.date_deadline)} | date {local(move.date)}"
          f" | tạo {local(move.create_date)} bởi {move.create_uid.name}"
          f" | phiếu tạo {local(pick.create_date) if pick else '-'}")


def diagnose_return(ret_move, line, neg_key):
    price_digits = price_precision(ret_move)
    comparable = [f for f in neg_key if f not in UNRECOVERABLE_KEYS and f in ret_move._fields]
    receipts = line.move_ids.filtered(lambda m: m != ret_move and not is_negative_return(m)
                                      and m.location_dest_id.usage != 'supplier')
    print(f"\n    >> Chẩn đoán move trả {ret_move.id} ({ret_move.picking_id.name}):")
    if not receipts:
        print("       Dòng không còn move nhận nào để so.")
        return
    for rec in receipts:
        copied = set(rec._negative_merge_key_vals()) if hasattr(rec, '_negative_merge_key_vals') else None
        diffs = []
        for fname in comparable:
            neg_val = origin_value(ret_move, fname, as_negative_origin=True)
            rec_val = rec[fname]
            if key_of(ret_move, fname, neg_val, price_digits) != key_of(rec, fname, rec_val, price_digits):
                diffs.append(f"{fname}: move âm {fmt_value(neg_val)} ≠ move nhận {fmt_value(rec_val)}"
                             f"{fix_module_note(fname, copied)}")
        head = f"       vs move nhận {rec.id} ({rec.picking_id.name}, {rec.state}, SL {rec.product_uom_qty:g})"
        if diffs:
            print(f"{head}: LỆCH KHOÁ → không trừ được")
            for d in diffs:
                print(f"          - {d}")
        else:
            print(f"{head}: khớp khoá (so được {len(comparable)} trường; không so {sorted(UNRECOVERABLE_KEYS)})")
    open_pickings = receipts.filtered(lambda m: m.state not in ('done', 'cancel')).picking_id
    if len(open_pickings) > 1:
        print(f"       ! Dòng có move nhận mở ở {len(open_pickings)} phiếu {open_pickings.mapped('name')} —"
              " Odoo chỉ trừ trong phiếu đầu tiên, phần còn lại thành phiếu trả.")
    if receipts.filtered(lambda m: m.state == 'cancel' and not m.product_uom_qty):
        print("       ! Có move nhận bị trừ về 0 rồi hủy: move âm lớn hơn move nhận trong phiếu được chọn"
              " → phần dư bị đảo thành phiếu trả.")


def fix_module_note(fname, copied):
    if copied is None:
        return f"  [{FIX_MODULE} chưa nạp]"
    return f"  [{FIX_MODULE} CÓ chép]" if fname in copied else f"  [{FIX_MODULE} BỎ QUA trường này]"


def section_order(order, neg_key):
    print(f"\n{SEP}\n  E. {order.name} — {order.partner_id.display_name} | {order.state} | tạo {local(order.create_date)}\n{SEP}")
    section_picking_type(order)
    for pick in order.picking_ids.sorted('id'):
        print(f"  Phiếu {pick.name:<16} {pick.picking_type_id.code:<9} {pick.state:<10} → {pick.location_dest_id.display_name}"
              f" | tạo {local(pick.create_date)}")
    for line in order.order_line.filtered(lambda l: l.product_id.type == 'consu'):
        moves = line.move_ids.sorted('id')
        returns = moves.filtered(is_negative_return)
        if not returns and not ORDER_SHOW_ALL_LINES:
            continue
        print(f"\n  {SUB}\n  Dòng {line.id} [{line.product_id.default_code}] {line.product_id.name}"
              f" | SL {line.product_qty:g} | đã nhận {line.qty_received:g} | giá {line.price_unit:,.0f}"
              f" | date_planned {local(line.date_planned)}")
        for move in moves:
            print_move(move)
        for ret_move in returns:
            diagnose_return(ret_move, line, neg_key)


def section_scan():
    print(f"\n{SEP}\n  F. QUÉT {SCAN_DAYS} NGÀY: MOVE TRẢ DO SL ÂM TRÊN CÁC ĐƠN MUA\n{SEP}")
    since = fields.Datetime.now() - timedelta(days=SCAN_DAYS)
    moves = env['stock.move'].sudo().search([
        ('purchase_line_id', '!=', False),
        ('location_dest_id.usage', '=', 'supplier'),
        ('origin_returned_move_id', '=', False),
        ('create_date', '>=', since),
    ])
    by_order = {}
    for move in moves:
        by_order.setdefault(move.purchase_line_id.order_id, env['stock.move'])
        by_order[move.purchase_line_id.order_id] |= move
    if not by_order:
        print("  Không có.")
    for order, order_moves in sorted(by_order.items(), key=lambda kv: kv[0].name):
        states = sorted(set(order_moves.mapped('state')))
        print(f"  {order.name:<12} {len(order_moves):>3} move | phiếu {sorted(set(order_moves.picking_id.mapped('name')))}"
              f" | trạng thái {states}")


def section_fix_module():
    print(f"\n{SEP}\n  G. MODULE {FIX_MODULE}\n{SEP}")
    mod = env['ir.module.module'].sudo().search([('name', '=', FIX_MODULE)])
    if not mod:
        print("  Không thấy module trong danh sách ứng dụng (chưa deploy / chưa cập nhật danh sách).")
        return
    print(f"  Trạng thái {mod.state} | phiên bản DB {mod.latest_version} | sửa lần cuối {local(mod.write_date)}"
          " (≈ lúc cài/nâng cấp; phiếu trả tạo TRƯỚC giờ này thì module chưa kịp chạy)")
    print_overrides('purchase.order.line', ['_prepare_stock_move_vals', '_open_receipt_move'])
    print_overrides('stock.move', ['_negative_merge_key_vals'])


neg_key_fields = section_config()
section_overrides()
section_automations()
for po in env['purchase.order'].sudo().search([('name', 'in', ORDERS)]):
    section_order(po, neg_key_fields)
section_scan()
section_fix_module()
env.cr.rollback()
