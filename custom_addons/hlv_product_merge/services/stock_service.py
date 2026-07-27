# -*- coding: utf-8 -*-

from odoo import _, fields
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class ProductMergeStockMixin:
    def _source_quants(self, product):
        if not product:
            return self.env["stock.quant"]
        return self.env["stock.quant"].search(
            [
                ("product_id", "=", product.id),
                ("quantity", "!=", 0),
                ("location_id.usage", "in", ("internal", "transit")),
            ],
            order="location_id, lot_id, package_id, owner_id, id",
        )

    def _quant_line_values(self, quant, different_uom):
        return {
            "quant_id": quant.id,
            "location_id": quant.location_id.id,
            "lot_id": quant.lot_id.id,
            "package_id": quant.package_id.id,
            "owner_id": quant.owner_id.id,
            "company_id": quant.company_id.id,
            "source_quantity": quant.quantity,
            "target_quantity": 0.0 if different_uom else quant.quantity,
        }

    def _validate_company_scope(self):
        self.ensure_one()
        outside_domain = [
            ("company_id", "not in", self.env.companies.ids),
            ("product_id", "=", self.source_product_id.id),
        ]
        # A complete cross-company audit is required before archiving a shared product.
        outside_quants = self.env["stock.quant"].sudo().search_count(
            outside_domain
            + [
                ("quantity", "!=", 0),
                ("location_id.usage", "in", ("internal", "transit")),
            ]
        )
        outside_sale_lines = self.env["sale.order.line"].sudo().search_count(
            outside_domain + [("state", "not in", ("cancel", "done"))]
        )
        outside_purchase_lines = self.env["purchase.order.line"].sudo().search_count(
            outside_domain + [("state", "not in", ("cancel", "done"))]
        )
        outside_moves = self.env["stock.move"].sudo().search_count(
            outside_domain + [("state", "not in", ("cancel", "done"))]
        )
        if any((outside_quants, outside_sale_lines, outside_purchase_lines, outside_moves)):
            raise UserError(_(
                "Sản phẩm nguồn còn tồn kho hoặc chứng từ tại công ty ngoài phạm vi "
                "đang được phép truy cập. Hãy bật đủ công ty liên quan rồi thực hiện lại."
            ))

    def _validate_quant_snapshot(self):
        self.ensure_one()
        current_quants = self._source_quants(self.source_product_id)
        current_by_id = {quant.id: quant for quant in current_quants}
        line_by_quant_id = {line.quant_id.id: line for line in self.line_ids if line.quant_id}
        if len(line_by_quant_id) != len(self.line_ids):
            raise UserError(_("Danh sách tồn kho không hợp lệ. Hãy đóng và mở lại cửa sổ gộp."))
        if set(current_by_id) != set(line_by_quant_id):
            raise UserError(_(
                "Tồn kho của sản phẩm nguồn đã thay đổi sau khi mở cửa sổ. "
                "Hãy đóng và mở lại chức năng gộp để lấy số liệu mới nhất."
            ))
        for quant_id, quant in current_by_id.items():
            line = line_by_quant_id[quant_id]
            if quant.product_id != self.source_product_id:
                raise UserError(_("Có dòng tồn kho không còn thuộc sản phẩm nguồn."))
            if float_compare(
                quant.quantity,
                line.source_quantity,
                precision_rounding=self.source_product_id.uom_id.rounding,
            ):
                raise UserError(_(
                    "Tồn tại %(location)s đã đổi từ %(old)s thành %(new)s. "
                    "Hãy đóng và mở lại chức năng gộp."
                ) % {
                    "location": quant.location_id.display_name,
                    "old": self._format_qty(line.source_quantity),
                    "new": self._format_qty(quant.quantity),
                })

    def _validate_target_quantities(self):
        self.ensure_one()
        different_uom = self.base_product_id.uom_id != self.source_product_id.uom_id
        target_rounding = self.base_product_id.uom_id.rounding or 0.00001
        for line in self.line_ids:
            if not different_uom:
                line.target_quantity = line.source_quantity
            elif float_compare(
                line.target_quantity,
                0.0,
                precision_rounding=target_rounding,
            ) == 0:
                raise UserError(_(
                    "Hãy nhập số lượng quy đổi sang %(uom)s cho vị trí %(location)s."
                ) % {
                    "uom": self.base_product_id.uom_id.display_name,
                    "location": line.location_id.display_name,
                })
            elif (line.source_quantity > 0) != (line.target_quantity > 0):
                raise UserError(_(
                    "Số lượng quy đổi tại %(location)s phải cùng dấu với tồn nguồn."
                ) % {"location": line.location_id.display_name})

            tracking = self.base_product_id.tracking
            if tracking != "none" and not line.lot_id:
                raise UserError(_(
                    "Sản phẩm gốc có theo dõi lô/serial nhưng tồn nguồn tại %(location)s "
                    "không có lô. Không thể tự động gộp dòng này."
                ) % {"location": line.location_id.display_name})
            if tracking == "serial" and float_compare(
                abs(line.target_quantity),
                1.0,
                precision_rounding=target_rounding,
            ):
                raise UserError(_(
                    "Sản phẩm gốc theo dõi serial; mỗi dòng serial chỉ được quy đổi thành 1 đơn vị."
                ))

    def _copy_lot(self, old_lot):
        self.ensure_one()
        if self.base_product_id.tracking == "none" or not old_lot:
            return self.env["stock.lot"]
        lot_model = self.env["stock.lot"]
        domain = [
            ("name", "=", old_lot.name),
            ("product_id", "=", self.base_product_id.id),
        ]
        if "company_id" in lot_model._fields:
            domain.append((
                "company_id",
                "=",
                old_lot.company_id.id if old_lot.company_id else False,
            ))
        target_lot = lot_model.search(domain, limit=1)
        if target_lot:
            return target_lot
        values = {"name": old_lot.name, "product_id": self.base_product_id.id}
        if "company_id" in lot_model._fields:
            values["company_id"] = old_lot.company_id.id if old_lot.company_id else False
        return lot_model.create(values)

    def _transfer_quants(self):
        self.ensure_one()
        quant_model = self.env["stock.quant"]
        details = []
        for line in self.line_ids.sorted(
            key=lambda item: (item.location_id.complete_name or "", item.id)
        ):
            target_lot = self._copy_lot(line.lot_id)
            remaining_source_qty, _in_date = quant_model._update_available_quantity(
                self.source_product_id,
                line.location_id,
                -line.source_quantity,
                lot_id=line.lot_id,
                package_id=line.package_id,
                owner_id=line.owner_id,
            )
            if float_compare(
                remaining_source_qty,
                0.0,
                precision_rounding=self.source_product_id.uom_id.rounding,
            ):
                raise UserError(_(
                    "Tồn tại %(location)s vừa thay đổi trong lúc gộp. "
                    "Toàn bộ thao tác đã được hủy; hãy thực hiện lại."
                ) % {"location": line.location_id.display_name})
            quant_model._update_available_quantity(
                self.base_product_id,
                line.location_id,
                line.target_quantity,
                lot_id=target_lot,
                package_id=line.package_id,
                owner_id=line.owner_id,
            )
            details.append({
                "location": line.location_id.display_name,
                "lot": line.lot_id.name if line.lot_id else "",
                "source_qty": line.source_quantity,
                "target_qty": line.target_quantity,
            })
        return details

    def _archive_source(self):
        self.ensure_one()
        source = self.source_product_id
        source.write({
            "hlv_merged_into_product_id": self.base_product_id.id,
            "hlv_merged_at": fields.Datetime.now(),
            "hlv_merged_by_id": self.env.user.id,
            "hlv_merge_note": self.note or False,
            "active": False,
        })
        template = source.product_tmpl_id
        all_variants = template.with_context(active_test=False).product_variant_ids
        if template and len(all_variants) == 1:
            template.write({"active": False})
