from odoo import models, api


class HlvInventoryGroupReportPrint(models.AbstractModel):
    """Abstract model that feeds data into the QWeb inventory group report."""
    _name = 'report.hlv_inventory_group_report.inventory_group_report_template'
    _description = 'Inventory Group Report – QWeb renderer'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env['hlv.inventory.report.wizard'].browse(docids)
        docs = [wizard.get_report_data() for wizard in wizards]
        return {
            'doc_ids': docids,
            'doc_model': 'hlv.inventory.report.wizard',
            'docs': docs,
        }
