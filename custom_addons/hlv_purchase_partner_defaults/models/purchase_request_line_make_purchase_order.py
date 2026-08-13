from odoo import models

from .purchase_order import PARTNER_FIELD_TO_PO_STUDIO_FIELD


class PurchaseRequestLineMakePurchaseOrder(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order"

    def _prepare_purchase_order(self, picking_type, group_id, company, origin, supplier):
        data = super()._prepare_purchase_order(
            picking_type, group_id, company, origin, supplier
        )
        po_fields = self.env["purchase.order"]._fields
        for partner_field, po_field in PARTNER_FIELD_TO_PO_STUDIO_FIELD.items():
            if po_field in po_fields:
                data[po_field] = supplier[partner_field]
        return data
