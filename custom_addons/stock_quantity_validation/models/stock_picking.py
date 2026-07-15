# -*- coding: utf-8 -*-
import logging
from collections import defaultdict

from markupsafe import Markup, escape

from odoo import SUPERUSER_ID, models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)


def _quant_quantities_by_keys(env, keys):
    keys = set(keys)
    quantities = {key: 0.0 for key in keys}
    if not keys:
        return quantities

    product_ids = {key[0] for key in keys}
    location_ids = {key[1] for key in keys}
    quants = env['stock.quant'].sudo().search([
        ('product_id', 'in', list(product_ids)),
        ('location_id', 'in', list(location_ids)),
    ])
    for quant in quants:
        key = (
            quant.product_id.id,
            quant.location_id.id,
            quant.lot_id.id or False,
            quant.package_id.id or False,
            quant.owner_id.id or False,
            quant.company_id.id or False,
        )
        if key in quantities:
            quantities[key] += quant.quantity
    return quantities


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _check_qty_validation_before_validate(self):
        """
        Kiểm tra quantity không được vượt quá product_uom_qty trên picking.
        Bỏ qua phiếu chuyển hàng nội bộ (có 'INT' trong tên) vì demand luôn = 0.
        """
        self.ensure_one()

        # Bỏ qua phiếu chuyển hàng nội bộ (có 'INT' trong tên)
        if self.name and 'INT' in self.name:
            return

        # Danh sách các move vi phạm (qty_done > product_uom_qty)
        violations = []

        # Kiểm tra từng move trong picking
        for move in self.move_ids_without_package:
            # Bỏ qua các move đã done hoặc đã cancel
            if move.state in ('done', 'cancel'):
                continue

            # Lấy số lượng đã đặt (demand) và số lượng thực tế (done)
            qty_demand = float(move.product_uom_qty or 0.0)
            qty_done = float(move.quantity or 0.0)

            # Sử dụng epsilon để xử lý sai số floating point
            EPS = 1e-6

            # Nếu qty_done vượt quá qty_demand
            if qty_done > qty_demand + EPS:
                product_name = move.product_id.display_name or move.product_id.name or _("Sản phẩm không xác định")
                uom_name = move.product_uom.name if move.product_uom else ''

                violations.append({
                    'product': product_name,
                    'demand': qty_demand,
                    'done': qty_done,
                    'uom': uom_name,
                    'move_id': move.id,
                })

                _logger.warning(
                    "⚠️ Picking %s: Move %s (%s) có qty_done (%.2f) > product_uom_qty (%.2f)",
                    self.name, move.id, product_name, qty_done, qty_demand
                )

        # Nếu có vi phạm, chặn xác nhận và hiển thị thông báo lỗi
        if violations:
            error_lines = []
            for v in violations:
                error_lines.append(
                    _("• %s: Đã làm %.2f %s (vượt quá %.2f %s đã đặt)") % (
                        v['product'],
                        v['done'],
                        v['uom'],
                        v['demand'],
                        v['uom']
                    )
                )

            error_message = _(
                "Không thể xác nhận phiếu %s!\n\n"
                "Số lượng thực tế (Done) không được vượt quá số lượng đã đặt (Demand):\n\n"
                "%s\n\n"
                "Vui lòng điều chỉnh số lượng trước khi xác nhận."
            ) % (self.name, "\n".join(error_lines))

            _logger.error("🚫 CHẶN XÁC NHẬN picking %s do vi phạm qty_done > product_uom_qty", self.name)

            raise UserError(error_message)

        _logger.info("✅ Picking %s: Tất cả qty_done đều hợp lệ", self.name)

    def _hlv_quant_delta_guard_enabled(self):
        if self.env.context.get('skip_quant_delta_guard') or self.env.context.get('hlv_skip_quant_delta_guard'):
            return False
        value = self.env['ir.config_parameter'].sudo().get_param(
            'stock_quantity_validation.validate_quant_delta_guard',
            'True',
        )
        return str(value).lower() not in ('0', 'false', 'no', 'off')

    def _hlv_stock_quant_product(self, product):
        if not product:
            return False
        if 'is_storable' in product._fields:
            return bool(product.is_storable)
        return (product.type or '') == 'product'

    def _hlv_move_line_qty_for_quant_delta(self, move_line):
        values = []
        for field_name in ('quantity', 'qty_done'):
            if field_name in move_line._fields:
                values.append(float(getattr(move_line, field_name) or 0.0))
        return max(values) if values else 0.0

    def _hlv_quant_delta_key(self, move_line, location, package):
        company = move_line.company_id or move_line.picking_id.company_id
        return (
            move_line.product_id.id,
            location.id,
            move_line.lot_id.id or False,
            package.id if package else False,
            move_line.owner_id.id or False,
            company.id if company else False,
        )

    def _hlv_collect_validate_quant_deltas_by_picking(self):
        deltas_by_picking = {}
        samples = {}
        quant_usages = ('internal', 'transit')
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue
            picking_deltas = defaultdict(float)
            for move_line in picking.move_line_ids:
                if move_line.state in ('done', 'cancel'):
                    continue
                if not self._hlv_stock_quant_product(move_line.product_id):
                    continue
                line_qty = self._hlv_move_line_qty_for_quant_delta(move_line)
                if line_qty <= 0:
                    continue

                uom = move_line.product_uom_id or move_line.product_id.uom_id
                product_qty = uom._compute_quantity(line_qty, move_line.product_id.uom_id)
                if move_line.location_id.usage in quant_usages:
                    key = self._hlv_quant_delta_key(move_line, move_line.location_id, move_line.package_id)
                    picking_deltas[key] -= product_qty
                    samples.setdefault(key, move_line)
                if move_line.location_dest_id.usage in quant_usages:
                    key = self._hlv_quant_delta_key(move_line, move_line.location_dest_id, move_line.result_package_id)
                    picking_deltas[key] += product_qty
                    samples.setdefault(key, move_line)
            deltas_by_picking[picking.id] = dict(picking_deltas)
        return deltas_by_picking, samples

    def _hlv_merge_quant_deltas(self, deltas_by_picking, picking_ids=None):
        merged = defaultdict(float)
        picking_ids = set(picking_ids) if picking_ids is not None else None
        for picking_id, picking_deltas in deltas_by_picking.items():
            if picking_ids is not None and picking_id not in picking_ids:
                continue
            for key, delta in picking_deltas.items():
                merged[key] += delta
        return {key: delta for key, delta in merged.items() if abs(delta) > 1e-12}

    def _hlv_quant_lock_name(self, key):
        product_id, location_id, lot_id, package_id, owner_id, company_id = key
        return 'hlv_validate_quant:%s:%s:%s:%s:%s:%s' % (
            company_id or 0,
            product_id or 0,
            location_id or 0,
            lot_id or 0,
            package_id or 0,
            owner_id or 0,
        )

    def _hlv_lock_validate_quant_flow(self, keys):
        if not keys:
            return

        if self.ids:
            self.env.cr.execute(
                'SELECT id FROM stock_picking WHERE id IN %s ORDER BY id FOR UPDATE',
                [tuple(self.ids)],
            )

        move_ids = self.move_ids.ids
        if move_ids:
            self.env.cr.execute(
                'SELECT id FROM stock_move WHERE id IN %s ORDER BY id FOR UPDATE',
                [tuple(move_ids)],
            )

        move_line_ids = self.move_line_ids.ids
        if move_line_ids:
            self.env.cr.execute(
                'SELECT id FROM stock_move_line WHERE id IN %s ORDER BY id FOR UPDATE',
                [tuple(move_line_ids)],
            )

        for key in sorted(keys):
            self.env.cr.execute(
                'SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)',
                [self._hlv_quant_lock_name(key)],
            )

        product_ids = sorted({key[0] for key in keys})
        location_ids = sorted({key[1] for key in keys})
        if product_ids and location_ids:
            self.env.cr.execute(
                '''
                    SELECT id
                      FROM stock_quant
                     WHERE product_id IN %s
                       AND location_id IN %s
                     ORDER BY id
                     FOR UPDATE
                ''',
                [tuple(product_ids), tuple(location_ids)],
            )
        self.env.invalidate_all()
        _logger.info(
            '[HLV_QUANT_GUARD] locked %s quant keys before validating pickings=%s',
            len(keys),
            self.mapped('name'),
        )

    def _hlv_snapshot_quant_qty(self, keys):
        self.env.invalidate_all()
        return _quant_quantities_by_keys(self.env, keys)

    def _hlv_quant_delta_label(self, key):
        product_id, location_id, lot_id, package_id, owner_id, company_id = key
        product = self.env['product.product'].sudo().browse(product_id)
        location = self.env['stock.location'].sudo().browse(location_id)
        return (
            '%s | location=%s | lot=%s | package=%s | owner=%s | company=%s'
            % (
                product.display_name if product.exists() else product_id,
                location.complete_name if location.exists() else location_id,
                lot_id or '-',
                package_id or '-',
                owner_id or '-',
                company_id or '-',
            )
        )

    def _hlv_quant_trace_lines(self, trace_store, limit=80):
        lines = []
        for trace in (trace_store or [])[:limit]:
            lines.append(
                'ML id=%s move=%s picking=%s product=%s | '
                'before: state=%s quantity=%s picked=%s src=%s quant=%s dest=%s quant=%s | '
                'after: exists=%s state=%s quantity=%s picked=%s src_quant=%s dest_quant=%s%s'
                % (
                    trace.get('line_id'),
                    trace.get('move_id'),
                    trace.get('picking_name'),
                    trace.get('product_name'),
                    trace.get('state_before'),
                    trace.get('quantity_before'),
                    trace.get('picked_before'),
                    trace.get('source_label'),
                    trace.get('source_quant_before'),
                    trace.get('dest_label'),
                    trace.get('dest_quant_before'),
                    trace.get('exists_after'),
                    trace.get('state_after'),
                    trace.get('quantity_after'),
                    trace.get('picked_after'),
                    trace.get('source_quant_after'),
                    trace.get('dest_quant_after'),
                    ' exception=%s' % trace.get('exception') if trace.get('exception') else '',
                )
            )
        if trace_store and len(trace_store) > limit:
            lines.append('... truncated %s additional move-line traces' % (len(trace_store) - limit))
        return lines

    def _hlv_post_quant_guard_failure(self, errors, trace_store=None):
        picking_ids = self.ids
        if not picking_ids:
            return False
        error_items = ''.join('<li>%s</li>' % escape(error) for error in errors[:10])
        trace_lines = self._hlv_quant_trace_lines(trace_store)
        trace_html = ''
        if trace_lines:
            trace_html = (
                '<p><b>Move-line / quant trace quanh core _action_done:</b></p><ul>%s</ul>'
                % ''.join('<li>%s</li>' % escape(line) for line in trace_lines)
            )
        body = Markup(
            "<p><b>HLV_QUANT_GUARD - Lệch tồn sau validate</b></p>"
            "<p>Hệ thống phát hiện tồn kho sau khi xác nhận phiếu không khớp với số lượng đã chuyển. "
            "Giao dịch validate đã bị rollback để tránh lệch tồn.</p>"
            "<ul>%s</ul>%s"
        ) % (Markup(error_items), Markup(trace_html))

        try:
            with api.Environment.manage(), self.env.registry.cursor() as cr:
                log_env = api.Environment(cr, SUPERUSER_ID, {})
                pickings = log_env['stock.picking'].sudo().browse(picking_ids).exists()
                subtype = log_env.ref('mail.mt_note', raise_if_not_found=False)
                author = log_env.user.partner_id
                for picking in pickings:
                    values = {
                        'model': 'stock.picking',
                        'res_id': picking.id,
                        'message_type': 'comment',
                        'subject': 'HLV_QUANT_GUARD - Quant mismatch after validate',
                        'body': str(body),
                    }
                    if subtype:
                        values['subtype_id'] = subtype.id
                    if author:
                        values['author_id'] = author.id
                    log_env['mail.message'].sudo().create(values)
                cr.commit()
                return bool(pickings)
        except Exception:
            _logger.exception(
                '[HLV_QUANT_GUARD] failed to post mismatch note to pickings=%s',
                self.mapped('name'),
            )
            return False

    def _hlv_assert_quant_delta_after_validate(
        self, before_snapshot, expected_deltas, samples, trace_store=None,
    ):
        if not expected_deltas:
            return
        after_snapshot = self._hlv_snapshot_quant_qty(expected_deltas.keys())
        errors = []
        for key, delta in sorted(expected_deltas.items()):
            current_qty = after_snapshot.get(key, 0.0)
            expected_qty = before_snapshot.get(key, 0.0) + delta
            sample = samples.get(key)
            rounding = sample.product_id.uom_id.rounding if sample else 0.01
            if float_compare(current_qty, expected_qty, precision_rounding=rounding) == 0:
                continue
            errors.append(
                '%s | before=%s delta=%s expected=%s current=%s'
                % (
                    self._hlv_quant_delta_label(key),
                    before_snapshot.get(key, 0.0),
                    delta,
                    expected_qty,
                    current_qty,
                )
            )

        if not errors:
            return

        _logger.error(
            '[HLV_QUANT_GUARD] quant mismatch after validate pickings=%s errors=%s trace=%s',
            self.mapped('name'),
            errors,
            self._hlv_quant_trace_lines(trace_store),
        )
        chatter_logged = self._hlv_post_quant_guard_failure(errors, trace_store)
        chatter_message = _(
            "Chi tiết đã được ghi vào chatter của phiếu với tag HLV_QUANT_GUARD."
        ) if chatter_logged else _(
            "Không ghi được chatter; vui lòng kiểm tra server log HLV_QUANT_GUARD."
        )
        raise UserError(_(
            "Tồn kho sau khi xác nhận phiếu không khớp với số lượng đã chuyển.\n"
            "Hệ thống đã hủy giao dịch validate này để tránh lệch tồn.\n\n"
            "%s\n\n"
            "%s\n"
            "Vui lòng thử validate lại. Nếu lỗi lặp lại, báo kỹ thuật kiểm tra phiếu này."
        ) % ("\n".join(errors[:10]), chatter_message))

    def button_validate(self):
        """
        Validate stock quantities before and after core validation.
        The post-check runs on every backend caller of stock.picking.button_validate.
        """
        for picking in self:
            picking._check_qty_validation_before_validate()

        guard_enabled = self._hlv_quant_delta_guard_enabled()
        deltas_by_picking = {}
        samples = {}
        before_snapshot = {}
        trace_store = []
        if guard_enabled:
            deltas_by_picking, samples = self._hlv_collect_validate_quant_deltas_by_picking()
            all_expected_deltas = self._hlv_merge_quant_deltas(deltas_by_picking)
            if all_expected_deltas:
                self._hlv_lock_validate_quant_flow(all_expected_deltas.keys())
                # Move lines may have changed while this transaction was waiting
                # for the picking/line locks. Rebuild expectations only after the
                # locks are held so the trace and post-check describe the rows
                # that core validation will actually process.
                deltas_by_picking, samples = self._hlv_collect_validate_quant_deltas_by_picking()
                locked_expected_deltas = self._hlv_merge_quant_deltas(deltas_by_picking)
                additional_keys = set(locked_expected_deltas) - set(all_expected_deltas)
                if additional_keys:
                    self._hlv_lock_validate_quant_flow(additional_keys)
                if locked_expected_deltas:
                    before_snapshot = self._hlv_snapshot_quant_qty(locked_expected_deltas.keys())

        validate_self = self.with_context(
            hlv_quant_trace=bool(guard_enabled and before_snapshot),
            hlv_quant_trace_store=trace_store,
        )
        res = super(StockPicking, validate_self).button_validate()

        if guard_enabled and before_snapshot:
            self.env.invalidate_all()
            done_picking_ids = set(self.filtered(lambda picking: picking.state == 'done').ids)
            done_expected_deltas = self._hlv_merge_quant_deltas(deltas_by_picking, done_picking_ids)
            self._hlv_assert_quant_delta_after_validate(
                before_snapshot,
                done_expected_deltas,
                samples,
                trace_store=trace_store,
            )

        return res


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.depends('move_line_ids.qty_done', 'move_line_ids.product_uom_id')
    def _compute_quantity_done(self):
        """
        Override _compute_quantity_done để thêm warning log khi phát hiện
        qty_done > product_uom_qty (không chặn ở đây, chỉ log cảnh báo).
        """
        res = super(StockMove, self)._compute_quantity_done()

        for move in self:
            if move.state in ('done', 'cancel'):
                continue

            qty_demand = float(move.product_uom_qty or 0.0)
            qty_done = float(move.quantity or 0.0)
            EPS = 1e-6

            if qty_done > qty_demand + EPS:
                _logger.debug(
                    "⚠️ Move %s (%s): qty_done (%.2f) > product_uom_qty (%.2f) - sẽ chặn khi validate picking",
                    move.id,
                    move.product_id.display_name,
                    qty_done,
                    qty_demand
                )

        return res


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _hlv_trace_quant_key(self, move_line, location, package):
        if not location or location.usage not in ('internal', 'transit'):
            return False
        company = move_line.company_id or move_line.picking_id.company_id
        return (
            move_line.product_id.id,
            location.id,
            move_line.lot_id.id or False,
            package.id if package else False,
            move_line.owner_id.id or False,
            company.id if company else False,
        )

    def _hlv_trace_quant_label(self, key):
        if not key:
            return '-'
        _product_id, location_id, lot_id, package_id, owner_id, company_id = key
        location = self.env['stock.location'].sudo().browse(location_id)
        return '%s [lot=%s package=%s owner=%s company=%s]' % (
            location.complete_name if location.exists() else location_id,
            lot_id or '-',
            package_id or '-',
            owner_id or '-',
            company_id or '-',
        )

    def _hlv_trace_before_action_done(self):
        traces = []
        for move_line in self:
            source_key = self._hlv_trace_quant_key(
                move_line, move_line.location_id, move_line.package_id,
            )
            dest_key = self._hlv_trace_quant_key(
                move_line, move_line.location_dest_id, move_line.result_package_id,
            )
            traces.append({
                'line_id': move_line.id,
                'move_id': move_line.move_id.id,
                'picking_id': move_line.picking_id.id,
                'picking_name': move_line.picking_id.name or '-',
                'product_name': move_line.product_id.display_name,
                'state_before': move_line.state,
                'quantity_before': move_line.quantity,
                'picked_before': getattr(move_line, 'picked', None),
                'source_key': source_key,
                'dest_key': dest_key,
                'source_label': self._hlv_trace_quant_label(source_key),
                'dest_label': self._hlv_trace_quant_label(dest_key),
            })
        keys = {
            key
            for trace in traces
            for key in (trace['source_key'], trace['dest_key'])
            if key
        }
        quantities = _quant_quantities_by_keys(self.env, keys)
        for trace in traces:
            trace['source_quant_before'] = quantities.get(trace['source_key']) if trace['source_key'] else None
            trace['dest_quant_before'] = quantities.get(trace['dest_key']) if trace['dest_key'] else None
        return traces

    def _hlv_trace_after_action_done(self, traces, exception=None):
        self.env.invalidate_all()
        keys = {
            key
            for trace in traces
            for key in (trace['source_key'], trace['dest_key'])
            if key
        }
        quantities = _quant_quantities_by_keys(self.env, keys)
        for trace in traces:
            line = self.browse(trace['line_id']).exists()
            trace.update({
                'exists_after': bool(line),
                'state_after': line.state if line else 'deleted',
                'quantity_after': line.quantity if line else None,
                'picked_after': getattr(line, 'picked', None) if line else None,
                'source_quant_after': quantities.get(trace['source_key']) if trace['source_key'] else None,
                'dest_quant_after': quantities.get(trace['dest_key']) if trace['dest_key'] else None,
            })
            if exception:
                trace['exception'] = exception
        return traces

    def _action_done(self):
        if not self.env.context.get('hlv_quant_trace'):
            return super()._action_done()

        trace_store = self.env.context.get('hlv_quant_trace_store')
        traces = self._hlv_trace_before_action_done()
        try:
            result = super()._action_done()
        except Exception as error:
            self._hlv_trace_after_action_done(traces, exception=repr(error))
            if isinstance(trace_store, list):
                trace_store.extend(traces)
            _logger.exception(
                '[HLV_QUANT_TRACE] core stock.move.line._action_done failed trace=%s',
                traces,
            )
            raise

        self._hlv_trace_after_action_done(traces)
        if isinstance(trace_store, list):
            trace_store.extend(traces)
        _logger.debug('[HLV_QUANT_TRACE] stock.move.line._action_done trace=%s', traces)
        return result

    def _get_qty_done_value(self):
        """
        Lấy giá trị qty_done, tương thích cả Odoo 16 (qty_done) và Odoo 17+ (quantity)
        """
        if hasattr(self, 'qty_done'):
            return float(self.qty_done or 0.0)
        return float(self.quantity or 0.0)

    @api.constrains('qty_done', 'quantity')
    def _check_qty_done_not_exceed_demand(self):
        """
        Chặn ngay khi tạo hoặc cập nhật stock.move.line nếu quantity vượt quá
        product_uom_qty của stock.move tương ứng.

        Điều này ngăn chặn việc quét mã vạch dư hoặc nhập thủ công số lượng vượt mức.
        Bỏ qua phiếu chuyển hàng nội bộ (có 'INT' trong tên) vì demand luôn = 0.
        """
        # Bypass validation nếu được gọi từ packaging context
        if self.env.context.get('skip_qty_validation'):
            return
            
        EPS = 1e-6  # Epsilon để xử lý sai số floating point

        for line in self:
            # Bỏ qua nếu không có move liên kết hoặc move đã done/cancel
            if not line.move_id or line.move_id.state in ('done', 'cancel'):
                continue

            # Bỏ qua nếu picking đã done (cho phép điều chỉnh sau khi hoàn thành)
            if line.picking_id and line.picking_id.state == 'done':
                continue

            # Bỏ qua phiếu chuyển hàng nội bộ (có 'INT' trong tên)
            if not line.picking_id or (line.picking_id.name and 'INT' in line.picking_id.name):
                continue

            move = line.move_id

            # Lấy tổng qty_done của TẤT CẢ move lines cùng move (bao gồm line hiện tại)
            total_qty_done = sum(
                ml._get_qty_done_value()
                for ml in move.move_line_ids
                if ml.state not in ('done', 'cancel')
            )

            # Số lượng demand (đã đặt)
            qty_demand = float(move.product_uom_qty or 0.0)

            # Kiểm tra vi phạm
            if total_qty_done > qty_demand + EPS:
                product_name = move.product_id.display_name or move.product_id.name or _("Sản phẩm không xác định")
                uom_name = move.product_uom.name if move.product_uom else ''
                picking_name = line.picking_id.name if line.picking_id else _("N/A")

                _logger.error(
                    "🚫 CHẶN tạo/cập nhật move.line: Picking %s, Product %s, "
                    "Total qty_done (%.2f) > demand (%.2f)",
                    picking_name, product_name, total_qty_done, qty_demand
                )

                raise UserError(_(
                    "Không thể nhập số lượng vượt quá demand!\n\n"
                    "📦 Phiếu: %s\n"
                    "🏷️ Sản phẩm: %s\n"
                    "📊 Đã đặt (Demand): %.2f %s\n"
                    "✏️ Đã nhập (Done): %.2f %s\n\n"
                    "❌ Bạn đang cố nhập %.2f %s vượt quá số lượng cho phép.\n\n"
                    "💡 Vui lòng kiểm tra lại số lượng hoặc liên hệ quản lý."
                ) % (
                    picking_name,
                    product_name,
                    qty_demand, uom_name,
                    total_qty_done, uom_name,
                    total_qty_done - qty_demand, uom_name
                ))

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create để validate ngay khi tạo move.line mới
        (ví dụ: khi quét mã vạch)
        """
        lines = super(StockMoveLine, self).create(vals_list)

        # Validate sau khi tạo (bypass nếu có skip flag)
        if not self.env.context.get('skip_qty_validation'):
            lines._check_qty_done_not_exceed_demand()

        return lines

    def write(self, vals):
        """
        Override write để validate khi cập nhật qty_done hoặc quantity
        """
        res = super(StockMoveLine, self).write(vals)

        # Chỉ validate nếu có thay đổi qty_done hoặc quantity (bypass nếu có skip flag)
        if ('qty_done' in vals or 'quantity' in vals) and not self.env.context.get('skip_qty_validation'):
            self._check_qty_done_not_exceed_demand()

        return res
