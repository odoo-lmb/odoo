# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from lxml import etree
import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError, AccessError

import logging
_logger = logging.getLogger(__name__)

class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    @api.model
    def default_get(self, field_list):
        result = super(AccountAnalyticLine, self).default_get(field_list)
        if not self.env.context.get('default_employee_id') and 'employee_id' in field_list and result.get('user_id'):
            result['employee_id'] = self.env['hr.employee'].search([('user_id', '=', result['user_id'])], limit=1).id
        return result

    task_id = fields.Many2one('project.task', 'Task', index=True)
    project_id = fields.Many2one('project.project', 'Project', domain=[('allow_timesheets', '=', True)])

    employee_id = fields.Many2one('hr.employee', "Employee")
    approver = fields.Many2one('hr.employee', '审批员',store=True,)
    department_id = fields.Many2one('hr.department', "Department", compute='_compute_department_id', store=True, compute_sudo=True)
    timesheet_type = fields.Selection(
        [(1, "日常工作"), (2, "调休"), (3, "年假"), (4, "病假"), (5, "事假"), (6, "婚假"), (7, "产假"), (8, "陪产假"), (9, "其他假期")], string='类型',
        track_visibility='always',
        copy=False, store=True, default=1)
    is_approval= fields.Selection(
        [(0, "审核中"), (1, "通过"),(2, "驳回")], string='审批',
        track_visibility='always',
        copy=False, store=True, default=0)

    is_myself =fields.Boolean( compute='_compute_myself',
        string="is USER self",)

    @api.onchange('project_id')
    def onchange_project_id(self):
        # force domain on task when project is set
        if self.project_id:
            if self.project_id != self.task_id.project_id:
                # reset task when changing project
                self.task_id = False
            return {'domain': {
                'task_id': [('project_id', '=', self.project_id.id)]
            }}

    @api.onchange('task_id')
    def _onchange_task_id(self):
        if not self.project_id:
            self.project_id = self.task_id.project_id

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        self.user_id = self.employee_id.user_id.id

    @api.depends('employee_id')
    def _compute_department_id(self):
        for line in self:
            line.department_id = line.employee_id.department_id

    @api.depends('employee_id')
    def _compute_myself(self):
         self.is_myself = (self.user_id.id == self.env.user.id)

    @api.onchange('approver')
    def onchange_approver(self):
        # force domain on task when project is set
        if not self.approver:
            if self.employee_id:
                if self.employee_id.approver:
                    self.approver = self.employee_id.approver



    @api.constrains('unit_amount')
    def _check_unit_amount(self):
        temp_dict = {}

        for line in self:
            print(
                "line.employee_id:%s line.date:%s line.unit_amount:%s" % (
                line.employee_id.user_id, line.date, line.unit_amount))
            if line.unit_amount > 8:
                raise ValidationError(
                    _('时间不能超过8.'))
            if line.unit_amount == 0:
                raise ValidationError(
                    _('工作时长不能为0'))
            if int(line.unit_amount) != line.unit_amount:
                raise ValidationError(
                    _('工作时长请填写整数.'))
            rst = self.env['account.analytic.line'].search(
                [('user_id', '=', line.user_id.id), ('date', '=', line.date)])
            count_amount = 0
            for temp in rst:
                print(
                    "id:%s amount:%s" % (temp.id, temp.unit_amount))
                if temp.id == line.id:
                    count_amount += line.unit_amount
                else:
                    count_amount += temp.unit_amount
            if count_amount > 8:
                raise ValidationError(
                    _('一日时间总计不能超过8.'))




        sudo_self = self.sudo()  # this creates only one env for all operation that required sudo()
        # (re)compute the amount (depending on unit_amount, employee_id for the cost, and account_id for currency)


            # if temp_dict.get(line.employee_id):
            #     if temp_dict[line.employee_id].get(line.date):
            #         temp_dict[line.employee_id][line.date] += line.unit_amount
            #         if temp_dict[line.employee_id][line.date] > 8:
            #             raise ValidationError(
            #                 _('时间不能超过8.'))
            #     else:
            #         temp_dict[line.employee_id][line.date] = line.unit_amount
            # else:
            #     temp_dict[line.employee_id] = {}
            #     temp_dict[line.employee_id][line.date] = line.unit_amount

    @api.constrains('is_approval')
    def _check_is_approval(self):
        temp_dict = {}

        for line in self:
            if line.is_approval == 1:
                rst = self.env['account.analytic.line'].search(
                    [('user_id', '=', line.user_id.id), ('date', '=', line.date)])
                count_amount = 0

    # @api.constrains('employee_id')
    # def _check_employee_id(self):
    #     for line in self:
    #





    # ----------------------------------------------------
    # ORM overrides
    # ----------------------------------------------------

    @api.model
    def create(self, values):
        # 判断类型
        holiday_name = "假期"
        timesheet_type = values.get('timesheet_type')
        project_id = values.get('project_id')
        project_name = self.env['project.project'].search([('id', '=', project_id)], limit=1).name
        if timesheet_type not in [1, 2] and project_name != holiday_name:
            raise UserError(_('其他类型请选择项目为假期，谢谢'))

        if timesheet_type in [1, 2]:
            if not values.get('name'):
                raise UserError(_('请填写工作简报，谢谢'))
            if project_name == holiday_name:
                raise UserError(_('日常工作和调休请不要选择项目为假期，谢谢'))

        # compute employee only for timesheet lines, makes no sense for other lines
        if not values.get('employee_id') and values.get('project_id'):
            if values.get('user_id'):
                ts_user_id = values['user_id']
            else:
                ts_user_id = self._default_user()
            values['employee_id'] = self.env['hr.employee'].search([('user_id', '=', ts_user_id)], limit=1).id
            if not values.get('approver'):
                employee = self.env['hr.employee'].browse(values['employee_id'])
                values['approver'] = employee.approver.id

        values = self._timesheet_preprocess(values)
        result = super(AccountAnalyticLine, self).create(values)
        if result.project_id:  # applied only for timesheet
            result._timesheet_postprocess(values)
        return result

    @api.multi
    def write(self, values):
        holiday_name = "假期"
        timesheet_type = values.get('timesheet_type') or self.timesheet_type

        if values.get('project_id'):
            project_name = self.env['project.project'].search([('id', '=', values.get('project_id'))], limit=1).name
        else:
            project_name = self.project_id.name

        if values.get('name') is not None:
            name = values.get('name')
        else:
            name = self.name
        # 如果工时表是普通类型
        if timesheet_type in [1, 2]:
            if not name:
                raise UserError(_('请填写工作简报，谢谢'))

            if project_name == holiday_name:
                raise UserError(_('普通类型不能选择假期项目，谢谢'))
        else:
            if project_name != holiday_name:
                raise UserError(_('这些类型的项目只能选择假期，谢谢'))

        if self.employee_id.user_id.id == self.env.user.id:
            if self.is_approval == 2:
                values['is_approval'] = 0
        values = self._timesheet_preprocess(values)
        result = super(AccountAnalyticLine, self).write(values)
        # applied only for timesheet
        self.filtered(lambda t: t.project_id)._timesheet_postprocess(values)
        return result

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        """ Set the correct label for `unit_amount`, depending on company UoM """
        result = super(AccountAnalyticLine, self).fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        result['arch'] = self._apply_timesheet_label(result['arch'])
        return result

    @api.model
    def _apply_timesheet_label(self, view_arch):
        doc = etree.XML(view_arch)
        encoding_uom = self.env.user.company_id.timesheet_encode_uom_id
        # Here, we select only the unit_amount field having no string set to give priority to
        # custom inheretied view stored in database. Even if normally, no xpath can be done on
        # 'string' attribute.
        for node in doc.xpath("//field[@name='unit_amount'][@widget='timesheet_uom'][not(@string)]"):
            node.set('string', _('Duration (%s)') % (encoding_uom.name))
        return etree.tostring(doc, encoding='unicode')

    # ----------------------------------------------------
    # Business Methods
    # ----------------------------------------------------

    def _timesheet_preprocess(self, vals):
        """ Deduce other field values from the one given.
            Overrride this to compute on the fly some field that can not be computed fields.
            :param values: dict values for `create`or `write`.
        """
        # project implies analytic account
        if vals.get('project_id') and not vals.get('account_id'):
            project = self.env['project.project'].browse(vals.get('project_id'))
            vals['account_id'] = project.analytic_account_id.id
            vals['company_id'] = project.analytic_account_id.company_id.id
            if not project.analytic_account_id.active:
                raise UserError(_('The project you are timesheeting on is not linked to an active analytic account. Set one on the project configuration.'))
        # employee implies user
        if vals.get('employee_id') and not vals.get('user_id'):
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            vals['user_id'] = employee.user_id.id
        # force customer partner, from the task or the project
        if (vals.get('project_id') or vals.get('task_id')) and not vals.get('partner_id'):
            partner_id = False
            if vals.get('task_id'):
                partner_id = self.env['project.task'].browse(vals['task_id']).partner_id.id
            else:
                partner_id = self.env['project.project'].browse(vals['project_id']).partner_id.id
            if partner_id:
                vals['partner_id'] = partner_id
        # set timesheet UoM from the AA company (AA implies uom)
        if 'product_uom_id' not in vals and all([v in vals for v in ['account_id', 'project_id']]):  # project_id required to check this is timesheet flow
            analytic_account = self.env['account.analytic.account'].sudo().browse(vals['account_id'])
            vals['product_uom_id'] = analytic_account.company_id.project_time_mode_id.id
        return vals

    @api.multi
    def _timesheet_postprocess(self, values):
        """ Hook to update record one by one according to the values of a `write` or a `create`. """
        sudo_self = self.sudo()  # this creates only one env for all operation that required sudo() in `_timesheet_postprocess_values`override
        values_to_write = self._timesheet_postprocess_values(values)
        for timesheet in sudo_self:
            if values_to_write[timesheet.id]:
                timesheet.write(values_to_write[timesheet.id])
        return values

    @api.multi
    def _timesheet_postprocess_values(self, values):
        """ Get the addionnal values to write on record
            :param dict values: values for the model's fields, as a dictionary::
                {'field_name': field_value, ...}
            :return: a dictionary mapping each record id to its corresponding
                dictionnary values to write (may be empty).
        """
        result = dict.fromkeys(self.ids, dict())
        sudo_self = self.sudo()  # this creates only one env for all operation that required sudo()
        # (re)compute the amount (depending on unit_amount, employee_id for the cost, and account_id for currency)
        if any([field_name in values for field_name in ['unit_amount', 'employee_id', 'account_id']]):
            for timesheet in sudo_self:
                cost = timesheet.employee_id.timesheet_cost or 0.0
                amount = -timesheet.unit_amount * cost
                amount_converted = timesheet.employee_id.currency_id._convert(
                    amount, timesheet.account_id.currency_id, self.env.user.company_id, timesheet.date)
                result[timesheet.id].update({
                    'amount': amount_converted,
                })
        return result
