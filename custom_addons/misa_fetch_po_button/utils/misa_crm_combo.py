# -*- coding: utf-8 -*-
"""Đọc và SỬA combo trên MISA CRM.

Mở rộng ``misa.api.utils`` (cùng model, người gọi không đổi gì) nhưng nằm file riêng:
misa_api_utils.py đã quá dài. Payload dựng bằng hàm thuần trong crm_combo_payload.

Luồng sửa, bắt chước đúng màn hình CRM:
    FormDataNew/Product/128/4      đọc phần đầu combo (+ ModifiedDate, Version)
    GetDataSubFormByID/<id>/2/null đọc các dòng con (+ ID, AsyncID của từng dòng)
    POST /Product                  lưu, MISAEntityState 2, từng dòng mang trạng thái riêng
"""
import logging

from odoo import models

from .crm_combo_payload import build_combo_update_payload, diff_combo_rows

_logger = logging.getLogger(__name__)

_CRM = "https://amisapp.misa.vn/crm/g2/api/business/Product"
_COMBO_LAYOUT_ID = 128
# Đúng body màn hình CRM gửi khi mở combo để sửa; thiếu cột ID / AsyncID là không lưu được.
_SUBFORM_BODY = [{
    "ColumnFieldSubForm": "ProductID,ProductIDText,ProductCode,Description,UnitID,UnitIDText,Amount,ID,AsyncID",
    "ColumnAggregateSubForm": "AmountSummary,ID",
    "TableName": "set_product",
    "IsSystem": True,
    "ParentIDKey": "CustomID",
    "IsBringSerialType": False,
}]


class MisaCrmCombo(models.AbstractModel):
    _inherit = 'misa.api.utils'

    def _crm_read(self, url, body, headers, what):
        """POST đọc dữ liệu CRM, đổi token một lần nếu hết hạn. Trả ``Data``, raise nếu lỗi."""
        session = self._get_retry_session()
        response = session.post(url, headers=headers, json=body, timeout=30)
        if response.status_code in (401, 403):
            headers.update(self._get_cached_crm_headers(force_refresh=True))
            headers.update({"layoutcode": "product", "x-misa-language": "vi-VN"})
            response = session.post(url, headers=headers, json=body, timeout=30)
        try:
            data = response.json()
        except Exception as exc:
            raise Exception(f"MISA CRM trả dữ liệu lạ khi đọc {what} (HTTP {response.status_code})") from exc
        if not response.ok or not data.get("Success"):
            raise Exception(f"Không đọc được {what}: {data.get('UserMessage') or response.text[:300]}")
        return data.get("Data")

    def _get_crm_combo_form(self, misa_id, headers):
        """Phần đầu combo (CurrentData của FormDataNew). Raise nếu CRM không trả."""
        data = self._crm_read(
            f"{_CRM}/FormDataNew/Product/{_COMBO_LAYOUT_ID}/4",
            {"ID": str(misa_id), "MISAEntityState": 2, "ActiveLayoutCode": None, "CustomDicData": None},
            headers, f"combo MISA ID {misa_id}",
        ) or {}
        current = data.get("CurrentData") if isinstance(data, dict) else None
        if not isinstance(current, dict) or not current.get("ID"):
            raise Exception(f"MISA CRM không trả thông tin combo MISA ID {misa_id}")
        return current

    def _get_crm_combo_rows(self, misa_id, headers):
        """Các dòng con hiện tại của combo (có ID, AsyncID từng dòng)."""
        data = self._crm_read(
            f"{_CRM}/GetDataSubFormByID/{misa_id}/2/null", _SUBFORM_BODY,
            headers, f"thành phần combo MISA ID {misa_id}",
        ) or []
        table = next((t for t in data if isinstance(t, dict) and t.get("TableName") == "set_product"), {})
        return table.get("DataFieldSubForm") or []

    def _sync_combo_to_odoo(self, code, name, unit_name, components):
        """Tạo / cập nhật sản phẩm combo + BOM kit trên Odoo cho khớp thành phần MISA.

        Dùng lại get_or_create_combo_product của luồng import đơn (không có cách dựng BOM
        thứ hai): nó tạo combo nếu chưa có, chuyển thành hàng lưu kho, rồi XOÁ dòng BOM
        cũ và ghi lại theo danh sách con. Mã con chưa có trên Odoo được nó tạo luôn.
        Gọi với số lượng combo = 1 nên số lượng con là số lượng trong 1 combo.

        Trả: ``{'odoo_synced': bool, 'odoo_note': str | None}``. Không bao giờ raise:
        MISA đã ghi xong, lỗi phía Odoo chỉ được báo lại, không được làm mất kết quả MISA.
        """
        combo_data = {'ProductIDText': code, 'Description': name or code,
                      'UnitIDText': unit_name or 'Bộ', 'Amount': 1.0}
        children = [{
            'ProductIDText': (item.get('code') or '').strip(),
            'Description': item.get('name') or item.get('code'),
            'UnitIDText': item.get('unit_name') or 'Cái',
            'Amount': float(item.get('quantity') or 0.0),
            'Price': 0.0,
        } for item in components]
        try:
            with self.env.cr.savepoint():
                product = self.get_or_create_combo_product(combo_data, children)
        except Exception as error:
            _logger.exception("Đồng bộ combo %s xuống Odoo lỗi", code)
            return {'odoo_synced': False, 'odoo_note': f"Odoo chưa cập nhật combo/BOM: {error}"}
        if not product:
            return {'odoo_synced': False, 'odoo_note': "Odoo chưa cập nhật combo/BOM (không tạo được sản phẩm)."}
        return {'odoo_synced': True, 'odoo_note': None}

    def get_combo_misa(self, code):
        """Thành phần hiện tại của combo theo mã.

        Trả: ``{'misa_id', 'code', 'name', 'price', 'components': [{'code', 'name',
            'quantity', 'unit'}]}``. Raise khi mã không có hoặc không phải combo.
        """
        code = str(code or "").strip()
        headers = self._get_cached_crm_headers()
        headers.update({"layoutcode": "product", "x-misa-language": "vi-VN"})
        existing = self._find_exact_crm_product_by_code(code, headers=headers) if code else None
        if not existing:
            raise Exception(f"Không có mã {code} trên MISA CRM")
        if not existing.get("is_combo"):
            raise Exception(f"Mã {code} trên CRM không phải Combo")
        current = self._get_crm_combo_form(existing["misa_id"], headers)
        rows = self._get_crm_combo_rows(existing["misa_id"], headers)
        return {
            "misa_id": str(existing["misa_id"]),
            "code": (current.get("ProductCode") or code).strip(),
            "name": current.get("ProductName"),
            "price": current.get("UnitPrice"),
            "components": [{
                "code": (row.get("ProductCode") or "").strip(),
                "name": row.get("Description") or row.get("ProductName"),
                "quantity": float(row.get("Amount") or 0.0),
                "unit": row.get("UnitIDText"),
            } for row in rows],
        }

    def update_combo_product_misa(self, code, components=None, name=None, price=None, price_pu=None):
        """Sửa combo đã có trên CRM.

        Nhận:
            code: mã combo (tra CRM theo mã chính xác).
            components: danh sách thành phần MỚI ĐẦY ĐỦ ``[{'code', 'quantity'}]`` — hàng nào
                không có trong danh sách là bị xoá khỏi combo. None = không đổi thành phần.
            name / price / price_pu: None = giữ nguyên.
        Trả: ``{'id', 'changed', 'changes', 'header', 'odoo_synced', 'odoo_note'}``;
            changes = thêm / xoá / đổi số lượng (xem diff_combo_rows), header = các trường
            phần đầu đã đổi; odoo_* = kết quả ghi lại combo + BOM kit trên Odoo.
        Biên: không có gì khác bản hiện tại -> không gửi lên CRM, ``changed`` False, nhưng
            BOM Odoo vẫn được ghi lại theo MISA.
        Raise khi: mã không có / không phải combo; danh sách mới rỗng; mã con không có trên
            CRM; CRM từ chối (vd có người vừa sửa combo này — MISA kiểm ModifiedDate/Version).
        """
        code = str(code or "").strip()
        if not code:
            raise Exception("Thiếu mã combo")
        if components is not None and not components:
            raise Exception(f"Combo {code} phải còn ít nhất một sản phẩm con")

        headers = self._get_cached_crm_headers()
        headers.update({"layoutcode": "product", "x-misa-language": "vi-VN"})
        existing = self._find_exact_crm_product_by_code(code, headers=headers)
        if not existing:
            raise Exception(f"Không có mã {code} trên MISA CRM")
        if not existing.get("is_combo"):
            raise Exception(f"Mã {code} trên CRM không phải Combo")
        misa_id = existing["misa_id"]

        current = self._get_crm_combo_form(misa_id, headers)
        rows = self._get_crm_combo_rows(misa_id, headers)
        if components is None:
            # Giữ nguyên thành phần: so bộ dòng hiện tại với chính nó -> mọi dòng state 0.
            components = [{"code": row.get("ProductCode"), "quantity": row.get("Amount")} for row in rows]
        resolved = self._resolve_crm_combo_components(code, components, headers)
        data_rows, old_data, amount_summary, changes = diff_combo_rows(rows, resolved)

        header = {}
        if name and name.strip() != (current.get("ProductName") or ""):
            header["ProductName"] = name.strip()
        if price is not None and float(price) != float(current.get("UnitPrice") or 0):
            header["UnitPrice"] = float(price)
        if price_pu is not None and float(price_pu) != float(current.get("PurchasedPrice") or 0):
            header["PurchasedPrice"] = float(price_pu)

        if not header and not any(changes.values()):
            saved_id, changed = str(misa_id), False
        else:
            payload = build_combo_update_payload(current, data_rows, old_data, amount_summary, header)
            saved_id, changed = self._save_crm_product(payload, code, headers), True
            _logger.info("Sửa combo CRM %s (ID=%s): %s %s", code, saved_id, changes, header)
        # Ghi lại BOM Odoo theo đúng danh sách MISA kể cả khi MISA không đổi gì: lần đó
        # chính là lúc sửa được một BOM Odoo đã lệch từ trước.
        odoo = self._sync_combo_to_odoo(
            code, header.get("ProductName") or current.get("ProductName"),
            current.get("UsageUnitIDText"), resolved)
        return dict(odoo, id=saved_id, changed=changed, changes=changes, header=header)
