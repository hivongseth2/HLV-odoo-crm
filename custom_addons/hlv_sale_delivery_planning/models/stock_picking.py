"""Adds delivery planner picking fields/actions and invalidates snapshots on picking changes.
"""

import logging
from datetime import timedelta
from markupsafe import Markup, escape
from odoo import api, models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Fields whose changes should trigger a real-time dashboard refresh
_PICK_NOTIFY_FIELDS = {
    'state', 'x_printed', 'carrier_id', 'carrier_tracking_ref',
    'scheduled_date', 'date_done', 'x_bien_ban_printed',
    'shipper_received', 'shipper_returned', 'shipper_user_id', 'shipper_received_by',
    'x_pack_packer_user_id', 'x_pack_assigned_by_id', 'x_pack_assigned_at',
    'x_pick_print_start_at', 'x_pick_print_end_at', 'x_pick_printed_by_id',
    'x_pack_actual_start_at', 'x_pack_actual_end_at', 'x_pack_actual_user_id',
    'x_pack_print_to_done_seconds', 'x_pack_actual_seconds', 'x_pack_source_pick_id',
}


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_printed = fields.Boolean(
        string='Đã in phiếu lấy hàng',
        default=False,
        copy=False,
        help='Đánh dấu tự động khi phiếu được in từ màn hình điều phối giao hàng',
    )

    x_bien_ban_printed = fields.Boolean(
        string='Đã in biên bản',
        default=False,
        copy=False,
        help='Đánh dấu tự động khi in các report như: biên bản giao nhận/bàn giao, BBGN, BBBG, PXBH, phiếu xuất, phiếu bàn giao... cho phiếu này.',
    )

    x_pack_packer_user_id = fields.Many2one(
        'res.users',
        string='Người đóng được assign',
        copy=False,
        index=True,
        help='Người đóng gói được chọn khi in phiếu lấy hàng. Lưu trên phiếu PICK.',
    )
    x_pack_assigned_by_id = fields.Many2one(
        'res.users',
        string='Người assign đóng gói',
        copy=False,
        readonly=True,
    )
    x_pack_assigned_at = fields.Datetime(
        string='Thời gian assign đóng gói',
        copy=False,
        readonly=True,
        index=True,
    )
    x_pick_print_start_at = fields.Datetime(
        string='Bắt đầu in phiếu lấy hàng',
        copy=False,
        index=True,
    )
    x_pick_print_end_at = fields.Datetime(
        string='Kết thúc in phiếu lấy hàng',
        copy=False,
        index=True,
    )
    x_pick_printed_by_id = fields.Many2one(
        'res.users',
        string='Người in phiếu lấy hàng',
        copy=False,
        readonly=True,
    )
    x_pack_source_pick_id = fields.Many2one(
        'stock.picking',
        string='Phiếu PICK nguồn',
        copy=False,
        index=True,
        help='Phiếu lấy hàng dùng để assign người đóng cho phiếu PACK này.',
    )
    x_pack_actual_start_at = fields.Datetime(
        string='Bắt đầu đóng thực tế',
        copy=False,
        index=True,
    )
    x_pack_actual_end_at = fields.Datetime(
        string='Kết thúc đóng thực tế',
        copy=False,
        index=True,
    )
    x_pack_actual_user_id = fields.Many2one(
        'res.users',
        string='Người thao tác đóng thực tế',
        copy=False,
        readonly=True,
    )
    x_pack_print_to_done_seconds = fields.Float(
        string='TG từ in PICK đến done PACK (giây)',
        copy=False,
        readonly=True,
    )
    x_pack_actual_seconds = fields.Float(
        string='TG đóng thực tế (giây)',
        copy=False,
        readonly=True,
    )

    def _is_pick_slip_picking(self):
        self.ensure_one()
        return (
            'PICK' in ((self.picking_type_id.sequence_code or '').upper())
            and not self.return_id
        )

    def _is_pack_picking(self):
        self.ensure_one()
        return (
            'PACK' in ((self.picking_type_id.sequence_code or '').upper())
            and not self.return_id
        )

    def _packer_display_name(self, user):
        return getattr(user, 'x_packer_name', None) or user.name or ''

    @api.model
    def get_packer_users_for_assignment(self):
        users = self.env['res.users'].sudo().search([
            ('share', '=', False),
            ('active', '=', True),
        ], order='name')
        return [
            {
                'id': user.id,
                'name': user.name,
                'packer_name': self._packer_display_name(user),
            }
            for user in users
        ]

    @api.model
    def prepare_picking_print_assignment_data(self, picking_ids):
        pickings = self.sudo().browse([int(pid) for pid in (picking_ids or []) if pid]).exists()
        pickings = pickings.filtered(
            lambda p: p._is_pick_slip_picking() and p.state not in ('done', 'cancel')
        )
        return {
            'required': bool(pickings),
            'picking_ids': pickings.ids,
            'pickings': [
                {
                    'id': picking.id,
                    'name': picking.name,
                    'origin': picking.origin or '',
                    'packer_user': (
                        [picking.x_pack_packer_user_id.id, self._packer_display_name(picking.x_pack_packer_user_id)]
                        if picking.x_pack_packer_user_id else False
                    ),
                }
                for picking in pickings
            ],
            'packers': self.get_packer_users_for_assignment(),
        }

    @api.model
    def assign_picking_print_packer(self, picking_ids, packer_user_id):
        pickings = self.sudo().browse([int(pid) for pid in (picking_ids or []) if pid]).exists()
        pickings = pickings.filtered(
            lambda p: p._is_pick_slip_picking() and p.state not in ('done', 'cancel')
        )
        if not pickings:
            return {'success': False, 'message': _('Không có phiếu lấy hàng hợp lệ để assign.')}
        pickings.sudo().with_context(
            pack_assigned_by_uid=self.env.uid,
            pack_printed_by_uid=self.env.uid,
        ).mark_picking_print_started(packer_user_id=packer_user_id)
        packer = self.env['res.users'].sudo().browse(int(packer_user_id)).exists()
        return {
            'success': True,
            'picking_ids': pickings.ids,
            'packer_user_id': packer.id,
            'packer_name': self._packer_display_name(packer),
        }

    @api.model
    def get_packing_kpi_dashboard(self, date_from=False, date_to=False, packer_user_id=False, search_text=False, packing_state=False):
        domain = [
            ('picking_type_id.sequence_code', 'ilike', 'PICK'),
            ('return_id', '=', False),
            ('x_pack_packer_user_id', '!=', False),
        ]
        if date_from:
            start = fields.Datetime.to_datetime(date_from)
            domain.append(('x_pack_assigned_at', '>=', start))
        if date_to:
            end = fields.Datetime.to_datetime(date_to) + timedelta(days=1)
            domain.append(('x_pack_assigned_at', '<', end))
        if packer_user_id and str(packer_user_id) != 'all':
            domain.append(('x_pack_packer_user_id', '=', int(packer_user_id)))

        picks = self.sudo().search(domain, order='x_pack_assigned_at desc, id desc')

        # Filter by search_text: match PICK name, SO name, or linked PACK name
        if search_text and picks:
            q = search_text.strip().lower()
            pack_domain_st = [
                ('x_pack_source_pick_id', 'in', picks.ids),
                ('name', 'ilike', q),
            ]
            matching_pack_pick_ids = set(
                self.sudo().search(pack_domain_st).mapped('x_pack_source_pick_id').ids
            )
            picks = picks.filtered(
                lambda p: (
                    q in (p.name or '').lower()
                    or q in (p.sale_id.name or '').lower()
                    or q in (p.origin or '').lower()
                    or p.id in matching_pack_pick_ids
                )
            )

        pack_domain = [('x_pack_source_pick_id', 'in', picks.ids)] if picks else [('id', '=', 0)]
        packs = self.sudo().search(pack_domain)
        packs_by_pick = {}
        for pack in packs:
            packs_by_pick.setdefault(pack.x_pack_source_pick_id.id, self.env['stock.picking'])
            packs_by_pick[pack.x_pack_source_pick_id.id] |= pack

        groups = {}
        filter_state = str(packing_state or 'all')
        total_assigned = 0
        total_done = 0
        total_in_progress = 0
        print_to_done_values = []
        actual_values = []

        for pick in picks:
            related_packs = packs_by_pick.get(pick.id, self.env['stock.picking'])
            done_packs = related_packs.filtered(lambda p: p.state == 'done')
            active_packs = related_packs.filtered(lambda p: p.state not in ('done', 'cancel'))
            best_pack = done_packs[:1] or active_packs[:1] or related_packs[:1]
            is_done = bool(done_packs)
            is_in_progress = bool(active_packs.filtered(lambda p: p.x_pack_actual_start_at or p.state == 'in_progress'))
            row_state = 'done' if is_done else ('in_progress' if is_in_progress else 'assigned')
            if filter_state != 'all' and row_state != filter_state:
                continue

            packer = pick.x_pack_packer_user_id
            key = packer.id
            group = groups.setdefault(key, {
                'packer_user_id': packer.id,
                'packer_name': self._packer_display_name(packer),
                'assigned_count': 0,
                'in_progress_count': 0,
                'done_count': 0,
                'avg_print_to_done_seconds': 0,
                'avg_actual_seconds': 0,
                'rows': [],
                '_print_values': [],
                '_actual_values': [],
            })

            group['assigned_count'] += 1
            total_assigned += 1
            if is_done:
                group['done_count'] += 1
                total_done += 1
            elif is_in_progress:
                group['in_progress_count'] += 1
                total_in_progress += 1

            print_seconds = best_pack.x_pack_print_to_done_seconds if best_pack else 0
            actual_seconds = best_pack.x_pack_actual_seconds if best_pack else 0
            if print_seconds:
                group['_print_values'].append(print_seconds)
                print_to_done_values.append(print_seconds)
            if actual_seconds:
                group['_actual_values'].append(actual_seconds)
                actual_values.append(actual_seconds)

            group['rows'].append({
                'pick_id': pick.id,
                'pick_name': pick.name,
                'packer_user_id': packer.id,
                'sale_order': pick.sale_id.name or pick.origin or '',
                'pack_name': best_pack.name if best_pack else '',
                'state': row_state,
                'assigned_at': pick.x_pack_assigned_at.strftime('%Y-%m-%d %H:%M:%S') if pick.x_pack_assigned_at else False,
                'print_start_at': pick.x_pick_print_start_at.strftime('%Y-%m-%d %H:%M:%S') if pick.x_pick_print_start_at else False,
                'print_end_at': pick.x_pick_print_end_at.strftime('%Y-%m-%d %H:%M:%S') if pick.x_pick_print_end_at else False,
                'pack_start_at': best_pack.x_pack_actual_start_at.strftime('%Y-%m-%d %H:%M:%S') if best_pack and best_pack.x_pack_actual_start_at else False,
                'pack_end_at': best_pack.x_pack_actual_end_at.strftime('%Y-%m-%d %H:%M:%S') if best_pack and best_pack.x_pack_actual_end_at else False,
                'print_to_done_seconds': print_seconds or 0,
                'actual_seconds': actual_seconds or 0,
            })

        def avg(values):
            return sum(values) / len(values) if values else 0

        group_list = []
        for group in groups.values():
            group['avg_print_to_done_seconds'] = avg(group.pop('_print_values'))
            group['avg_actual_seconds'] = avg(group.pop('_actual_values'))
            group_list.append(group)
        group_list.sort(key=lambda g: (g['assigned_count'], g['done_count']), reverse=True)

        return {
            'summary': {
                'assigned_count': total_assigned,
                'in_progress_count': total_in_progress,
                'done_count': total_done,
                'avg_print_to_done_seconds': avg(print_to_done_values),
                'avg_actual_seconds': avg(actual_values),
            },
            'groups': group_list,
            'packers': self.get_packer_users_for_assignment(),
        }

    @api.model
    def get_packing_kpi_daily_chart(self, date_from=False, date_to=False, packer_user_id=False, packing_state=False):
        """Return daily breakdown for chart rendering: labels + done/in_progress/assigned arrays."""
        domain = [
            ('picking_type_id.sequence_code', 'ilike', 'PICK'),
            ('return_id', '=', False),
            ('x_pack_packer_user_id', '!=', False),
        ]
        if date_from:
            start = fields.Datetime.to_datetime(date_from)
            domain.append(('x_pack_assigned_at', '>=', start))
        if date_to:
            end = fields.Datetime.to_datetime(date_to) + timedelta(days=1)
            domain.append(('x_pack_assigned_at', '<', end))
        if packer_user_id and str(packer_user_id) != 'all':
            domain.append(('x_pack_packer_user_id', '=', int(packer_user_id)))

        picks = self.sudo().search(domain)
        pack_domain = [('x_pack_source_pick_id', 'in', picks.ids)] if picks else [('id', '=', 0)]
        packs = self.sudo().search(pack_domain)
        packs_by_pick = {}
        for pack in packs:
            packs_by_pick.setdefault(pack.x_pack_source_pick_id.id, self.env['stock.picking'])
            packs_by_pick[pack.x_pack_source_pick_id.id] |= pack

        filter_state = str(packing_state or 'all')
        daily = {}
        for pick in picks:
            if not pick.x_pack_assigned_at:
                continue
            related_packs = packs_by_pick.get(pick.id, self.env['stock.picking'])
            done_packs = related_packs.filtered(lambda p: p.state == 'done')
            active_packs = related_packs.filtered(lambda p: p.state not in ('done', 'cancel'))
            is_done = bool(done_packs)
            is_in_progress = bool(active_packs.filtered(lambda p: p.x_pack_actual_start_at or p.state == 'in_progress'))
            row_state = 'done' if is_done else ('in_progress' if is_in_progress else 'assigned')
            if filter_state != 'all' and row_state != filter_state:
                continue
            vn_dt = pick.x_pack_assigned_at + timedelta(hours=7)
            day = vn_dt.strftime('%Y-%m-%d')
            if day not in daily:
                daily[day] = {'assigned': 0, 'done': 0, 'in_progress': 0}
            daily[day]['assigned'] += 1
            if done_packs:
                daily[day]['done'] += 1
            elif is_in_progress:
                daily[day]['in_progress'] += 1

        labels = sorted(daily.keys())
        return {
            'labels': labels,
            'assigned': [daily[d]['assigned'] for d in labels],
            'done': [daily[d]['done'] for d in labels],
            'in_progress': [daily[d]['in_progress'] for d in labels],
        }

    def _is_pack_restriction_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'hlv_sale_delivery_planning.restrict_pack_to_assigned_user'
        ) in ('1', 'True', 'true', True)

    def _is_pack_manager(self, user=None):
        user = user or self.env.user
        return bool(
            user._is_superuser()
            or user.has_group('hlv_sale_delivery_planning.group_pack_manager')
        )

    def _resolve_assigned_pick_for_pack(self):
        self.ensure_one()
        if self._is_pick_slip_picking():
            return self
        if self.x_pack_source_pick_id.exists():
            return self.x_pack_source_pick_id
        domain = [
            ('id', '!=', self.id),
            ('return_id', '=', False),
            ('picking_type_id.sequence_code', 'ilike', 'PICK'),
            ('state', '!=', 'cancel'),
        ]
        if self.group_id:
            domain.append(('group_id', '=', self.group_id.id))
        elif self.sale_id:
            domain.append(('sale_id', '=', self.sale_id.id))
        elif self.origin:
            domain.append(('origin', '=', self.origin))
        else:
            return self.env['stock.picking']
        return self.sudo().search(domain, order='x_pick_print_end_at desc, date_done desc, id desc', limit=1)

    def _check_pack_assignment_access(self, user=None, raise_exception=True):
        self.ensure_one()
        user = user or self.env.user
        if not self._is_pack_picking() or not self._is_pack_restriction_enabled():
            return True
        if self._is_pack_manager(user):
            return True
        source_pick = self._resolve_assigned_pick_for_pack()
        assigned_user = source_pick.x_pack_packer_user_id if source_pick else False
        if assigned_user and assigned_user.id == user.id:
            return True
        assigned_name = self._packer_display_name(assigned_user) if assigned_user else _('chưa assign')
        message = _('Bạn không được assign đóng phiếu này. Người đóng: %s') % assigned_name
        if raise_exception:
            raise UserError(message)
        return False

    def action_assign_packer(self, packer_user_id):
        packer = self.env['res.users'].sudo().browse(int(packer_user_id)).exists()
        if not packer:
            raise UserError(_('Không tìm thấy người đóng được chọn.'))
        now = fields.Datetime.now()
        picks = self.filtered(lambda p: p._is_pick_slip_picking())
        if not picks:
            raise UserError(_('Không có phiếu lấy hàng hợp lệ để assign.'))
        assigner_name = self.env['res.users'].sudo().browse(
            self.env.context.get('pack_assigned_by_uid') or self.env.uid
        ).name or ''
        local_now = now + timedelta(hours=7)
        time_str = local_now.strftime('%H:%M %d/%m/%Y')
        for pick in picks:
            old_packer = pick.x_pack_packer_user_id
            pick.write({
                'x_pack_packer_user_id': packer.id,
                'x_pack_assigned_by_id': self.env.context.get('pack_assigned_by_uid') or self.env.uid,
                'x_pack_assigned_at': now,
            })
            if old_packer and old_packer.id != packer.id:
                body = Markup('🔄 Đổi người đóng gói lúc {time}: {old} → <b>{new}</b> (bởi {by})').format(
                    time=time_str,
                    old=escape(old_packer.name or ''),
                    new=escape(packer.name or ''),
                    by=escape(assigner_name),
                )
            else:
                body = Markup('👤 Assign người đóng gói lúc {time}: <b>{new}</b> (bởi {by})').format(
                    time=time_str,
                    new=escape(packer.name or ''),
                    by=escape(assigner_name),
                )
            pick.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note')
        return True

    def do_print_picking(self):
        """Override: open packer selection wizard if no packer assigned (PICK slips only)."""
        for picking in self:
            if not picking.exists():
                continue
            if picking._is_pick_slip_picking() and not picking.x_pack_packer_user_id:
                wizard = self.env['stock.picking.packer.print.wizard'].create({
                    'picking_id': picking.id,
                })
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Chọn người đóng gói'),
                    'res_model': 'stock.picking.packer.print.wizard',
                    'res_id': wizard.id,
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'form_view_ref': 'hlv_sale_delivery_planning.view_picking_packer_print_wizard',
                    },
                }
        return super().do_print_picking()

    def mark_picking_print_started(self, packer_user_id=None):
        picks = self.filtered(lambda p: p._is_pick_slip_picking())
        if not picks:
            return False
        if packer_user_id:
            picks.action_assign_packer(packer_user_id)
        elif any(not p.x_pack_packer_user_id for p in picks):
            raise UserError(_('Vui lòng chọn người đóng trước khi in phiếu lấy hàng.'))

        config_param = self.env['ir.config_parameter'].sudo()
        print_time_mode = config_param.get_param(
            'hlv_sale_delivery_planning.pick_print_time_mode', 'first'
        )
        now = fields.Datetime.now()
        printed_by = self.env.context.get('pack_printed_by_uid') or self.env.uid
        printer_name = self.env['res.users'].sudo().browse(printed_by).name or ''
        local_now = now + timedelta(hours=7)
        time_str = local_now.strftime('%H:%M %d/%m/%Y')

        for pick in picks:
            vals = {'x_pick_printed_by_id': printed_by}
            # Only update print_start_at if not yet recorded, or mode is 'latest'
            if print_time_mode == 'latest' or not pick.x_pick_print_start_at:
                vals['x_pick_print_start_at'] = now
            pick.write(vals)
            # Log to chatter (use Markup so HTML is rendered, not shown as raw text)
            body = Markup('🖨️ In phiếu lấy hàng lúc {time} bởi <b>{user}</b>').format(
                time=time_str,
                user=escape(printer_name),
            )
            pick.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note')
        return True

    def mark_picking_print_finished(self):
        picks = self.filtered(lambda p: p._is_pick_slip_picking())
        if not picks:
            return False
        picks.write({
            'x_pick_print_end_at': fields.Datetime.now(),
            'x_printed': True,
        })
        return True

    def mark_pack_actual_started(self, user=None):
        user = user or self.env.user
        for picking in self:
            if not picking._is_pack_picking():
                continue
            picking._check_pack_assignment_access(user=user)
            source_pick = picking._resolve_assigned_pick_for_pack()
            vals = {
                'x_pack_actual_user_id': user.id,
            }
            if source_pick:
                vals['x_pack_source_pick_id'] = source_pick.id
            if not picking.x_pack_actual_start_at:
                vals['x_pack_actual_start_at'] = fields.Datetime.now()
            picking.write(vals)
        return True

    def mark_pack_done(self, user=None):
        user = user or self.env.user
        now = fields.Datetime.now()
        for picking in self:
            if not picking._is_pack_picking():
                continue
            source_pick = picking._resolve_assigned_pick_for_pack()
            start_at = picking.x_pack_actual_start_at or now
            vals = {
                'x_pack_actual_user_id': user.id,
                'x_pack_actual_end_at': now,
                'x_pack_actual_start_at': start_at,
                'x_pack_actual_seconds': max((now - start_at).total_seconds(), 0.0),
            }
            if source_pick:
                vals['x_pack_source_pick_id'] = source_pick.id
                print_start = source_pick.x_pick_print_start_at or source_pick.x_pick_print_end_at
                if print_start:
                    vals['x_pack_print_to_done_seconds'] = max((now - print_start).total_seconds(), 0.0)
            picking.write(vals)
        return True

    def button_validate(self):
        for picking in self:
            if picking._is_pack_picking():
                picking._check_pack_assignment_access()
        return super().button_validate()

    @api.model_create_multi
    def create(self, vals_list):
        """Phiếu MỚI (kể cả backorder do Odoo tự tách khi không lấy đủ hàng 1 lần) không đi qua
        write() nên hook dưới đây không bắt được — snapshot của đơn liên quan bị bỏ sót, giữ
        packing_status/has_assigned_pick TÍNH TỪ TRƯỚC KHI CÓ PHIẾU MỚI này, dẫn tới hiển thị
        sai trên Kanban (VD: đơn đã đóng gói xong lô 1 nhưng còn backorder lô 2 đang chờ hàng,
        Kanban vẫn kẹt ở cột cũ dù thực tế đã đổi). Phải invalidate ngay khi TẠO phiếu mới, không
        chỉ khi ghi lên phiếu đã có."""
        records = super().create(vals_list)
        records._notify_delivery_planner_changed()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals and _PICK_NOTIFY_FIELDS.intersection(vals.keys()):
            self._notify_delivery_planner_changed()
        return res

    def _action_done(self):
        res = super()._action_done()
        self._notify_delivery_planner_changed()
        return res

    def _notify_delivery_planner_changed(self):
        """Send bus notification with the affected SO ids so the dashboard can
        do a partial subset refresh instead of a full reload."""
        sale_orders = self.mapped('sale_id') | self.mapped('move_ids.sale_line_id.order_id')
        source_picks = self.mapped('x_pack_source_pick_id')
        if source_picks:
            sale_orders |= source_picks.mapped('sale_id') | source_picks.mapped('move_ids.sale_line_id.order_id')
        so_ids = list(set(sale_orders.ids))
        if not so_ids:
            return
        try:
            from ..services.delivery_planner_stats import bump_stats_cache_version
            bump_stats_cache_version()
        except Exception:
            pass
        try:
            self.env['hlv.delivery.planner.snapshot'].sudo().mark_dirty_for_sale_orders(
                so_ids, reason='stock.picking'
            )
        except Exception:
            pass
        try:
            self.env['bus.bus']._sendone(
                'delivery_planner_channel',
                'delivery_planner_data_changed',
                {'source': 'stock.picking', 'sale_order_ids': so_ids},
            )
        except Exception:
            _logger.debug('Failed to send delivery_planner_data_changed notification', exc_info=True)
