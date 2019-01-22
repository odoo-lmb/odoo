#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2019/1/22 10:27
# @Author  : youqingkui
# @File    : hr_timesheet_lock.py
# @Desc    :

import json
import time
from odoo import api, fields, models, _
import logging
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class TimeSheetLock(models.Model):
    _name = 'timesheet.lock'

    lock_date = fields.Char(
        string="锁定日期（年-月）", required=True)
    options = fields.Selection([
        (1, '锁定'),
        (2, '解锁'),
    ], '选项', default=1, required=True)

    _sql_constraints = [

        ('date_uniq', 'unique(lock_date)', '日期不能重复'),

    ]


    @api.constrains('lock_date')
    def _check_date(self):
        for line in self:
            try:
                time_array = time.strptime(line.lock_date, "%Y-%m")
            except Exception as e:
                _logger.error(e)
                raise ValidationError(_('请输入正确的时间格式如2019-01'))
