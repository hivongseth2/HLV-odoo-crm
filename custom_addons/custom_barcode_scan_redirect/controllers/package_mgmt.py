# -*- coding: utf-8 -*-
"""Package management routes: create, unpack, transfer, edit, print labels."""
from odoo import http
from odoo.http import request
from werkzeug.utils import redirect
import logging

_logger = logging.getLogger(__name__)


class PackageManagementController(http.Controller):

    # ===================== PARTIAL PACK MANAGEMENT =====================

    @http.route('/pack_scan/create_partial_pack', type='json', auth='user', csrf=False)
    def create_partial_pack(self, **kwargs):
        """Tạo gói hàng từ các move_line hoàn tất trong picking"""
        picking_id = kwargs.get("picking_id")
        move_line_data = kwargs.get("move_line_data", [])
        package_barcode = kwargs.get('package_barcode')

        _logger.info(f"CREATE_PARTIAL_PACK: picking_id={picking_id}, items={len(move_line_data)}")

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            _logger.error(f"CREATE_PARTIAL_PACK: Picking {picking_id} không tồn tại")
            return {"error": "Phiếu không tồn tại"}

        try:
            result = picking.create_partial_pack(move_line_data, package_name=package_barcode)
            _logger.info(f"CREATE_PARTIAL_PACK: Success! New package: {result['package_name']} (ID: {result['package_id']})")
            return {
                "success": True,
                "package_id": result['package_id'],
                "package_name": result['package_name'],
                "message": f"✅ Tạo gói hàng {result['package_name']} thành công!"
            }
        except Exception as e:
            _logger.exception("CREATE_PARTIAL_PACK error")
            return {"error": str(e)}

    @http.route('/pack_scan/unpack', type='json', auth='user', csrf=False)
    def unpack_pack(self, **kwargs):
        """Unpack: chuyển items từ partial pack về picking gốc"""
        picking_id = kwargs.get("picking_id")

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            picking.unpack_partial()
            return {
                "success": True,
                "message": f"✅ Unpack {picking.name} thành công!"
            }
        except Exception as e:
            _logger.exception("UNPACK error")
            return {"error": str(e)}

    @http.route('/pack_scan/unpack_all', type='json', auth='user', csrf=False)
    def unpack_all(self, **kwargs):
        """
        Bỏ đóng gói toàn bộ: unreserve → chuyển quant ra khỏi package → xóa
        package trên move_lines → re-reserve.
        """
        picking_id = kwargs.get("picking_id")
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            mls = picking.move_line_ids.filtered(
                lambda l: l.package_id or l.result_package_id
            )
            if not mls:
                return {"success": True, "message": "Không có dòng nào cần bỏ đóng gói."}

            count = len(mls)
            location = picking.location_id

            # 1. Thu thập packages liên quan
            packages = mls.mapped('package_id') | mls.mapped('result_package_id')
            packages = packages.filtered(lambda p: p)

            # 2. Unreserve picking trước
            picking.do_unreserve()
            _logger.info("UNPACK_ALL %s: unreserved", picking.name)

            # 2b. Reset qty_done trên các dòng còn lại (quét rồi nhưng chưa đóng gói)
            remaining = picking.move_line_ids.filtered(lambda l: l.qty_done > 0)
            if remaining:
                remaining.sudo().with_context(skip_qty_validation=True).write({'qty_done': 0})
                _logger.info("UNPACK_ALL %s: reset %d loose scanned lines to 0", picking.name, len(remaining))

            # 3. Chuyển quant ra khỏi package
            Quant = request.env['stock.quant'].sudo()
            for pkg in packages:
                pkg_quants = Quant.search([
                    ('package_id', '=', pkg.id),
                    ('location_id', '=', location.id),
                    ('quantity', '!=', 0),
                ])
                for q in pkg_quants:
                    existing = Quant.search([
                        ('product_id', '=', q.product_id.id),
                        ('location_id', '=', q.location_id.id),
                        ('lot_id', '=', q.lot_id.id if q.lot_id else False),
                        ('package_id', '=', False),
                        ('owner_id', '=', q.owner_id.id if q.owner_id else False),
                    ], limit=1)
                    if existing:
                        existing.quantity += q.quantity
                    else:
                        Quant.create({
                            'product_id': q.product_id.id,
                            'location_id': q.location_id.id,
                            'lot_id': q.lot_id.id if q.lot_id else False,
                            'package_id': False,
                            'owner_id': q.owner_id.id if q.owner_id else False,
                            'quantity': q.quantity,
                        })
                    q.quantity = 0
                _logger.info("UNPACK_ALL: moved quants out of package %s", pkg.name)

            # 4. Xóa package trên move_lines
            mls.write({'package_id': False, 'result_package_id': False})

            # 5. Re-reserve picking
            picking.action_assign()
            _logger.info(
                "UNPACK_ALL %s: cleared %d move_lines, re-assigned",
                picking.name, count,
            )
            return {
                "success": True,
                "message": f"✅ Đã bỏ đóng gói {count} dòng trong {picking.name}",
            }
        except Exception as e:
            _logger.exception("UNPACK_ALL error")
            return {"error": str(e)}

    # ===================== ADD / TRANSFER =====================

    @http.route('/pack_scan/add_to_pack', type='json', auth='user', csrf=False)
    def add_to_pack(self, **kwargs):
        """Thêm items vào pack từ picking gốc"""
        picking_id = kwargs.get("picking_id")
        move_line_data = kwargs.get("move_line_data", [])

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            picking.add_to_pack(move_line_data)
            return {
                "success": True,
                "message": "✅ Thêm sản phẩm vào pack thành công!"
            }
        except Exception as e:
            _logger.exception("ADD_TO_PACK error")
            return {"error": str(e)}

    @http.route('/pack_scan/transfer_pack_item', type='json', auth='user', csrf=False)
    def transfer_pack_item(self, **kwargs):
        """Chuyển items từ pack này sang pack khác"""
        picking_id = kwargs.get("picking_id")
        target_pack_id = kwargs.get("target_pack_id")
        move_line_data = kwargs.get("move_line_data", [])

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Pack nguồn không tồn tại"}

        try:
            picking.transfer_pack_item(target_pack_id, move_line_data)
            return {
                "success": True,
                "message": "✅ Chuyển sản phẩm sang pack khác thành công!"
            }
        except Exception as e:
            _logger.exception("TRANSFER_PACK_ITEM error")
            return {"error": str(e)}

    # ===================== PRINT LABELS =====================

    @http.route('/pack_scan/print_label', type='json', auth='user', csrf=False)
    def print_label(self, **kwargs):
        picking_id = kwargs.get("picking_id")

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            request.env.ref('hlv_pack_sequence.action_report_simple_package_labels').sudo()
            return {
                "success": True,
                "report_url": f"/report/pdf/hlv_pack_sequence.report_simple_package_label_document/{picking_id}",
                "message": "✅ Đang chuẩn bị in nhãn..."
            }
        except Exception as e:
            _logger.exception("PRINT_LABEL error")
            return {"error": str(e)}

    @http.route('/pack_scan/print_label_80x80', type='json', auth='user', csrf=False)
    def print_label_80x80(self, **kwargs):
        picking_id = kwargs.get("picking_id")

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            return {
                "success": True,
                "report_url": f"/report/pdf/hlv_pack_sequence.report_package_label_document/{picking_id}",
                "message": "✅ Đang chuẩn bị in nhãn 80x80..."
            }
        except Exception as e:
            _logger.exception("PRINT_LABEL_80X80 error")
            return {"error": str(e)}

    # ===================== PACKAGE EDIT MANAGEMENT =====================

    @http.route('/pack_scan/get_package_details', type='json', auth='user', csrf=False)
    def get_package_details(self, **kwargs):
        """Lấy chi tiết sản phẩm trong 1 package để hiển thị modal edit"""
        picking_id = int(kwargs.get("picking_id") or 0)
        package_id = int(kwargs.get("package_id") or 0)

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            result = picking.get_package_details(package_id)
            return result
        except Exception as e:
            _logger.exception("GET_PACKAGE_DETAILS error")
            return {"error": str(e)}

    @http.route('/pack_scan/update_package_item_qty', type='json', auth='user', csrf=False)
    def update_package_item_qty(self, **kwargs):
        """Cập nhật số lượng của 1 sản phẩm trong package"""
        picking_id = kwargs.get("picking_id")
        package_id = kwargs.get("package_id")
        move_line_id = kwargs.get("move_line_id")
        new_qty = kwargs.get("new_qty", 0)

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            result = picking.update_package_item_qty(package_id, move_line_id, new_qty)
            return result
        except Exception as e:
            _logger.exception("UPDATE_PACKAGE_ITEM_QTY error")
            return {"error": str(e)}

    @http.route('/pack_scan/remove_package_item', type='json', auth='user', csrf=False)
    def remove_package_item(self, **kwargs):
        """Xoá 1 sản phẩm khỏi package"""
        picking_id = kwargs.get("picking_id")
        package_id = kwargs.get("package_id")
        move_line_id = kwargs.get("move_line_id")

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            result = picking.remove_package_item(package_id, move_line_id)
            return result
        except Exception as e:
            _logger.exception("REMOVE_PACKAGE_ITEM error")
            return {"error": str(e)}

    @http.route('/pack_scan/transfer_item_between_packs', type='json', auth='user', csrf=False)
    def transfer_item_between_packs(self, **kwargs):
        """Chuyển 1 sản phẩm từ package này sang package khác"""
        picking_id = kwargs.get("picking_id")
        source_package_id = kwargs.get("source_package_id")
        target_package_id = kwargs.get("target_package_id")
        move_line_id = kwargs.get("move_line_id")
        qty = kwargs.get("qty", 0)

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            result = picking.transfer_package_item(source_package_id, target_package_id, move_line_id, qty)
            return result
        except Exception as e:
            _logger.exception("TRANSFER_ITEM_BETWEEN_PACKS error")
            return {"error": str(e)}

    @http.route('/pack_scan/add_item_to_package', type='json', auth='user', csrf=False)
    def add_item_to_package(self, **kwargs):
        """Thêm sản phẩm vào package (bổ sung sau)"""
        picking_id = kwargs.get("picking_id")
        package_id = kwargs.get("package_id")
        move_line_id = kwargs.get("move_line_id")
        qty = kwargs.get("qty", 0)

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            result = picking.add_item_to_package(package_id, move_line_id, qty)
            return result
        except Exception as e:
            _logger.exception("ADD_ITEM_TO_PACKAGE error")
            return {"error": str(e)}

    @http.route('/pack_scan/split_package', type='json', auth='user', csrf=False)
    def split_package(self, **kwargs):
        """Tách 1 package thành phiếu riêng"""
        picking_id = kwargs.get('picking_id')
        package_id = kwargs.get('package_id')

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        try:
            result = picking.split_package_to_new_picking(package_id)
            return {
                'success': True,
                'new_picking_id': result['picking_id'],
                'new_picking_name': result['picking_name'],
                'message': f"✅ Đã tách {result['picking_name']} thành công!"
            }
        except Exception as e:
            _logger.exception('SPLIT_PACKAGE error')
            return {"error": str(e)}

    # ===================== GDRIVE DISCONNECT =====================

    @http.route('/gdrive/oauth2/disconnect', type='http', auth='user', website=True, csrf=False)
    def disconnect(self, **kw):
        request.env['ir.config_parameter'].sudo().set_param('gdrive.user_credentials_json', '')
        return redirect('/gdrive/oauth2/start')
