# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from lxml import etree
import json
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError, AccessError
from datetime import timedelta, datetime,date
import logging
import time
import psycopg2
_logger = logging.getLogger(__name__)


HOLIDAY_NAME = "假期"
CHECK_WEEKS = [5, 6]
NEED_WORK = 1
NOT_WORK = 2
LOCK_OPTION = 1
SPECIAL_DATE_ERROR = "这一天是非工作日，暂不需要填写工时"


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    @api.model
    def default_get(self, field_list):
        result = super(AccountAnalyticLine, self).default_get(field_list)
        if not self.env.context.get(
                'default_employee_id') and 'employee_id' in field_list and result.get('user_id'):
            result['employee_id'] = self.env['hr.employee'].search(
                [('user_id', '=', result['user_id'])], limit=1).id
        return result

    task_id = fields.Many2one('project.task', 'Task', index=True)
    project_id = fields.Many2one(
        'project.project', 'Project', domain=[
            ('allow_timesheets', '=', True)])

    employee_id = fields.Many2one('hr.employee', "Employee")
    approver = fields.Many2one('hr.employee', '审批员', store=True,)
    department_id = fields.Many2one(
        'hr.department',
        "Department",
        compute='_compute_department_id',
        store=True,
        compute_sudo=True)
    timesheet_type = fields.Selection(
        [(1, "日常工作"), (2, "调休"), (3, "年假"), (4, "病假"), (5, "事假"), (6, "婚假"), (7, "产假"), (8, "陪产假"), (9, "其他假期")], string='类型',
        track_visibility='always',
        copy=False, store=True, default=1)
    is_approval = fields.Selection(
        [(0, "审核中"), (1, "通过"), (2, "驳回")], string='审批',
        track_visibility='always',
        copy=False, store=True, default=0)

    is_myself = fields.Boolean(compute='_compute_myself',
                               string="is USER self",)
    sanity_fail_reason = fields.Char(
        'check timesheet',
        default='',
        store=True)
    is_fake_data = fields.Boolean(string="is fake data", default=0)

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
                    _('持续时间不能超过8.'))
            if line.unit_amount == 0:
                raise ValidationError(
                    _('持续时间不能为0'))
            if int(line.unit_amount) != line.unit_amount:
                raise ValidationError(
                    _('持续时间请填写整数.'))
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
                    _('一日持续时间总计不能超过8.'))

        # this creates only one env for all operation that required sudo()
        sudo_self = self.sudo()
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

    @api.constrains('date')
    def _check_date(self):
        for line in self:
           self.env['account.analytic.line'].search(
                [('user_id', '=', line.user_id.id), ('date', '=', line.date),('is_fake_data','!=',False)]).unlink()


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
        self._sanity_fail_reason_type(values)
        self._check_special_date(values)
        self._check_project_task(values)
        self._check_timesheet_lock(values)

        # compute employee only for timesheet lines, makes no sense for other
        # lines
        if not values.get('employee_id') and values.get('project_id'):
            if values.get('user_id'):
                ts_user_id = values['user_id']
            else:
                ts_user_id = self._default_user()
            values['employee_id'] = self.env['hr.employee'].search(
                [('user_id', '=', ts_user_id)], limit=1).id
            if not values.get('approver'):
                employee = self.env['hr.employee'].browse(
                    values['employee_id'])
                values['approver'] = employee.approver.id


        values = self._timesheet_preprocess(values)
        result = super(AccountAnalyticLine, self).create(values)
        if result.project_id:  # applied only for timesheet
            result._timesheet_postprocess(values)
        return result

    @api.multi
    def write(self, values):
        self._sanity_fail_reason_type(values)
        self._check_special_date(values)
        self._check_project_task(values)
        self._check_timesheet_lock(values)

        if self.employee_id.user_id.id == self.env.user.id:
            if self.is_approval == 2:
                values['is_approval'] = 0
        values = self._timesheet_preprocess(values)
        result = super(AccountAnalyticLine, self).write(values)
        # applied only for timesheet
        self.filtered(lambda t: t.project_id)._timesheet_postprocess(values)
        return result

    @api.multi
    def unlink(self):
        for timesheet in self:
            values = {'date': str(timesheet.date)}
            self._check_timesheet_lock(values)
        return super(AccountAnalyticLine, self).unlink()

    @api.model
    def fields_view_get(
            self,
            view_id=None,
            view_type='form',
            toolbar=False,
            submenu=False):
        """ Set the correct label for `unit_amount`, depending on company UoM """
        result = super(
            AccountAnalyticLine,
            self).fields_view_get(
            view_id=view_id,
            view_type=view_type,
            toolbar=toolbar,
            submenu=submenu)
        result['arch'] = self._apply_timesheet_label(result['arch'])
        return result

    @api.model
    def _apply_timesheet_label(self, view_arch):
        doc = etree.XML(view_arch)
        encoding_uom = self.env.user.company_id.timesheet_encode_uom_id
        # Here, we select only the unit_amount field having no string set to give priority to
        # custom inheretied view stored in database. Even if normally, no xpath can be done on
        # 'string' attribute.
        for node in doc.xpath(
                "//field[@name='unit_amount'][@widget='timesheet_uom'][not(@string)]"):
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
            project = self.env['project.project'].browse(
                vals.get('project_id'))
            vals['account_id'] = project.analytic_account_id.id
            vals['company_id'] = project.analytic_account_id.company_id.id
            if not project.analytic_account_id.active:
                raise UserError(
                    _('The project you are timesheeting on is not linked to an active analytic account. Set one on the project configuration.'))
        # employee implies user
        if vals.get('employee_id') and not vals.get('user_id'):
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            vals['user_id'] = employee.user_id.id
        # force customer partner, from the task or the project
        if (vals.get('project_id') or vals.get(
                'task_id')) and not vals.get('partner_id'):
            partner_id = False
            if vals.get('task_id'):
                partner_id = self.env['project.task'].browse(
                    vals['task_id']).partner_id.id
            else:
                partner_id = self.env['project.project'].browse(
                    vals['project_id']).partner_id.id
            if partner_id:
                vals['partner_id'] = partner_id
        # set timesheet UoM from the AA company (AA implies uom)
        if 'product_uom_id' not in vals and all([v in vals for v in [
                                                'account_id', 'project_id']]):  # project_id required to check this is timesheet flow
            analytic_account = self.env['account.analytic.account'].sudo().browse(
                vals['account_id'])
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
        # this creates only one env for all operation that required sudo()
        sudo_self = self.sudo()
        # (re)compute the amount (depending on unit_amount, employee_id for the cost, and account_id for currency)
        if any([field_name in values for field_name in [
               'unit_amount', 'employee_id', 'account_id']]):
            for timesheet in sudo_self:
                cost = timesheet.employee_id.timesheet_cost or 0.0
                amount = -timesheet.unit_amount * cost
                amount_converted = timesheet.employee_id.currency_id._convert(
                    amount, timesheet.account_id.currency_id, self.env.user.company_id, timesheet.date)
                result[timesheet.id].update({
                    'amount': amount_converted,
                })
        return result

    def _sanity_fail_reason_type(self, values):
        """
        检查类型规则
        """
        timesheet_type = values.get('timesheet_type') or self.timesheet_type
        if values.get('project_id'):
            project_name = self.env['project.project'].search([('id', '=', values.get('project_id'))], limit=1).name
        else:
            project_name = self.project_id.name

        if values.get('name') is not None:
            name = values.get('name')
        else:
            name = self.name

        if timesheet_type not in [1, 2] and project_name != HOLIDAY_NAME:
            raise UserError(_('年假、病假、事假等类型，项目请选择假期'))

        if timesheet_type in [1, 2]:
            if not name:
                raise UserError(_('请填写工作简报，谢谢'))
            if project_name == HOLIDAY_NAME:
                raise UserError(_('日常工作和调休请不要选择项目为假期，谢谢'))

    def _check_special_date(self, values):
        """
        检查特殊日期规则
        """
        if values.get('date'):
            date = values.get('date')
        else:
            date = str(self.date)
        # 判断是否特殊日期
        week = datetime.strptime(date, "%Y-%m-%d").weekday()
        special_date = self.env['timesheet.special_date'].search([('date', '=', date)], limit=1)
        if week in CHECK_WEEKS:
            # 是特殊日期要上班
            if special_date.id and special_date.options == NEED_WORK:
                pass
            else:
                raise UserError(_('这一天是非工作日，暂不需要填写工时'))
        else:  # 如果是周一至周五的特殊日期并且指定不需要上班
            if special_date.id and special_date.options == NOT_WORK:
                raise UserError(_('这一天是非工作日，暂不需要填写工时'))

    def _check_project_task(self, values):
        """
        检查项目子任务
        """
        project_id = values.get('project_id')
        if project_id is None:
            project_id = self.project_id.id
        task_id = values.get('task_id')
        if task_id is None:
            task_id = self.task_id.id

        list_task = self.env['project.task'].search([('project_id', '=', project_id)])
        task_ids = []
        for task in list_task:
            task_ids.append(task.id)
        if task_ids and task_id not in task_ids:
            raise UserError(_('此项目有子任务，请选择对应子任务，谢谢'))

    def _check_timesheet_lock(self, values):
        """
        检查工时锁
        :param timesheet_date:
        :return:
        """
        if values.get('date'):
            date = values.get('date')
        else:
            date = str(self.date)
        time_array = time.strptime(date, "%Y-%m-%d")
        other_style_time = time.strftime("%Y-%m", time_array)
        lock_record = self.env['timesheet.lock'].search([('lock_date', '=', other_style_time), ('options', '=', LOCK_OPTION)], limit=1)
        if lock_record:
            raise UserError(_('当月份的工时已经被锁，不能再进行修改'))


    def _check_timesheet(self):
        now = datetime.now()
        sanity_fail_reason = ""
        rst = self.env['account.analytic.line'].search(
            [('user_id', '=', self.user_id.id),('date','=',self.date)])
        count_amount = 0
        for temp in rst:
            count_amount += temp.unit_amount
        if not self.is_fake_data:
            if count_amount < 8:
               sanity_fail_reason = "当日填写时长不够"
            if int(self.unit_amount) != self.unit_amount:
                sanity_fail_reason += " 该工时的时长为非整数"
            if self.is_approval != 1:
                sanity_fail_reason += " 该工时处于未通过状态"
            if self.project_id:
                list_task = self.env['project.task'].search(
                    [('project_id', '=', self.project_id.id)])
                list_task_id = [task.id for task in list_task]
                if list_task and self.task_id.id not in list_task_id:
                    sanity_fail_reason += " 请选择正确的任务"
            check_date = self.env['timesheet.special_date'].search(
                [('date', '=', self.date)], limit=1)
            if check_date.options == NOT_WORK:
                sanity_fail_reason += '这一天是非工作日，暂不需要填写工时'
        else:
            sanity_fail_reason += '当日未填写工时'
        return sanity_fail_reason





    def check_last_week(self):
        self.update_db_data('last_week')
        return True


    def check_last_month(self):
        self.update_db_data('last_month')
        return True

    def check_this_week(self):
        self.update_db_data("this_week")
        return True


    def check_this_month(self):
        self.update_db_data('this_month')
        return True


    def update_db_data(self,flag="last_week"):
        now = datetime.now()
        # 取需要工作的时间
        if flag == 'last_week':
            sunday_last_week = now - timedelta(days=now.isoweekday())
            monday_last_week = sunday_last_week - timedelta(days=6)
            last_week = [
                sunday_last_week - timedelta(i) for i in
                         range(7)]
            list_date = last_week
            first_day = date.strftime(monday_last_week, '%Y-%m-%d')
            last_day= date.strftime(sunday_last_week, '%Y-%m-%d')

        elif flag == 'this_week':
            this_week = [
                date.today() - timedelta(days=now.weekday()) + timedelta(days=i) for i in
                         range(7)]
            list_date = this_week
            first_day = date.strftime(date.today()-timedelta(days=now.weekday()), '%Y-%m-%d')
            last_day= date.strftime(date.today()-timedelta(days=now.weekday())+timedelta(days=6), '%Y-%m-%d')
        elif flag == 'this_month':
            this_month_first_day = date(now.year, now.month, 1)
            this_month_end = (datetime(now.year, now.month + 1,
                                               1) - timedelta(days=1)).date()
            this_month = [
                this_month_first_day + timedelta(i) for i in
                         range(int((this_month_end-this_month_first_day).days)+1)]
            list_date = this_month
            first_day = date.strftime(
                this_month_first_day, '%Y-%m-%d')
            last_day = date.strftime(this_month_end, '%Y-%m-%d')

        elif flag == 'last_month':
            last_month_last_day = date(now.year, now.month, 1) - timedelta(days=1)
            last_month_first_day=date(last_month_last_day.year, last_month_last_day.month, 1)
            last_month=[last_month_first_day + timedelta(days=i) for i in
                         range(int((last_month_last_day-last_month_first_day).days)+1)]
            list_date = last_month
            first_day = last_month_first_day
            last_day = last_month_last_day
        list_employee = self.env['hr.employee'].search(
            [ '|',('user_id', '=', self.env.user.id),'|',
            ('approver.user_id', '=', self.env.user.id),'|',
            ("department_id.manager_id.user_id", '=', self.env.user.id),'|',
            ('department_id.parent_id.manager_id.user_id', '=', self.env.user.id),(
            'department_id.parent_id.parent_id.manager_id.user_id', '=',
            self.env.user.id) ])
        list_timesheet = self.env['account.analytic.line'].search(
            [('date','>=',first_day),('date','<=',last_day),'|',('user_id', '=', self.env.user.id),'|',
            ('approver.user_id', '=', self.env.user.id),'|',
            ("department_id.manager_id.user_id", '=', self.env.user.id),'|',
            ('department_id.parent_id.manager_id.user_id', '=', self.env.user.id),(
            'department_id.parent_id.parent_id.manager_id.user_id', '=',
            self.env.user.id) ])
        weekday = [i for i in list_date if i.isoweekday() <6] # 所有工作日
        weekend = [i for i in list_date if i.isoweekday() > 5] # 所有周末

        list_weekday = [str(date.strftime(temp_date,'%Y-%m-%d')) for temp_date in weekday]
        list_weekend = [str(date.strftime(temp_date, '%Y-%m-%d')) for temp_date in
                        weekend]
          
        # 取需要工作的特殊周末
        db_special_workday = self.env['timesheet.special_date'].search(
            [('date', 'in', list_weekend),('options','=',NEED_WORK)])
        list_special_workday = [str(day.date) for day in db_special_workday]
        # 取不需要工作的特殊工作日
        db_special_unworkday = self.env['timesheet.special_date'].search(
            [('date', 'in',  list_weekday), ('options', '=',  NOT_WORK)])
        list_special_unworkday = [str(day.date) for day in db_special_unworkday]
        # 算出所用需要工作的日子
        all_work_day = list((set(list_weekday)-set(list_special_unworkday)).union(set(list_special_workday)))
        # 给每个用户每一天都制造一个伪数据
        dict_all = {}
        dict_employee ={}  # 存放每个员工的uid
        dict_approver = {} # 存放每个员工的审批员的uid
        dict_department = {}  # 存放每个员工的部门id
        for employee in list_employee:
            if not employee.user_id.id:
                continue
            employee_info = self.env['hr.employee'].search(
                [('user_id', '=', employee.user_id.id)], limit=1)
            first_working_day =  employee_info.first_working_day2 if employee_info.first_working_day2 else employee_info.first_working_day1
            last_working_day = employee_info.last_working_day2 if employee_info.last_working_day2 else employee_info.last_working_day1
            if not dict_all.get(employee.user_id.id):
                dict_all[employee.user_id.id] = {}
                _logger.info("employees %s" % employee.user_id.id)
                dict_employee[employee.user_id.id]=employee.id
                dict_department[employee.user_id.id]=employee.department_id.id
                dict_approver[employee.user_id.id]=employee.approver.id
            for str_date in all_work_day:
                if first_working_day:
                    if first_working_day > datetime.strptime(str_date, "%Y-%m-%d").date():
                        continue
                if last_working_day:
                    if last_working_day < datetime.strptime(str_date, "%Y-%m-%d").date():
                        continue
                dict_all[employee.user_id.id][str(str_date)] = 1
        # 从所有的伪造数据中删除已有的真数据
        for timesheet in list_timesheet:
            if not dict_all.get(timesheet.user_id.id):
                continue
            _logger.info("timesheet.date %s" % timesheet.date)
            dict_all[timesheet.user_id.id].pop(str(timesheet.date),None)

        # 对应的项目字段
        project = self.env['project.project'].search(
            [('analytic_account_id.id', '!=', 0)],limit=1)
        account_id = project.analytic_account_id.id
        my_employee_id = self.env['hr.employee'].search(
            [('user_id', '=',  self.env.user.id)],limit=1)
        # 要插入的字段
        insert_field = ["user_id", "create_uid", "employee_id","department_id","approver",
                        "project_id", "date","amount","account_id","company_id","is_fake_data"]
        # 要插入的值
        values = []
        for employee_uid in dict_all:
            for str_date in dict_all[employee_uid]:
                if dict_approver[employee_uid]:
                    approver_id = dict_approver[employee_uid]
                else:
                    approver_id = my_employee_id.id
                if not dict_department[employee_uid]:
                    continue

                values.append(
                    "('%s','%s','%s','%s','%s','%s','%s',1,  '%s',1,True)" % (
                        employee_uid, employee_uid, dict_employee[employee_uid],dict_department[employee_uid],approver_id,
                         project.id, str_date, account_id))

        if values:
            self.batch_insert('account_analytic_line',insert_field,values)
        list_timesheet = self.env['account.analytic.line'].search(
            [('date', '>=', first_day), ('date', '<=', last_day), '|',
             ('user_id', '=', self.env.user.id), '|',
             ('approver.user_id', '=', self.env.user.id), '|',
             ("department_id.manager_id.user_id", '=', self.env.user.id), '|',
             ('department_id.parent_id.manager_id.user_id', '=',
              self.env.user.id), (
                 'department_id.parent_id.parent_id.manager_id.user_id', '=',
                 self.env.user.id)])

        for timesheet in list_timesheet:
            self.update_data('account_analytic_line', timesheet._check_timesheet(), timesheet.id)




    def batch_insert(self, model, fileds, values, context=None):
        # 批量插入到数据库
        cr = self.env.cr
        vals_length = len(values)
        sql_fileds = ",".join(fileds)
        sql_values = ",".join(values)
        sql = "INSERT INTO %s (%s) VALUES %s;" % (
            model, sql_fileds, sql_values)
        cr.execute(sql)
        cr.commit()

    def update_data(self, model,  values,id ):
        # 批量插入到数据库
        cr = self.env.cr
        vals_length = len(values)
        fileds = "sanity_fail_reason"
        sql = "UPDATE %s SET %s='%s' WHERE id=%s;" % (
            model, fileds, values,id )
        cr.execute(sql)
        cr.commit()
