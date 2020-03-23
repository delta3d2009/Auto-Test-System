import os
from pathlib import Path
import datetime
from datetime import date, datetime, timedelta

from flask import request, Response, send_from_directory, current_app
from flask_restx import Resource
from mongoengine import ValidationError

from app.main.util.decorator import token_required, organization_team_required_by_args, organization_team_required_by_json, task_required
from app.main.util.get_path import get_test_result_path
from ..util import push_event
from ..util.tarball import path_to_dict
from ..model.database import *
from ..util.dto import TaskDto
# from ..util.dto import Organization_team as _organization_team
from ..config import get_config
from ..util.response import *

api = TaskDto.api
_task = TaskDto.task
_organization_team = TaskDto.organization_team
_task_update = TaskDto.task_update
_task_cancel = TaskDto.task_cancel
_task_stat = TaskDto.task_stat

@api.route('/result')
class TaskStatistics(Resource):
    @token_required
    @organization_team_required_by_args
    @task_required
    @api.doc('get_task_result')
    @api.param('organization', description='The organization ID')
    @api.param('team', description='The team ID')
    @api.param('task_id', description='The task ID')
    def get(self, **kwargs):
        """Get the task result XML file generated by robot"""
        task = kwargs['task']

        result_dir = get_test_result_path(task)
        if not os.path.exists(result_dir):
            return response_message(ENOENT, 'Task result directory not found'), 404

        with open(result_dir / 'output.xml', encoding='utf-8') as f:
            return Response(f.read(), mimetype='text/xml')

@api.route('/result_files')
class ScriptDownloadList(Resource):
    @token_required
    @organization_team_required_by_args
    @task_required
    @api.doc('get_the_result_files')
    @api.param('organization', description='The organization ID')
    @api.param('team', description='The team ID')
    @api.param('task_id', description='The task ID')
    def get(self, **kwargs):
        """Get the test result file list"""
        task = kwargs['task']

        result_dir = get_test_result_path(task)
        if not os.path.exists(result_dir):
            return response_message(ENOENT, 'Task result directory not found'), 404

        result_files = path_to_dict(result_dir)

        return response_message(SUCCESS, files=result_files)

@api.route('/result_file')
class ScriptDownload(Resource):
    @token_required
    @organization_team_required_by_args
    @task_required
    @api.doc('get_a_result_file')
    @api.param('organization', description='The organization ID')
    @api.param('team', description='The team ID')
    @api.param('task_id', description='The task ID')
    @api.param('file', description='The file path')
    def get(self, **kwargs):
        """Get the test result file"""
        file_path = request.args.get('file', default=None)
        if not file_path:
            return response_message(EINVAL, 'Field file is required'), 400

        task = kwargs['task']

        result_dir = get_test_result_path(task)
        return send_from_directory(Path(os.getcwd()) / result_dir, file_path, as_attachment=True)

@api.route('/')
class TaskController(Resource):
    @token_required
    @organization_team_required_by_args
    @api.doc('get_task_statistics')
    @api.param('organization', description='The organization ID')
    @api.param('team', description='The team ID')
    @api.param('start_date', description='The start date to query')
    @api.param('end_date', description='The end date to query')
    @api.marshal_list_with(_task_stat)
    def get(self, **kwargs):
        """
        Get the task statistics list of last 7 days

        The result is a list of task statistics of each day
        """
        organization = kwargs['organization']
        team = kwargs['team']

        start_date = request.args.get('start_date', default=(datetime.datetime.utcnow().timestamp()-86300)*1000)
        end_date = request.args.get('end_date', default=(datetime.datetime.utcnow().timestamp() * 1000))

        start_date = datetime.datetime.fromtimestamp(int(start_date)/1000)
        end_date = datetime.datetime.fromtimestamp(int(end_date)/1000)

        if (start_date - end_date).days > 0:
            return response_message(EINVAL, 'start date {} is larger than end date {}'.format(start_date, end_date)), 401

        delta = end_date - start_date
        days = delta.days
        if delta % timedelta(days=1):
            days = days + 1

        stats = []
        start = start_date
        end = start + timedelta(days=1) 

        query = {'organization': organization, 'team': team}
        query2 = {'status': 'waiting', 'organization': organization, 'team': team}

        for d in range(days):
            if d == (days - 1):
                end = end_date
            query['run_date__gte'] = start
            query2['schedule_date__gte'] = start
            query['run_date__lte'] = end
            query2['schedule_date__lte'] = end

            query['status'] = 'successful'
            tasks = Task.objects(**query)
            succeeded = tasks.count()

            query['status'] = 'failed'
            tasks = Task.objects(**query)
            failed = tasks.count()

            query['status'] = 'running'
            tasks = Task.objects(**query)
            running = tasks.count()

            tasks = Task.objects(**query2)
            waiting = tasks.count()
            
            stats.append({
                'succeeded': succeeded,
                'failed': failed,
                'running': running,
                'waiting': waiting,
            })

            start = start + timedelta(days=1)
            end = start + timedelta(days=1)
        return stats

    @token_required
    @organization_team_required_by_json
    @api.doc('run_a_test_suite')
    @api.expect(_task)
    def post(self, **kwargs):
        """Run a test suite"""
        data = request.json
        if data is None:
            return response_message(EINVAL, 'The request data is empty'), 400

        task = Task()
        test_suite = data.get('test_suite', None)
        if test_suite == None:
            return response_message(EINVAL, 'Field test_suite is required'), 400

        task.test_suite = test_suite

        organization = kwargs['organization']
        team = kwargs['team']
        user = kwargs['user']

        query = {'test_suite': task.test_suite, 'organization': organization}
        if team:
            query['team'] = team
        test = Test.objects(**query)
        if not test:
            return response_message(ENOENT, 'The requested test suite is not found'), 404
        if test.count() != 1:
            return response_message(EINVAL, 'Found duplicate test suites'), 401
        test = test.first()

        endpoint_list = data.get('endpoint_list', None)
        if endpoint_list == None:
            return response_message(EINVAL, 'Endpoint list is not included in the request'), 400
        if not isinstance(endpoint_list, list):
            return response_message(EINVAL, 'Endpoint list is not a list'), 400
        if len(endpoint_list) == 0:
            return response_message(EINVAL, 'Endpoint list is empty'), 400
        task.endpoint_list = endpoint_list

        priority = int(data.get('priority', QUEUE_PRIORITY_DEFAULT))
        if priority < QUEUE_PRIORITY_MIN or priority > QUEUE_PRIORITY_MAX:
            return response_message(ERANGE, 'Task priority is out of range'), 400
        task.priority = priority

        parallelization = data.get('parallelization', False)
        task.parallelization = parallelization == True

        variables = data.get('variables', {})
        if not isinstance(variables, dict):
            return response_message(EINVAL, 'Variables should be a dictionary'), 400
        task.variables = variables

        testcases = data.get('test_cases', [])
        if not isinstance(testcases, list):
            return response_message(EINVAL, 'Testcases should be a list'), 400
        task.testcases = testcases

        task.tester = user
        task.upload_dir = data.get('upload_dir', '')
        task.test = test
        task.organization = organization
        task.team = team
        try:
            task.save()
        except ValidationError:
            return response_message(EINVAL, 'Task validation failed'), 400

        failed = []
        succeeded = []
        running = []
        for endpoint in task.endpoint_list:
            if task.parallelization:
                new_task = Task()
                for name in task:
                    if name != 'id' and not name.startswith('_') and not callable(task[name]):
                        new_task[name] = task[name]
                else:
                    new_task.save()
                    taskqueue = TaskQueue.objects(endpoint_address=endpoint, priority=task.priority, organization=organization, team=team).first()
                    if not taskqueue:
                        failed.append(str(new_task.id))
                        current_app.logger.error('Task queue not found')
                    else:
                        if not taskqueue.running_task and len(taskqueue.tasks) == 0:
                            running.append(str(new_task.id))
                        ret = taskqueue.push(new_task)
                        if ret == None:
                            failed.append(str(new_task.id))
                            current_app.logger.error('Failed to push task to the task queue')
                        else:
                            message = {
                                'address': endpoint,
                                'task_id': str(new_task.id),
                            }
                            ret = push_event(organization=new_task.test.organization, team=new_task.test.team, code=EVENT_CODE_START_TASK, message=message)
                            if not ret:
                                return response_message(EPERM, 'Pushing the event to event queue failed'), 403
                            succeeded.append(str(new_task.id))
            else:
                taskqueue = TaskQueue.objects(endpoint_address=endpoint, priority=task.priority, organization=organization, team=team).first()
                if not taskqueue:
                    failed.append(str(task.id))
                    current_app.logger.error('Task queue not found')
                else:
                    if not taskqueue.running_task and len(taskqueue.tasks) == 0:
                        running.append(str(task.id))
                    ret = taskqueue.push(task)
                    if ret == None:
                        failed.append(str(task.id))
                        current_app.logger.error('Failed to push task to the task queue')
                    else:
                        message = {
                            'address': endpoint,
                            'task_id': str(task.id),
                        }
                        ret = push_event(organization=task.test.organization, team=task.test.team, code=EVENT_CODE_START_TASK, message=message)
                        if not ret:
                            return response_message(EPERM, 'Pushing the event to event queue failed'), 403
                        succeeded.append(str(task.id))
        else:
            if task.parallelization:
                task.delete()
        if len(failed) != 0:
            return response_message(UNKNOWN_ERROR, 'Task scheduling failed'), 401
        return response_message(SUCCESS, failed=failed, succeeded=succeeded, running=[t for t in running if t in succeeded]), 200

    @token_required
    @organization_team_required_by_json
    @task_required
    @api.doc('update_a_task')
    @api.expect(_task_update)
    def patch(self, **kwargs):
        """Update a task with specified fields"""
        task = kwargs['task']
        data = request.json
        if not data:
            return response_message(EINVAL, 'The request data is empty'), 400

        comment = data.get('comment', None)
        if not comment:
            return response_message(EINVAL, 'Field comment is required'), 400

        task.comment = comment
        task.save()

    @token_required
    @organization_team_required_by_json
    @task_required
    @api.doc('cancel_a_task')
    @api.expect(_task_cancel)
    def delete(self, **kwargs):
        """
        Cancel a task
        
        The task will be removed from the queue. The running task will be terminated,
        """
        task = kwargs['task']
        data = request.json
        if data is None:
            return response_message(EINVAL, 'The request data is empty'), 400

        address = data.get('address', None)
        if address is None:
            return response_message(EINVAL, 'Field address is required'), 400
        priority = data.get('priority', None)
        if priority is None:
            return response_message(EINVAL, 'Field priority is required'), 400

        message = {
            'address': address,
            'priority': priority,
            'task_id': str(task.id)
        }

        ret = push_event(organization=task.test.organization, team=task.test.team, code=EVENT_CODE_CANCEL_TASK, message=message)
        if not ret:
            return response_message(EPERM, 'Pushing the event to event queue failed'), 403
