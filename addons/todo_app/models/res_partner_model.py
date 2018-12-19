#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2018/12/17 15:11
# @Author  : wangjue
# @Site    : 
# @File    : res_partner_model.py
# @Software: PyCharm

from odoo import fields, models
class ResPartner(models.Model):
    _inherit = 'res.partner'
    todo_ids= fields.Many2many(
    'todo.task',
    string="To-do Teams")