# -*- coding: utf-8 -*-
from odoo import http

# class SpecialDate(http.Controller):
#     @http.route('/special_date/special_date/', auth='public')
#     def index(self, **kw):
#         return "Hello, world date"

#     @http.route('/special_date/special_date/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('special_date.listing', {
#             'root': '/special_date/special_date',
#             'objects': http.request.env['special_date.special_date'].search([]),
#         })

#     @http.route('/special_date/special_date/objects/<model("special_date.special_date"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('special_date.object', {
#             'object': obj
#         })