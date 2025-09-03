# -*- coding: utf-8 -*-
# from odoo import http


# class BitsysStockLock(http.Controller):
#     @http.route('/bitsys_stock_lock/bitsys_stock_lock', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/bitsys_stock_lock/bitsys_stock_lock/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('bitsys_stock_lock.listing', {
#             'root': '/bitsys_stock_lock/bitsys_stock_lock',
#             'objects': http.request.env['bitsys_stock_lock.bitsys_stock_lock'].search([]),
#         })

#     @http.route('/bitsys_stock_lock/bitsys_stock_lock/objects/<model("bitsys_stock_lock.bitsys_stock_lock"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('bitsys_stock_lock.object', {
#             'object': obj
#         })

