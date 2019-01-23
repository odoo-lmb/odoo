#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2019/1/22 16:51
# @Author  : youqingkui
# @File    : special_date.py
# @Desc    :

from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)

class SpecialDate(models.Model):
    _name = 'timesheet.special_date'

    date = fields.Date(
        string="特殊日期", required=True)
    options = fields.Selection([
        (1, '填写'),
        (2, '不填写'),
    ], '选项', default=1, required=True)

    _sql_constraints = [

        ('date_uniq', 'unique(date)', '特殊日期不能重复'),

    ]


    @api.model
    def create(self, values):
        if values.get('date') and values.get('options')==2:
            _logger.info("debug speciak all data %s"%self.env['account.analytic.line'].search(
                [('date', '=', values.get('date')),('is_fake_data','!=',False)]))
            rst =self.env['account.analytic.line'].search(
                [('date', '=', values.get('date')),('is_fake_data','!=',False)]).unlink()
            _logger.info("debug speciak delete rst %s "%rst)
        result = super(SpecialDate, self).create(values)
        return result