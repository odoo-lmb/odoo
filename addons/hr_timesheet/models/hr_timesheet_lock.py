#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2019/1/22 10:27
# @Author  : youqingkui
# @File    : hr_timesheet_lock.py
# @Desc    :



from lxml import etree
import json
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError, AccessError
from datetime import timedelta, datetime,date
import logging
import psycopg2
_logger = logging.getLogger(__name__)


class TimeSheetLock(models.Model):
    _name = 'timesheet.lock'

    date = fields.Char(
        string="锁定日期（年-月）", required=True)
    options = fields.Selection([
        (1, '锁定'),
        (2, '解锁'),
    ], '选项', default=1, required=True)

    _sql_constraints = [

        ('date_uniq', 'unique(date)', '日期不能重复'),

    ]