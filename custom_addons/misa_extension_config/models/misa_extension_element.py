# -*- coding: utf-8 -*-
# Copyright 2026 HLV
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from odoo import fields, models


class MisaExtensionElement(models.Model):
    _name = "misa.extension.element"
    _description = "Cấu hình UI element cho MISA Browser Extension"
    _order = "page_type, sequence, id"

    # ── IDENTITY ──
    name = fields.Char(
        string="Tên hiển thị",
        required=True,
        help="Label hiển thị trên UI extension. VD: 'Tạo YCMH Odoo'",
    )
    code = fields.Char(
        string="Mã element",
        required=True,
        help="Unique key để extension map sang handler. VD: 'create_pr_btn'",
    )
    _sql_constraints = [
        ("code_uniq", "unique(code)", "Mã element phải duy nhất trên toàn hệ thống!")
    ]

    # ── LOẠI ELEMENT ──
    element_type = fields.Selection(
        selection=[
            ("button", "Nút bấm (có state machine)"),
            ("status_badge", "Badge trạng thái"),
            ("status_field", "Trường trạng thái trong form"),
            ("grid_column", "Cột lưới (jsGrid)"),
            ("list_column", "Cột trang list"),
            ("skeleton", "Loading skeleton"),
            ("badge", "Badge nhỏ (vd: SL đã nhận)"),
        ],
        string="Loại element",
        required=True,
        default="button",
        help="""
            button: Nút bấm có state machine (create/syncing/synced/revoce)
            status_badge: Badge hiển thị trạng thái (đã đồng bộ/đang xử lý...)
            status_field: Trường trạng thái inject vào form "Thông tin chung"
            grid_column: Cột trong bảng jsGrid (VD: Nhà cung cấp, Tồn kho...)
            list_column: Cột trong trang list (VD: trạng thái Odoo)
            skeleton: Nút loading "Đang kiểm tra..."
            badge: Badge nhỏ (VD: SL đã nhận)
        """,
    )

    # ── PAGE ──
    page_type = fields.Selection(
        selection=[
            ("purchase_request", "Trang YCMH (MISA CRM)"),
            ("sale_order", "Trang Đơn bán hàng (MISA CRM)"),
            ("purchase_request_list", "Danh sách YCMH"),
            ("sale_order_list", "Danh sách Đơn bán hàng"),
            ("popup", "Popup Extension"),
            ("all", "Mọi trang"),
        ],
        string="Trang áp dụng",
        required=True,
        default="purchase_request",
        help="Element này chỉ hiển thị ở trang nào của MISA CRM hoặc Popup",
    )

    # ── API WIRING (dành cho element có gọi API) ──
    endpoint = fields.Char(
        string="Endpoint URL",
        help="VD: /api/extension/pr/create. Để trống nếu element không gọi API.",
    )
    http_method = fields.Selection(
        selection=[("GET", "GET"), ("POST", "POST"), ("JSONRPC", "JSON-RPC")],
        string="HTTP Method",
        default="POST",
    )
    handler_key = fields.Char(
        string="Handler Key",
        help="Map sang JS function trong handler registry của extension. "
             "VD: 'create_pr', 'check_pr', 'revoke_pr', 'suppliers_stock'",
    )

    # ── VỊ TRÍ INJECT ──
    anchor_selector = fields.Char(
        string="CSS Selector vị trí",
        help="CSS selector để tìm điểm neo inject. "
             "VD: '.listmenu, div[class*=\"listmenu\"]' cho header, "
             "'.jsgrid-header-row' cho grid column.",
    )
    anchor_strategy = fields.Selection(
        selection=[
            ("first_child", "Chèn làm con đầu tiên (insertBefore firstChild)"),
            ("append", "Chèn làm con cuối cùng (appendChild)"),
            ("before", "Chèn trước anchor"),
            ("after", "Chèn sau anchor"),
            ("replace", "Thay thế anchor"),
            ("grid_header", "Thêm làm cột header jsGrid"),
            ("grid_body", "Thêm làm cột body jsGrid"),
            ("form_field", "Thêm trường vào form (div.misa-form-group)"),
        ],
        string="Chiến lược chèn",
        default="first_child",
    )

    # ── HIỂN THỊ ──
    tooltip = fields.Char(
        string="Tooltip",
        help="Tooltip hiển thị khi hover. VD: 'Tạo YCMH trên Odoo'",
    )
    enabled = fields.Boolean(
        string="Bật",
        default=True,
        help="Bỏ tick để ẩn element này khỏi extension (không cần update extension)",
    )
    sequence = fields.Integer(
        string="Thứ tự",
        default=10,
        help="Thứ tự hiển thị (tăng dần). Dùng để sắp xếp vị trí các element cùng loại.",
    )

    # ── STYLES ──
    styles = fields.Text(
        string="Styles (JSON)",
        help="Style inline cho element dạng JSON key-value. "
             'VD: {"backgroundColor":"#2b88ff","color":"#ffffff","padding":"6px 16px"}',
    )
    state_config = fields.Text(
        string="State Config (JSON)",
        help="Dành cho element_type=button. Định nghĩa state machine của nút. "
             'VD: {"create":{"label":"Tạo YCMH","color":"#2b88ff"},'
             '"syncing":{"label":"Đang đồng bộ","color":"#f59e0b"},'
             '"synced":{"label":"Đã đồng bộ","color":"#e5e7eb"},'
             '"revoke":{"label":"Thu hồi","color":"#ef4444"}}',
    )

    # ── GRID COLUMN SPECIFIC ──
    column_config = fields.Text(
        string="Column Config (JSON)",
        help="Dành cho element_type=grid_column. Nếu null → toggle toàn bộ block grid column. "
             "Nếu có JSON → cấu hình chi tiết từng cột. "
             'VD: [{"key":"misa_supplier_id","name":"Nhà cung cấp","width":"160px","editable":true}]',
    )

    # ── TRIGGER ĐỘNG ──
    requires_data_event = fields.Char(
        string="Yêu cầu data event",
        help="Element chỉ render khi event này đã fire. "
             "VD: 'MISA_PR_DATA' — chỉ render khi đã nhận được data YCMH từ MISA.",
    )
    auto_trigger_event = fields.Char(
        string="Tự động chạy khi có event",
        help="Tự động trigger handler khi extension nhận được event này. "
             "VD: 'MISA_SO_LEDGER_SAVE' — tự động tạo SO khi người dùng 'Đề nghị ghi doanh số'.",
    )

    # ── VERSIONING ──
    version_id = fields.Many2one(
        "misa.extension.config.version",
        string="Config Version",
        help="Phiên bản config mà element này thuộc về.",
    )
    config_version = fields.Integer(
        string="Config Version #",
        related="version_id.version",
        store=True,
    )

    active = fields.Boolean(
        string="Kích hoạt",
        default=True,
        help="Ẩn element này khỏi cả Odoo lẫn extension (soft delete)",
    )