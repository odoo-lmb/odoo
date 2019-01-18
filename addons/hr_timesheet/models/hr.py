# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models
import datetime
from datetime import timedelta

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    timesheet_cost = fields.Monetary('Timesheet Cost', currency_field='currency_id', default=0.0)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)

    # check_timesheet = fields.Char('check timesheet',compute='_check_timesheet', readonly=True, store=False)
    #
    #
    #
    # def _check_timesheet(self):
    #     now = datetime.datetime.now()
    #     # last_week_start = datetime.date.strftime(now - timedelta(days=now.weekday() + 7), '%Y-%m-%d')
    #     # last_week_end = datetime.date.strftime(now - timedelta(days=now.weekday() + 1), '%Y-%m-%d')
    #
    #     for employee in self:
    #         rst = self.env['account.analytic.line'].search(
    #             [('user_id', '=', employee.user_id.id)])
    #         count_amount = 0
    #         for temp in rst:
    #             count_amount += temp.unit_amount
    #         if count_amount < 40:
    #             employee.check_timesheet = "填写时长不够"
    #         else:
    #             employee.check_timesheet = ""
