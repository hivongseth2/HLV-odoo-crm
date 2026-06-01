# -*- coding: utf-8 -*-
from odoo import models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def _hlv_invoice_guard_serialize_purchase(self):
        self.ensure_one()
        helper = self.env["sale.order"]
        return {
            "id": self.id,
            "name": self.name,
            "origin": self.origin or "",
            "partner": helper._hlv_invoice_guard_partner(self.partner_id),
            "currency": self.currency_id.name,
            "amount_untaxed": self.amount_untaxed,
            "amount_tax": self.amount_tax,
            "amount_total": self.amount_total,
            "lines": [
                line._hlv_invoice_guard_serialize_purchase_line()
                for line in self.order_line
                if not line.display_type
            ],
        }


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    def _hlv_invoice_guard_serialize_purchase_line(self):
        self.ensure_one()
        tax_percent = self.env["sale.order"]._hlv_invoice_guard_tax_percent(self.taxes_id)
        tax_amount = self.price_total - self.price_subtotal
        return {
            "id": self.id,
            "product_code": self.product_id.default_code or "",
            "product_name": self.product_id.display_name or self.name,
            "description": self.name or "",
            "qty": self.product_qty,
            "uom": self.product_uom.name if self.product_uom else "",
            "price_unit": self.price_unit,
            "discount": getattr(self, "discount", 0.0) or 0.0,
            "tax_percent": tax_percent,
            "subtotal": self.price_subtotal,
            "tax": tax_amount,
            "total": self.price_total,
        }
