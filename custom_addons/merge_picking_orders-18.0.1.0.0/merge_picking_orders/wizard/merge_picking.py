# -*- coding: utf-8 -*-
###############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Sreerag PM(odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from odoo import fields, models, _
from odoo.exceptions import AccessError


class MergePicking(models.TransientModel):
    """
    Class for wizard to show selected pickings to merge
    Method:
        action_merge(self):
            Method to merge the selected pickings
    """
    _name = 'merge.picking'
    _description = "Merge Picking Wizard"

    merge_picking_ids = fields.Many2many('stock.picking', string='Danh sách phiếu',
                                         help="Các phiếu đã chọn để gộp")
    existing_pick_id = fields.Many2one(
        'stock.picking', string="Gộp vào phiếu có sẵn",
        help="Chọn phiếu nếu bạn muốn gộp vào phiếu đã có sẵn,"
             " nếu không thì để trống")

    def action_merge(self):
        """
        Main method to merge selected pickings
        - If checked 'merge to existing' then the selected pickings will be
          merged to last record
        - Else a new record will be created with the existing picking lines
        - The selected pickings will be moved to cancelled state
        - The newly created picking will be in ready state
        """
        # Checking for exceptions if exist raise corresponding messages
        if len(list(set(x.partner_id if x.partner_id else None for x in
                        self.merge_picking_ids))) > 1:
            raise AccessError(_("Không thể gộp phiếu của các đối tác khác nhau,"
                                " vui lòng chọn phiếu cùng đối tác"))
        if len(list(set(self.merge_picking_ids.mapped('picking_type_id')))) > 1:
            raise AccessError(
                _("Không thể gộp phiếu khác loại,"
                  " vui lòng chọn phiếu cùng loại"))
        if any(state in ['done', 'cancel'] for state in
               self.merge_picking_ids.mapped('state')):
            raise AccessError(_('Không thể gộp phiếu đã Hoàn thành/Đã hủy, '
                                'vui lòng bỏ chọn các phiếu đó và thử lại'))
        if len(list(set(self.merge_picking_ids.mapped('state')))) > 1:
            raise AccessError(_('Không thể gộp phiếu ở trạng thái khác nhau, '
                                'vui lòng chọn phiếu cùng trạng thái'))
        if len(self.merge_picking_ids) == 1:
            raise AccessError(_('Không thể gộp khi chỉ có một phiếu,'
                                ' vui lòng chọn ít nhất hai phiếu'))
        # If there is no exception, continues with the merging process
        source_document = []
        origins = set()
        if self.existing_pick_id:
            main_pick = self.existing_pick_id
            orders = self.merge_picking_ids-main_pick
            moves = main_pick.move_ids
            source_document.append(main_pick.name)
            if main_pick.origin:
                origins.add(main_pick.origin)
        else:
            orders = self.merge_picking_ids
            moves = self.env['stock.move']
            main_pick = orders[0].copy({'move_ids': None})
        for record in orders:
            for line in record.move_ids:
                moves += line.copy({'picking_id': main_pick.id})
            source_document.append(record.name)
            if record.origin:
                origins.add(record.origin)
            record.action_cancel()
        # Giữ nguyên origin nếu tất cả phiếu cùng origin, ngược lại ghi "Gộp từ"
        if len(origins) == 1:
            merged_origin = origins.pop()
        else:
            merged_origin = f"Gộp từ ({', '.join(source_document)})"
        main_pick.write({'origin': merged_origin})
        main_pick.action_confirm()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': main_pick.id,
            'target': 'current',
        }
