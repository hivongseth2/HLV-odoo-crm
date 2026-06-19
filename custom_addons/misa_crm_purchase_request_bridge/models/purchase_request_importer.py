# -*- coding: utf-8 -*-
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MisaCrmPurchaseRequestImporter(models.AbstractModel):
    _name = "misa.crm.purchase.request.importer"
    _description = "MISA CRM Purchase Request Importer"

    @api.model
    def import_payload(self, payload):
        data = payload.get("purchase_request") or payload.get("data") or payload
        lines = data.get("lines") or payload.get("lines") or []

        crm_number = self._clean(
            data.get("PurchaseRequestNo")
            or data.get("purchase_request_no")
            or data.get("number")
        )
        if not crm_number:
            raise ValidationError(_("Missing PurchaseRequestNo"))
        if not lines:
            raise ValidationError(_("Purchase request has no product lines"))

        existing = self.env["purchase.request"].sudo().search(
            [("origin", "=", crm_number)], limit=1
        )
        if existing and not data.get("overwrite"):
            return {
                "created": False,
                "purchase_request_id": existing.id,
                "purchase_request_name": existing.name,
                "message": "Purchase request already exists",
            }
        if existing and existing.state != "draft":
            raise ValidationError(
                _("Existing purchase request %s is not draft") % existing.display_name
            )

        line_commands = self._prepare_line_commands(lines, data)
        request_vals = self._prepare_request_vals(data, crm_number, line_commands)

        if existing:
            existing.line_ids.unlink()
            existing.write(request_vals)
            pr = existing
            created = False
        else:
            pr = self.env["purchase.request"].sudo().create(request_vals)
            created = True

        body = self._build_chatter_note(data, len(line_commands))
        pr.message_post(body=body)

        if data.get("submit_for_approval"):
            pr.button_to_approve()

        return {
            "created": created,
            "purchase_request_id": pr.id,
            "purchase_request_name": pr.name,
            "line_count": len(pr.line_ids),
            "state": pr.state,
        }

    def _prepare_request_vals(self, data, crm_number, line_commands):
        description_parts = []
        for label, key in (
            ("Purpose", "PurchasePurpose"),
            ("Delivery address", "DeliveryAddress"),
            ("CRM sale order", "SaleOrderNo"),
            ("CRM process", "ProcessID"),
        ):
            value = self._clean(data.get(key))
            if value:
                description_parts.append("%s: %s" % (label, value))

        crm_description = self._clean(data.get("Description"))
        if crm_description:
            description_parts.append(crm_description)

        vals = {
            "origin": crm_number,
            "description": "\n".join(description_parts),
            "line_ids": line_commands,
        }

        request_date = self._parse_date(data.get("RequestDate"))
        if request_date:
            vals["date_start"] = request_date

        assigned_user = self._find_user(data.get("OwnerText") or data.get("OwnerIDText"))
        vals["requested_by"] = (assigned_user or self._fallback_requested_by()).id

        picking_type = self._default_incoming_picking_type()
        if picking_type:
            vals["picking_type_id"] = picking_type.id

        return vals

    def _prepare_line_commands(self, lines, data):
        commands = []
        missing_codes = []
        date_required = (
            self._parse_date(data.get("DesiredDeliveryDeadline"))
            or self._parse_date(data.get("RequestDate"))
            or fields.Date.context_today(self)
        )

        for index, item in enumerate(lines, start=1):
            code = self._clean(
                item.get("ProductIDText")
                or item.get("product_code")
                or item.get("default_code")
            )
            description = self._clean(
                item.get("Description") or item.get("description") or item.get("name")
            )
            qty = self._parse_float(item.get("Amount") or item.get("quantity") or 0.0)

            if not code and not description:
                continue
            if qty <= 0:
                continue

            product = self._find_product(code, description)
            if not product:
                missing_codes.append(code or description or ("line %s" % index))
                continue

            commands.append(
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "name": description or product.display_name,
                        "product_qty": qty,
                        "product_uom_id": product.uom_id.id,
                        "date_required": date_required,
                    },
                )
            )

        if missing_codes:
            raise ValidationError(
                _("Products not found in Odoo by default_code/name: %s")
                % ", ".join(missing_codes)
            )
        if not commands:
            raise ValidationError(_("No valid product lines found"))
        return commands

    def _find_product(self, code, description):
        Product = self.env["product.product"].sudo()
        if code:
            product = Product.search([("default_code", "=", code)], limit=1)
            if product:
                return product
        if description:
            return Product.search([("name", "ilike", description)], limit=1)
        return Product.browse()

    def _find_user(self, text):
        text = self._clean(text)
        if not text:
            return self.env["res.users"].browse()
        login = ""
        if "(" in text and ")" in text:
            login = text.split("(", 1)[1].split(")", 1)[0]
        Users = self.env["res.users"].sudo()
        if login:
            user = Users.search([("login", "ilike", login)], limit=1)
            if user:
                return user
        return Users.search([("name", "ilike", text.split(" (", 1)[0])], limit=1)

    def _default_incoming_picking_type(self):
        PickingType = self.env["stock.picking.type"].sudo()
        company = self.env.company
        picking_type = PickingType.search(
            [("code", "=", "incoming"), ("warehouse_id.company_id", "=", company.id)],
            limit=1,
        )
        if not picking_type:
            picking_type = PickingType.search(
                [("code", "=", "incoming"), ("warehouse_id", "=", False)],
                limit=1,
            )
        return picking_type

    def _fallback_requested_by(self):
        return (
            self.env.ref("base.user_admin", raise_if_not_found=False)
            or self.env.user
        )

    @staticmethod
    def _clean(value):
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _parse_float(value):
        if value in (None, ""):
            return 0.0
        text = str(value).strip().replace(" ", "")
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_date(value):
        if not value:
            return False
        raw = str(value).strip()
        formats = (
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%d/%m/%Y",
            "%d/%m/%Y %H:%M:%S",
            "%d-%m-%Y",
        )
        for fmt in formats:
            try:
                return datetime.strptime(raw[:26], fmt).date()
            except ValueError:
                continue
        return False

    def _build_chatter_note(self, data, line_count):
        source_url = self._clean(data.get("source_url"))
        parts = [
            "Imported from MISA CRM purchase request page.",
            "CRM request: %s" % self._clean(data.get("PurchaseRequestNo")),
            "Lines: %s" % line_count,
        ]
        if source_url:
            parts.append("Source URL: %s" % source_url)
        return "<br/>".join(parts)

