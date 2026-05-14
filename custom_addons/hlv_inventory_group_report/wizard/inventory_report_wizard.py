from odoo import models, fields, api
from odoo.exceptions import UserError


class HlvInventoryReportWizard(models.TransientModel):
    _name = 'hlv.inventory.report.wizard'
    _description = 'Báo cáo tồn kho theo nhóm sản phẩm'

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
        help='Bật để hiển thị cả sản phẩm không có tồn kho tại kho đã chọn',
    )

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _get_warehouses(self):
        return self.warehouse_ids or self.env['stock.warehouse'].search([])

    def get_report_data(self):
        """Compute structured data consumed by the QWeb report template."""
        warehouses = self._get_warehouses()
        groups_data = []
        grand_wh_totals = {wh.id: 0.0 for wh in warehouses}
        grand_total = 0.0

        for group in self.group_ids.sorted('sequence'):
            products_data = []
            group_wh_totals = {wh.id: 0.0 for wh in warehouses}
            group_total = 0.0

            for product in group.product_ids.sorted('default_code'):
                warehouse_qtys = []
                total = 0.0
                for wh in warehouses:
                    qty = product.with_context(warehouse=wh.id).qty_available
                    warehouse_qtys.append({'warehouse': wh, 'qty': qty})
                    total += qty
                    group_wh_totals[wh.id] = group_wh_totals.get(wh.id, 0.0) + qty

                group_total += total

                if not self.show_zero and total == 0:
                    continue

                products_data.append({
                    'product': product,
                    'warehouse_qtys': warehouse_qtys,
                    'total': total,
                })

            # Accumulate grand totals
            for wh in warehouses:
                grand_wh_totals[wh.id] += group_wh_totals[wh.id]
            grand_total += group_total

            groups_data.append({
                'group': group,
                'products': products_data,
                'group_wh_totals': [
                    {'warehouse': wh, 'qty': group_wh_totals[wh.id]}
                    for wh in warehouses
                ],
                'group_total': group_total,
            })

        return {
            'wizard': self,
            'warehouses': warehouses,
            'groups_data': groups_data,
            'grand_wh_totals': [
                {'warehouse': wh, 'qty': grand_wh_totals[wh.id]}
                for wh in warehouses
            ],
            'grand_total': grand_total,
            'multi_group': len(self.group_ids) > 1,
        }

    # -----------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------

    def action_print_pdf(self):
        return self.env.ref(
            'hlv_inventory_group_report.action_report_inventory_group_pdf'
        ).report_action(self)

    def action_preview_html(self):
        return self.env.ref(
            'hlv_inventory_group_report.action_report_inventory_group_html'
        ).report_action(self)
