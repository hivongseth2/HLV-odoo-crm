from odoo import api, models

# Maps the vendor (res.partner) field to the matching Purchase Order Studio
# field it should default onto. The PO fields are created via Odoo Studio and
# therefore may not exist in every environment, hence the _fields check below.
PARTNER_FIELD_TO_PO_STUDIO_FIELD = {
    'hlv_po_payment_term': 'x_studio_iu_kin_thanh_ton',
    'hlv_po_delivery_term': 'x_studio_delivery_term',
    'hlv_po_delivery_address': 'x_studio_ddgh',
}


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.onchange('partner_id')
    def _onchange_partner_id_hlv_default_terms(self):
        partner = self.partner_id
        for partner_field, po_field in PARTNER_FIELD_TO_PO_STUDIO_FIELD.items():
            if po_field in self._fields:
                setattr(self, po_field, partner[partner_field] if partner else False)
