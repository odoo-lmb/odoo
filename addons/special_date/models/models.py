# -*- coding: utf-8 -*-

from odoo import models, fields, api

class special_date(models.Model):
    _name = 'special_date.date'

    date = fields.Date(
        string="特殊日期", required=True)
    options = fields.Selection([
        (1, '填写'),
        (2, '不填写'),
    ], '选项', default=1, required=True)

    _sql_constraints = [

        ('date_uniq', 'unique(date)', '特殊日期不能重复'),

    ]