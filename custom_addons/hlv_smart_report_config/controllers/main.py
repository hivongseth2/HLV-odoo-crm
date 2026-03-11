# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request, content_disposition
from odoo.tools.pdf import merge_pdf
import io

class HlvSmartPrintController(http.Controller):

    @http.route('/hlv_smart/print_merged/<int:wizard_id>', type='http', auth='user')
    def print_merged(self, wizard_id, **kw):
        """
        Gộp tất cả các biên bản và số lượng bản in thành một file PDF duy nhất.
        """
        wizard = request.env['hlv.smart.print.wizard'].browse(wizard_id)
        if not wizard.exists() or not wizard.report_line_ids:
            return request.not_found()

        picking = wizard.picking_id
        pdfs = []
        
        for line in wizard.report_line_ids:
            # Render từng biên bản (loại PDF)
            # res_ids nhận vào một danh sách ID
            pdf_content, _ = line.report_id._render_qweb_pdf(res_ids=picking.ids)
            
            # Thêm vào danh sách gộp dựa trên số lượng bản in (copies)
            for _ in range(line.copies):
                pdfs.append(pdf_content)

        if not pdfs:
            return request.not_found()

        # Gộp các tệp PDF lại
        merged_pdf = merge_pdf(pdfs)
        
        # Tạo tên file
        filename = "Bien_ban_%s.pdf" % (picking.name.replace('/', '_'))
        
        return request.make_response(merged_pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', content_disposition(filename))
        ])
