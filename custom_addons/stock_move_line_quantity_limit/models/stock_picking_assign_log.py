from odoo import api, models
import logging

_logger = logging.getLogger(__name__)


class StockPickingAssignLog(models.Model):
    _inherit = 'stock.picking'

    def action_assign(self):
        """Log khi user bấm nút 'Kiểm tra tình trạng còn hàng'
        và tự động sửa ghost reservation trước khi assign."""
        _logger.info(
            '[ASSIGN_LOG] ===== action_assign CALLED | picking=%s (id=%s) | state=%s =====',
            self.name, self.id, self.state,
        )

        # Tự động sửa ghost reservation trước khi assign
        self._fix_ghost_reservations_before_assign()

        # Log tất cả moves đang cần dự trữ
        for move in self.move_ids.filtered(lambda m: m.state not in ['done', 'cancel']):
            # Lấy quant tại source location
            quants = self.env['stock.quant'].search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', move.location_id.id),
            ])
            on_hand = sum(q.quantity for q in quants)
            reserved = sum(q.reserved_quantity for q in quants)
            available = sum(q.available_quantity for q in quants)

            # Lấy move lines hiện tại (trước khi assign)
            existing_lines = move.move_line_ids.filtered(lambda l: l.state not in ['done', 'cancel'])
            existing_reserved = sum(l.quantity for l in existing_lines)

            _logger.info(
                '[ASSIGN_LOG] MOVE | product=%s (id=%s) | demand=%s | '
                'source_location=%s (id=%s) | '
                'on_hand=%s | reserved_in_quant=%s | available=%s | '
                'already_reserved_in_lines=%s',
                move.product_id.display_name,
                move.product_id.id,
                move.product_uom_qty,
                move.location_id.display_name,
                move.location_id.id,
                on_hand,
                reserved,
                available,
                existing_reserved,
            )

            # Nếu hàng ở nhiều sub-location, log từng sub-location
            all_quants = self.env['stock.quant'].search([
                ('product_id', '=', move.product_id.id),
                ('location_id', 'child_of', move.location_id.id),
            ])
            if len(all_quants) > 1:
                _logger.info('[ASSIGN_LOG] MULTI-LOC breakdown cho product=%s:', move.product_id.display_name)
                for q in all_quants:
                    _logger.info(
                        '[ASSIGN_LOG]   -> location=%s (id=%s) | on_hand=%s | reserved=%s | available=%s',
                        q.location_id.display_name, q.location_id.id,
                        q.quantity, q.reserved_quantity, q.available_quantity,
                    )
                    # Nếu location này có reserved > 0, log xem PICKING NÀO đang giữ
                    if q.reserved_quantity > 0:
                        reserving_lines = self.env['stock.move.line'].search([
                            ('product_id', '=', move.product_id.id),
                            ('location_id', '=', q.location_id.id),
                            ('state', 'not in', ['done', 'cancel']),
                            ('quantity', '>', 0),
                        ])
                        sum_from_lines = sum(rl.quantity for rl in reserving_lines)
                        for rl in reserving_lines:
                            _logger.info(
                                '[ASSIGN_LOG]      * RESERVED BY: picking=%s (id=%s) | picking_state=%s | move_line_id=%s | qty=%s | này_có_phải_picking_hiện_tại=%s',
                                rl.picking_id.name if rl.picking_id else 'N/A',
                                rl.picking_id.id if rl.picking_id else 'N/A',
                                rl.picking_id.state if rl.picking_id else 'N/A',
                                rl.id,
                                rl.quantity,
                                rl.picking_id.id == self.id,
                            )
                        # Phát hiện ghost reservation
                        if abs(sum_from_lines - q.reserved_quantity) > 0.001:
                            _logger.warning(
                                '[ASSIGN_LOG]      *** GHOST RESERVATION DETECTED! location=%s | '
                                'quant.reserved_quantity=%s | sum(move_lines.qty)=%s | phantom=%s cái ***',
                                q.location_id.display_name,
                                q.reserved_quantity,
                                sum_from_lines,
                                q.reserved_quantity - sum_from_lines,
                            )

        result = super().action_assign()

        _logger.info('[ASSIGN_LOG] ===== action_assign DONE | picking=%s =====', self.name)

        # Log move lines SAU khi assign
        for move in self.move_ids.filtered(lambda m: m.state not in ['cancel']):
            for line in move.move_line_ids.filtered(lambda l: l.state not in ['cancel']):
                _logger.info(
                    '[ASSIGN_LOG] RESULT LINE | product=%s | location=%s (id=%s) | qty_reserved=%s | state=%s',
                    line.product_id.display_name,
                    line.location_id.display_name,
                    line.location_id.id,
                    line.quantity,
                    line.state,
                )

        return result

    def _fix_ghost_reservations_before_assign(self):
        """
        Tự động phát hiện và sửa ghost reservation trước khi assign.
        Ghost reservation = quant.reserved_quantity > tổng move lines thực tế.
        """
        for move in self.move_ids.filtered(lambda m: m.state not in ['done', 'cancel']):
            quants = self.env['stock.quant'].search([
                ('product_id', '=', move.product_id.id),
                ('location_id', 'child_of', move.location_id.id),
            ])
            for q in quants:
                real_reserved = sum(
                    self.env['stock.move.line'].search([
                        ('product_id', '=', move.product_id.id),
                        ('location_id', '=', q.location_id.id),
                        ('state', 'not in', ['done', 'cancel']),
                        ('quantity', '>', 0),
                    ]).mapped('quantity')
                )
                if abs(q.reserved_quantity - real_reserved) > 0.001:
                    _logger.warning(
                        '[ASSIGN_LOG] AUTO-FIX ghost reservation | location=%s | '
                        'quant.reserved=%s → fix to=%s (phantom=%s)',
                        q.location_id.display_name,
                        q.reserved_quantity,
                        real_reserved,
                        q.reserved_quantity - real_reserved,
                    )
                    q.sudo().write({'reserved_quantity': real_reserved})

    def button_validate(self):
        """
        Lớp bảo vệ thứ 3: Trước khi validate picking, kiểm tra lần cuối
        rằng tổng done qty không vượt quá tồn kho thực tế.
        Tính cả pending done từ các picking khác.
        Tự động điều chỉnh nếu vượt quá.
        """
        from markupsafe import Markup

        adjusted_moves = []

        for picking in self:
            # Nhóm moves theo (product, parent_location)
            product_location_map = {}
            for move in picking.move_ids.filtered(
                lambda m: m.state not in ['done', 'cancel'] and m.quantity > 0
            ):
                if not move.product_id or not move.location_id:
                    continue
                if move.location_id.usage != 'internal':
                    continue
                key = (move.product_id.id, move.location_id.id)
                product_location_map.setdefault(key, []).append(move)

            for (prod_id, loc_id), moves in product_location_map.items():
                product = moves[0].product_id
                location = moves[0].location_id

                # Tổng done qty trong picking hiện tại cho product này
                total_done_this_picking = sum(m.quantity for m in moves)

                # Tồn kho thực tế
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', prod_id),
                    ('location_id', 'child_of', loc_id),
                ])
                total_on_hand = sum(q.quantity for q in quants)
                total_reserved_quant = sum(q.reserved_quantity for q in quants)

                # Pending done từ picking khác (phần ĐÃ nhập tay nhưng chưa reserve trong quant)
                other_move_lines = self.env['stock.move.line'].search([
                    ('product_id', '=', prod_id),
                    ('location_id', 'child_of', loc_id),
                    ('state', 'not in', ['done', 'cancel']),
                    ('quantity', '>', 0),
                ])
                other_picking_qty = sum(
                    ml.quantity for ml in other_move_lines
                    if ml.picking_id.id != picking.id
                )
                # Pending = phần chưa reserve = other_qty - quant_reserved
                pending_others = max(0.0, other_picking_qty - total_reserved_quant)

                real_available = (
                    total_on_hand
                    - total_reserved_quant
                    - pending_others
                )

                if total_done_this_picking > real_available and real_available >= 0:
                    _logger.warning(
                        '[VALIDATE_CHECK] OVER-ALLOCATION | picking=%s | product=%s | '
                        'done=%s > real_available=%s | on_hand=%s | reserved_quant=%s | '
                        'pending_others=%s | own_reserved=%s',
                        picking.name, product.display_name,
                        total_done_this_picking, real_available,
                        total_on_hand, total_reserved_quant,
                        pending_others, own_reserved,
                    )

                    # Phân bổ lại qty cho các moves
                    remaining = max(0.0, real_available)
                    for m in moves:
                        if remaining <= 0:
                            old_qty = m.quantity
                            m.with_context(skip_qty_limit_write_check=True).write(
                                {'quantity': 0.0}
                            )
                            adjusted_moves.append(
                                (m, product, old_qty, 0.0)
                            )
                        elif m.quantity > remaining:
                            old_qty = m.quantity
                            m.with_context(skip_qty_limit_write_check=True).write(
                                {'quantity': remaining}
                            )
                            adjusted_moves.append(
                                (m, product, old_qty, remaining)
                            )
                            remaining = 0.0
                        else:
                            remaining -= m.quantity

            # Post thông báo nếu có điều chỉnh
            if adjusted_moves:
                msg_lines = []
                for move, product, old_qty, new_qty in adjusted_moves:
                    msg_lines.append(
                        '<li><b>%s</b>: %s → %s (kho không đủ)</li>'
                        % (product.display_name, old_qty, new_qty)
                    )
                msg = Markup(
                    '<div style="color: #856404; background-color: #fff3cd; '
                    'border: 1px solid #ffc107; padding: 10px; border-radius: 4px;">'
                    '<b>⚠️ Hệ thống đã tự động điều chỉnh số lượng thực tế:</b>'
                    '<ul>%s</ul>'
                    '<small>Lý do: Tổng SL nhập tay vượt quá tồn kho khả dụng '
                    '(đã tính cả các đơn khác đang xử lý).</small>'
                    '</div>'
                ) % Markup(''.join(msg_lines))
                picking.message_post(body=msg)

        return super().button_validate()

