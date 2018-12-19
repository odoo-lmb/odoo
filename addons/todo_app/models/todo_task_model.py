# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, api
class TodoTask(models.Model):
    _name = 'todo.task'
    _description = 'To-do Task'
    name = fields.Char('Description', required=True)
    is_done = fields.Boolean('Done?')
    active = fields.Boolean('Active?', default=True)
    user_id = fields.Many2one(
    'res.users',
    string='Responsible',
    default=lambda self: self.env.user)
    team_ids = fields.Many2many('res.partner', string='Team')

@api.multi
def do_toggle_done(self):
    for task in self:
        task.is_done = not task.is_done
    return True

@api.model
def do_clear_done(self):
    dones = self.search([('is_done', '=', True)])
    dones.write({'active': False})
    return True
