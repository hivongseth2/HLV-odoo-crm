import io
import base64

from odoo import models, fields, api
from odoo.exceptions import UserError


class HlvInventoryReportWizard(models.TransientModel):
    _name = 'hlv.inventory.report.wizard'
    _description = 'Báo cáo tồn kho theo nhóm sản phẩm'

    config_id = fields.Many2one(
        'hlv.inventory.report.config',
        string='Cấu hình đã lưu',
        ondelete='set null',
    )
    group_ids = fields.Many2many(
        'hlv.product.report.group',
        string='Nhóm sản phẩm',
        required=True,
    )
    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'hlv_inv_report_wizard_wh_rel',
        'wizard_id',
        'warehouse_id',
        string='Kho hàng',
        help='Để trống để báo cáo tất cả các kho',
    )
    show_zero = fields.Boolean(
        'Hiển thị sản phẩm tồn = 0',
        default=True,
    )
    show_location_detail = fields.Boolean(
        'Chi tiết theo vị trí (Location)',
        default=False,
        help='Khi bật: cột báo cáo là từng vị trí con (shelf/bin) thay vì kho',
    )

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _get_warehouses(self):
        return self.warehouse_ids or self.env['stock.warehouse'].search([])

    def _get_locations(self):
        root_ids = self._get_warehouses().mapped('lot_stock_id').ids
        if not root_ids:
            return self.env['stock.location']
        return self.env['stock.location'].search([
            ('id', 'child_of', root_ids),
            ('usage', '=', 'internal'),
            ('active', '=', True),
        ])

    def _get_columns(self):
        if self.show_location_detail:
            return [
                {'id': loc.id, 'name': loc.display_name, 'record': loc}
                for loc in self._get_locations()
            ]
        return [
            {'id': wh.id, 'name': wh.name, 'code': wh.code or wh.name, 'record': wh}
            for wh in self._get_warehouses()
        ]

    def _get_product_qtys(self, product, columns):
        if self.show_location_detail:
            loc_ids = [c['id'] for c in columns]
            if loc_ids:
                groups = self.env['stock.quant'].read_group(
                    [('product_id', '=', product.id), ('location_id', 'in', loc_ids)],
                    ['location_id', 'quantity'],
                    ['location_id'],
                )
                qty_map = {g['location_id'][0]: g['quantity'] for g in groups}
            else:
                qty_map = {}
            return [{'col': c, 'qty': qty_map.get(c['id'], 0.0)} for c in columns]
        return [
            {'col': c, 'qty': product.with_context(warehouse=c['id']).qty_available}
            for c in columns
        ]

    def get_report_data(self):
        columns = self._get_columns()
        groups_data = []
        grand_col_totals = {c['id']: 0.0 for c in columns}
        grand_total = 0.0

        for group in self.group_ids.sorted('sequence'):
            products_data = []
            group_col_totals = {c['id']: 0.0 for c in columns}
            group_total = 0.0

            for product in group.product_ids.sorted('default_code'):
                col_qtys = self._get_product_qtys(product, columns)
                total = sum(cq['qty'] for cq in col_qtys)
                for cq in col_qtys:
                    group_col_totals[cq['col']['id']] += cq['qty']
                group_total += total

                if not self.show_zero and total == 0:
                    continue

                products_data.append({
                    'product': product,
                    'col_qtys': col_qtys,
                    'total': total,
                })

            for c in columns:
                grand_col_totals[c['id']] += group_col_totals[c['id']]
            grand_total += group_total

            groups_data.append({
                'group': group,
                'products': products_data,
                'group_col_totals': [
                    {'col': c, 'qty': group_col_totals[c['id']]} for c in columns
                ],
                'group_total': group_total,
            })

        return {
            'wizard': self,
            'columns': columns,
            'groups_data': groups_data,
            'grand_col_totals': [
                {'col': c, 'qty': grand_col_totals[c['id']]} for c in columns
            ],
            'grand_total': grand_total,
            'multi_group': len(self.group_ids) > 1,
            'show_location_detail': self.show_location_detail,
        }

    def _populate_result_lines(self):
        """Delete old lines then create fresh result lines."""
        self.env['hlv.inventory.report.line'].search(
            [('wizard_id', '=', self.id)]
        ).unlink()

        data = self.get_report_data()
        columns = data['columns']
        lines_vals = []
        seq = 1

        for group_data in data['groups_data']:
            for prod in group_data['products']:
                if len(columns) == 1:
                    qty_details = '%g' % prod['col_qtys'][0]['qty']
                else:
                    parts = [
                        '%s: %g' % (cq['col'].get('code') or cq['col']['name'], cq['qty'])
                        for cq in prod['col_qtys'] if cq['qty'] > 0
                    ]
                    qty_details = ' | '.join(parts) if parts else '—'

                lines_vals.append({
                    'wizard_id': self.id,
                    'sequence': seq,
                    'group_name': group_data['group'].name,
                    'product_code': prod['product'].default_code or '',
                    'product_name': prod['product'].name,
                    'qty_details': qty_details,
                    'qty_total': prod['total'],
                })
                seq += 1

        self.env['hlv.inventory.report.line'].create(lines_vals)

    # -----------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------

    def action_view_web(self):
        """Populate lines then open list view in the main area (no download)."""
        self._populate_result_lines()
        warehouses = self._get_warehouses()
        wh_label = (
            ', '.join(warehouses.mapped('name'))
            if self.warehouse_ids else 'Tất cả kho'
        )
        grp_label = ', '.join(self.group_ids.mapped('name'))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tồn kho | %s | %s' % (grp_label, wh_label),
            'res_model': 'hlv.inventory.report.line',
            'view_mode': 'list',
            'domain': [('wizard_id', '=', self.id)],
            'context': {'search_default_groupby_group': 1},
            'target': 'current',
        }

    def action_save_config(self):
        """Create or update a saved config from current wizard settings."""
        vals = {
            'group_ids': [(6, 0, self.group_ids.ids)],
            'warehouse_ids': [(6, 0, self.warehouse_ids.ids)],
            'show_zero': self.show_zero,
            'show_location_detail': self.show_location_detail,
        }
        if self.config_id:
            self.config_id.write(vals)
            msg = 'Đã cập nhật cấu hình "%s"' % self.config_id.name
        else:
            default_name = ', '.join(self.group_ids.mapped('name')[:3])
            config = self.env['hlv.inventory.report.config'].create(
                dict(name=default_name, **vals)
            )
            self.config_id = config
            msg = 'Đã lưu cấu hình mới: "%s"' % config.name
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': 'success', 'message': msg, 'sticky': False},
        }

    def action_print_pdf(self):
        return self.env.ref(
            'hlv_inventory_group_report.action_report_inventory_group_pdf'
        ).report_action(self)

    def action_preview_html(self):
        return self.env.ref(
            'hlv_inventory_group_report.action_report_inventory_group_html'
        ).report_action(self)

    def action_export_excel(self):
        try:
            import xlsxwriter
        except ImportError:
            raise UserError('Thư viện xlsxwriter chưa được cài đặt trên server.')

        data = self.get_report_data()
        columns = data['columns']
        total_cols = 3 + len(columns) + 1

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('Tồn kho')

        def fmt(**kw):
            return wb.add_format(kw)

        f_title = fmt(bold=True, font_size=14, align='center', valign='vcenter',
                      font_color='#1a2639')
        f_grp_hdr = fmt(bold=True, font_size=11, bg_color='#1a2639',
                        font_color='#ffffff', border=1, valign='vcenter')
        f_col_hdr = fmt(bold=True, bg_color='#d9e1ec', font_color='#1a2639',
                        align='center', valign='vcenter', border=1, text_wrap=True)
        f_col_tot_hdr = fmt(bold=True, bg_color='#c8e6c9', font_color='#1b5e20',
                            align='center', valign='vcenter', border=1)
        f_text = fmt(border=1)
        f_code = fmt(border=1, font_name='Courier New', font_size=9,
                     font_color='#546e7a')
        f_seq = fmt(border=1, align='center', font_color='#9e9e9e')
        f_num_pos = fmt(bold=True, num_format='#,##0.##', align='right',
                        font_color='#1b5e20', border=1)
        f_num_zero = fmt(num_format='#,##0.##', align='right',
                         font_color='#9e9e9e', border=1)
        f_total = fmt(bold=True, num_format='#,##0.##', align='right',
                      font_color='#1b5e20', bg_color='#e8f5e9', border=1)
        f_sub_lbl = fmt(bold=True, italic=True, bg_color='#e8eaf6',
                        font_color='#283593', align='right', border=1)
        f_sub_num = fmt(bold=True, num_format='#,##0.##', bg_color='#e8eaf6',
                        font_color='#283593', align='right', border=1)
        f_grand_lbl = fmt(bold=True, bg_color='#1a2639', font_color='#ffffff',
                          align='right', border=1)
        f_grand_num = fmt(bold=True, num_format='#,##0.##', bg_color='#1a2639',
                          font_color='#ffffff', align='right', border=1)
        f_grand_tot = fmt(bold=True, font_size=12, num_format='#,##0.##',
                          bg_color='#2e7d32', font_color='#ffffff',
                          align='right', border=1)

        ws.set_column(0, 0, 5)
        ws.set_column(1, 1, 14)
        ws.set_column(2, 2, 42)
        for i in range(len(columns)):
            ws.set_column(3 + i, 3 + i, 16)
        ws.set_column(3 + len(columns), 3 + len(columns), 14)

        ws.merge_range(0, 0, 1, total_cols - 1,
                       'BÁO CÁO TỒN KHO THEO NHÓM SẢN PHẨM', f_title)
        ws.set_row(0, 28)
        ws.set_row(1, 10)

        hdr_row = 2
        ws.write(hdr_row, 0, 'STT', f_col_hdr)
        ws.write(hdr_row, 1, 'Mã SP', f_col_hdr)
        ws.write(hdr_row, 2, 'Tên sản phẩm', f_col_hdr)
        for i, col in enumerate(columns):
            ws.write(hdr_row, 3 + i, col['name'], f_col_hdr)
        ws.write(hdr_row, 3 + len(columns), 'TỔNG TỒN', f_col_tot_hdr)
        ws.set_row(hdr_row, 32)

        row = hdr_row + 1

        for group_data in data['groups_data']:
            ws.merge_range(row, 0, row, total_cols - 1,
                           group_data['group'].name.upper(), f_grp_hdr)
            ws.set_row(row, 18)
            row += 1

            for idx, prod in enumerate(group_data['products']):
                ws.write(row, 0, idx + 1, f_seq)
                ws.write(row, 1, prod['product'].default_code or '', f_code)
                ws.write(row, 2, prod['product'].name, f_text)
                for i, cq in enumerate(prod['col_qtys']):
                    ws.write(row, 3 + i, cq['qty'],
                             f_num_pos if cq['qty'] > 0 else f_num_zero)
                ws.write(row, 3 + len(columns), prod['total'], f_total)
                row += 1

            ws.merge_range(row, 0, row, 2,
                           'Tổng nhóm: ' + group_data['group'].name, f_sub_lbl)
            for i, gwt in enumerate(group_data['group_col_totals']):
                ws.write(row, 3 + i, gwt['qty'], f_sub_num)
            ws.write(row, 3 + len(columns), group_data['group_total'], f_total)
            ws.set_row(row, 16)
            row += 2

        if data['multi_group']:
            ws.merge_range(row, 0, row, 2, 'TỔNG CỘNG TẤT CẢ NHÓM', f_grand_lbl)
            for i, ggt in enumerate(data['grand_col_totals']):
                ws.write(row, 3 + i, ggt['qty'], f_grand_num)
            ws.write(row, 3 + len(columns), data['grand_total'], f_grand_tot)
            ws.set_row(row, 20)

        wb.close()
        output.seek(0)
        xls_b64 = base64.b64encode(output.read()).decode()

        attachment = self.env['ir.attachment'].create({
            'name': 'bao_cao_ton_kho.xlsx',
            'type': 'binary',
            'datas': xls_b64,
            'mimetype': (
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            ),
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % attachment.id,
            'target': 'new',
        }
