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
        Sử dụng sudo() để đảm bảo quyền truy cập và render báo cáo.
        """
        try:
            # Sử dụng sudo() vì TransientModel có thể bị hạn chế truy cập từ controller
            wizard = request.env['hlv.smart.print.wizard'].sudo().browse(wizard_id)
            if not wizard.exists() or not wizard.report_line_ids:
                return request.not_found()

            picking = wizard.picking_id
            pdfs = []
            
            # Khởi tạo công cụ render báo cáo
            Report = request.env['ir.actions.report'].sudo()
            
            for line in wizard.report_line_ids:
                # Render nội dung PDF
                # Trong Odoo, _render_qweb_pdf cần report_ref (ID hoặc xml_id) làm tham số đầu tiên
                pdf_content, _ = Report._render_qweb_pdf(line.report_id.id, res_ids=picking.ids)
                
                if pdf_content:
                    for _ in range(line.copies):
                        pdfs.append(pdf_content)

            if not pdfs:
                return request.make_response("Không có nội dung báo cáo để in.", headers=[('Content-Type', 'text/plain')])

            # Gộp các tệp PDF lại
            merged_pdf = merge_pdf(pdfs)
            
            # Tạo tên file gợi nhớ
            filename = "Bien_ban_%s.pdf" % (picking.name.replace('/', '_'))
            
            return request.make_response(merged_pdf, headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', 'inline; filename="%s"' % filename)
            ])
        except Exception as e:
            # Trả về lỗi chi tiết hơn nếu có thể (chỉ cho dev/test) hoặc log lại
            return request.make_response("Lỗi hệ thống khi in: %s" % str(e), status=500)
