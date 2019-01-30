#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2019/1/28 14:47
# @Author  : youqingkui
# @File    : timesheet_select_create.py
# @Desc    :

import time
import calendar
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .hr_timesheet import TIMESHEET_TYPE, NEED_WORK, NOT_WORK
from datetime import timedelta, datetime

STANDARD_WORK_HOURS = 8

class TimesheetSelectCreate(models.Model):
    _name = 'timesheet.select_create'

    task_id = fields.Many2one('project.task', 'Task', index=True)
    project_id = fields.Many2one(
        'project.project', 'Project', domain=[
            ('allow_timesheets', '=', True)], required=True)

    employee_id = fields.Many2one('hr.employee', "Employee")
    department_id = fields.Many2one(
        'hr.department',
        "Department",
        store=True)
    date = fields.Char(
        string="填充日期", required=True)

    timesheet_type = fields.Selection(
        TIMESHEET_TYPE,
        string='类型',
        track_visibility='always',
        copy=False, store=True, default=1)

    @api.onchange('department_id')
    def onchange_department_id(self):
        if self.department_id:
            if self.department_id != self.employee_id.department_id:
                self.employee_id = False
            return {'domain': {
                'employee_id': [('department_id', '=', self.department_id.id)]
            }}

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

    @api.model
    def create(self, values):
        department_id = values.get('department_id')
        employee_id = values.get('employee_id')
        project_id = values.get('project_id')
        task_id = values.get('task_id')
        date = values.get('date')
        timesheet_type = values.get('timesheet_type')
        values['name'] = '自动创建'
        values['unit_amount'] = STANDARD_WORK_HOURS
        values['is_approval'] = 1
        values['is_auto_create'] = 1

        date = self._change_date_format(date)

        if department_id and not employee_id:
            list_employee = self.env['hr.employee'].search([('department_id', '=', department_id)])
        elif employee_id:
            list_employee = self.env['hr.employee'].search([('id', '=', employee_id)])
        else:
            list_employee = []

        all_work_day = self._get_date_month(date)

        for employee in list_employee:
            # 创建工时那边代码不需要员工id的时候才会去找审批人
            values['employee_id'] = False
            values['user_id'] = employee.user_id.id
            values['approver'] = employee.approver.id
            first_working_day = employee.first_working_day2 if employee.first_working_day2 else employee.first_working_day1
            last_working_day = employee.last_working_day2 if employee.last_working_day2 else employee.last_working_day1
            first_working_day_timestap = 0
            last_working_day_timestap = 0
            if first_working_day:
                first_working_day_timestap = self._get_date_timestamp(str(first_working_day))
            if last_working_day:
                last_working_day_timestap = self._get_date_timestamp(str(last_working_day))

            for work_day in all_work_day:
                list_record = self.env['account.analytic.line'].search([('employee_id', '=', employee.id),
                                                                        ('date', '=', work_day)])
                insert_timestamp = self._get_date_timestamp(work_day)


                if first_working_day_timestap and insert_timestamp < first_working_day_timestap:
                    continue
                if last_working_day_timestap and insert_timestamp > last_working_day_timestap:
                    continue

                values['date'] = work_day
                total_unit_amount = 0
                for record in list_record:
                    if record.is_auto_create:
                        record.unlink()
                    else:
                        total_unit_amount += record.unit_amount
                # 如果工时不够8小时，则计算下
                if total_unit_amount < STANDARD_WORK_HOURS:
                    unit_amount = STANDARD_WORK_HOURS - total_unit_amount
                    if unit_amount <= STANDARD_WORK_HOURS:
                        values['unit_amount'] = unit_amount
                else:
                    continue

                result = self.env['account.analytic.line'].create(values)
        values['employee_id'] = employee_id
        values['date'] = date
        return super(TimesheetSelectCreate, self).create(values)

    def _get_date_month(self, date_str):
        from datetime import date
        date_type = self._check_date_type(date_str)
        if date_type == 'day':
            return [date_str]

        time_array = time.strptime(date_str, "%Y-%m")
        this_month_first_day = date(time_array.tm_year, time_array.tm_mon, 1)
        if time_array.tm_mon + 1 > 12:
            next_tm_mon = 1
            next_tm_year = time_array.tm_year + 1
        else:
            next_tm_mon = time_array.tm_mon + 1
            next_tm_year = time_array.tm_year
        this_month_end = (datetime(next_tm_year, next_tm_mon,
                                   1) - timedelta(days=1)).date()
        this_month = [
            this_month_first_day + timedelta(i) for i in
            range(int((this_month_end - this_month_first_day).days) + 1)]
        list_date = this_month
        first_day = date.strftime(
            this_month_first_day, '%Y-%m-%d')
        last_day = date.strftime(this_month_end, '%Y-%m-%d')

        weekday = [i for i in list_date if i.isoweekday() < 6]  # 所有工作日
        weekend = [i for i in list_date if i.isoweekday() > 5]  # 所有周末

        list_weekday = [str(date.strftime(temp_date, '%Y-%m-%d')) for temp_date in weekday]
        list_weekend = [str(date.strftime(temp_date, '%Y-%m-%d')) for temp_date in
                        weekend]

        # 取需要工作的特殊周末
        db_special_workday = self.env['timesheet.special_date'].search(
            [('date', 'in', list_weekend), ('options', '=', NEED_WORK)])
        list_special_workday = [str(day.date) for day in db_special_workday]
        # 取不需要工作的特殊工作日
        db_special_unworkday = self.env['timesheet.special_date'].search(
            [('date', 'in', list_weekday), ('options', '=', NOT_WORK)])
        list_special_unworkday = [str(day.date) for day in db_special_unworkday]
        # 算出所用需要工作的日子
        all_work_day = list((set(list_weekday) - set(list_special_unworkday)).union(set(list_special_workday)))
        return all_work_day

    def _check_date_type(self, date_str):
        time_array = date_str.split('-')
        date_type = ''
        try:
            if len(time_array) == 2:
                time_array = time.strptime(date_str, "%Y-%m")
                date_type = 'month'
            elif len(time_array) == 3:
                time_array = time.strptime(date_str, "%Y-%m-%d")
                date_type = 'day'
            else:
                raise ("error date")
            return date_type
        except Exception as e:
            raise ValidationError(_('日期格式有问题，如果按月，如2019-01，如果按日期则2019-01-01'))

    def _change_date_format(self, data_str):
        date_type = self._check_date_type(data_str)
        strTime = data_str
        if date_type == 'day':
            timeStruct = time.strptime(data_str, "%Y-%m-%d")
            strTime = time.strftime("%Y-%m-%d", timeStruct)
        if date_type == 'month':
            timeStruct = time.strptime(data_str, "%Y-%m")
            strTime = time.strftime("%Y-%m", timeStruct)

        return strTime

    def _get_date_timestamp(self, date_str, format_str="%Y-%m-%d"):
        timeStruct = time.strptime(date_str, format_str)
        timeStamp = int(time.mktime(timeStruct))
        return timeStamp





