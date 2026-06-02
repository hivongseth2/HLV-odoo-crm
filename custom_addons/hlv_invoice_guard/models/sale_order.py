# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import models
from odoo.tools import float_is_zero


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def hlv_invoice_guard_payload(self):
        self.ensure_one()
        purchase_order = self._hlv_invoice_guard_purchase_order()
        return {
            "sale_order": self._hlv_invoice_guard_serialize_sale(),
            "purchase_order": purchase_order._hlv_invoice_guard_serialize_purchase() if purchase_order else None,
        }

    def hlv_invoice_guard_check(self, crm_lines):
        self.ensure_one()
        payload = self.hlv_invoice_guard_payload()
        sale_by_code = self._hlv_invoice_guard_line_map(payload["sale_order"]["lines"])
        po_lines = (payload.get("purchase_order") or {}).get("lines") or []
        po_by_code = self._hlv_invoice_guard_line_map(po_lines)

        issues = []
        normalized_crm_lines = []
        precision = self.currency_id.rounding or 0.01

        for index, raw_line in enumerate(crm_lines or [], start=1):
            crm_line = self._hlv_invoice_guard_normalize_crm_line(raw_line, index)
            normalized_crm_lines.append(crm_line)
            code = crm_line["product_code"]
            sale_line = sale_by_code.get(code)
            po_line = po_by_code.get(code)

            if not code:
                issues.append(self._hlv_invoice_guard_issue(index, "", "product_code", "Dòng AMIS thiếu mã hàng hóa."))
                continue
            if not sale_line:
                issues.append(self._hlv_invoice_guard_issue(index, code, "product_code", "Mã hàng không có trong đơn bán Odoo."))
                continue

            self._hlv_invoice_guard_compare_number(issues, index, code, "qty", "Số lượng", crm_line["qty"], sale_line["qty"], precision)
            self._hlv_invoice_guard_compare_number(issues, index, code, "price_unit", "Đơn giá", crm_line["price_unit"], sale_line["price_unit"], precision)
            self._hlv_invoice_guard_compare_number(issues, index, code, "tax_percent", "VAT", crm_line["tax_percent"], sale_line["tax_percent"], 0.01)
            self._hlv_invoice_guard_compare_number(issues, index, code, "tax", "Tiền thuế", crm_line["tax"], sale_line["tax"], precision)
            self._hlv_invoice_guard_compare_number(issues, index, code, "total", "Tổng tiền", crm_line["total"], sale_line["total"], precision)

            if po_line:
                self._hlv_invoice_guard_compare_number(issues, index, code, "tax_percent", "VAT CRM/đơn mua", crm_line["tax_percent"], po_line["tax_percent"], 0.01, actual_label="CRM", expected_label="Đơn mua")


        return {
            **payload,
            "crm_lines": normalized_crm_lines,
            "summary": {
                "ok": not issues,
                "issue_count": len(issues),
                "checked_line_count": len(normalized_crm_lines),
            },
            "issues": issues,
        }

    def _hlv_invoice_guard_purchase_order(self):
        self.ensure_one()
        PurchaseOrder = self.env["purchase.order"].sudo()
        po = PurchaseOrder.search([("origin", "=", self.name)], limit=1)
        if po:
            return po
        return PurchaseOrder.search([("origin", "ilike", self.name)], limit=1)

    def _hlv_invoice_guard_serialize_sale(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "origin": self.origin or "",
            "partner": self._hlv_invoice_guard_partner(self.partner_id),
            "currency": self.currency_id.name,
            "amount_untaxed": self.amount_untaxed,
            "amount_tax": self.amount_tax,
            "amount_total": self.amount_total,
            "lines": [
                line._hlv_invoice_guard_serialize_sale_line()
                for line in self.order_line
                if not line.display_type
            ],
        }

    def _hlv_invoice_guard_partner(self, partner):
        return {
            "id": partner.id,
            "name": partner.display_name or "",
            "vat": partner.vat or "",
            "email": partner.email or "",
            "phone": partner.phone or partner.mobile or "",
        }

    def _hlv_invoice_guard_tax_percent(self, taxes):
        percent_taxes = taxes.filtered(lambda tax: tax.amount_type == "percent")
        return sum(percent_taxes.mapped("amount")) if percent_taxes else 0.0

    def _hlv_invoice_guard_line_map(self, lines):
        grouped = defaultdict(lambda: None)
        for line in lines:
            code = (line.get("product_code") or "").strip().upper()
            if not code:
                continue
            if grouped[code] is None:
                grouped[code] = dict(line)
                continue
            grouped[code]["qty"] += line.get("qty") or 0.0
            grouped[code]["subtotal"] += line.get("subtotal") or 0.0
            grouped[code]["tax"] += line.get("tax") or 0.0
            grouped[code]["total"] += line.get("total") or 0.0
        return grouped

    def _hlv_invoice_guard_normalize_crm_line(self, line, index):
        def as_float(value):
            if value is None or value == "":
                return None
            if isinstance(value, (int, float)):
                return float(value)
            text = str(value).strip().replace("%", "")
            text = text.replace(" ", "").replace(".", "").replace(",", ".")
            try:
                return float(text)
            except ValueError:
                return None

        return {
            "index": index,
            "product_code": (line.get("product_code") or line.get("ProductID") or "").strip().upper(),
            "description": line.get("description") or line.get("Description") or "",
            "qty": as_float(line.get("qty") or line.get("Amount")) or 0.0,
            "price_unit": as_float(line.get("price_unit") or line.get("Price")),
            "price_after_tax": as_float(line.get("price_after_tax") or line.get("PriceAfterTax")),
            "tax_percent": as_float(line.get("tax_percent") or line.get("TaxPercentID")) or 0.0,
            "subtotal": as_float(line.get("subtotal") or line.get("ToCurrency")),
            "tax": as_float(line.get("tax") or line.get("Tax")),
            "total": as_float(line.get("total") or line.get("Total")),
        }

    def _hlv_invoice_guard_compare_number(self, issues, index, code, field, label, actual, expected, precision, actual_label="AMIS", expected_label="Odoo"):
        if actual is None or expected is None:
            return
        diff = actual - expected
        if float_is_zero(diff, precision_rounding=precision):
            return
        issues.append(self._hlv_invoice_guard_issue(
            index, code, field,
            "%s lệch: %s=%s, %s=%s." % (label, actual_label, actual, expected_label, expected),
            actual=actual,
            expected=expected,
            diff=diff,
        ))

    def _hlv_invoice_guard_issue(self, index, code, field, message, actual=None, expected=None, diff=None):
        return {
            "line": index,
            "product_code": code,
            "field": field,
            "message": message,
            "actual": actual,
            "expected": expected,
            "diff": diff,
        }


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _hlv_invoice_guard_serialize_sale_line(self):
        self.ensure_one()
        helper = self.env["sale.order"]
        tax_percent = helper._hlv_invoice_guard_tax_percent(self.tax_id)
        price_after_tax = self.price_unit * (1.0 + tax_percent / 100.0)
        tax_amount = self.price_total - self.price_subtotal
        return {
            "id": self.id,
            "product_code": self.product_id.default_code or "",
            "product_name": self.product_id.display_name or self.name,
            "description": self.name or "",
            "qty": self.product_uom_qty,
            "uom": self.product_uom.name if self.product_uom else "",
            "price_unit": self.price_unit,
            "price_after_tax": price_after_tax,
            "discount": self.discount,
            "tax_percent": tax_percent,
            "subtotal": self.price_subtotal,
            "tax": tax_amount,
            "total": self.price_total,
        }
