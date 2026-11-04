# -*- coding: utf-8 -*-
"""Dòng thay đổi đơn mua có thêm "% thuế cũ" (old_tax_rate — bên mua đổi VAT, po_proposal_change.py). Các dòng có từ
trước chưa ai đổi VAT: thuế cũ = thuế của dòng. Thiếu thì giá cũ sau VAT trong lịch sử tính theo 0% và hiện như đổi
VAT."""


def migrate(cr, version):
    cr.execute("UPDATE hlv_po_revision_line SET old_tax_rate = tax_rate WHERE old_tax_rate IS NULL OR old_tax_rate = 0")
