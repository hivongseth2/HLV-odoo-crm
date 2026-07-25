from odoo import api, models
import logging

_logger = logging.getLogger(__name__)


class StockPickingAssignLog(models.Model):
    _inherit = 'stock.picking'

    def action_assign(self):
        """Log khi user bấm nút 'Kiểm tra tình trạng còn hàng'."""
        _logger.info(
            '[ASSIGN_LOG] ===== action_assign CALLED | picking=%s (id=%s) | state=%s =====',
            self.name, self.id, self.state,
        )

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


