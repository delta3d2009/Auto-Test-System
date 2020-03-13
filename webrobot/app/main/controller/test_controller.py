import os
import time
from pathlib import Path

from flask import Flask, send_from_directory, request, current_app
from flask_restplus import Resource

from app.main.util.decorator import token_required, organization_team_required_by_args
from app.main.util.get_path import get_test_result_path, get_back_scripts_root
from ..config import get_config
from ..model.database import *
from ..util.dto import TestDto
from ..util.tarball import make_tarfile, pack_files
from ..util.response import *

api = TestDto.api
_test_cases = TestDto.test_cases
_test_suite = TestDto.test_suite


@api.route('/script')
@api.response(404, 'Script not found.')
@api.response(200, 'Download the script successfully.')
class ScriptDownload(Resource):
    # @token_required
    @api.doc('get_test_script')
    @api.param('id', description='The task id')
    @api.param('test', description='The test suite name')
    def get(self):
        """
        Get the test script

        Get the bundled file that contains all necessary test scripts that the test needs to run
        """
        task_id = request.args.get('id', None)
        if not task_id:
            return response_message(EINVAL, 'Field id is required'), 400

        test_suite = request.args.get('test', None)
        if not test_suite:
            return response_message(EINVAL, 'Field test is required'), 400

        task = Task.objects(pk=task_id).first()
        if not task:
            return response_message(ENOENT, 'Task not found'), 404

        if test_suite.endswith('.py'):
            test_suite = test_suite[0:-3]

        result_dir = get_test_result_path(task)
        scripts_root = get_back_scripts_root(task)

        results_tmp = result_dir / 'temp'
        try:
            os.mkdir(results_tmp)
        except FileExistsError:
            pass
        script_file = scripts_root / (test_suite + '.py')
        if not os.path.exists(script_file):
            return response_message(ENOENT, "file {} does not exist".format(script_file)), 404

        for _ in range(3):
            tarball = pack_files(test_suite, scripts_root, results_tmp)
            if tarball is None:
                current_app.logger.warning("retry packaging files")
                time.sleep(1)
            else:
                tarball = os.path.basename(tarball)
                return send_from_directory(Path(os.getcwd()) / results_tmp, tarball)
        else:
            return response_message(EIO, "packaging files failed"), 404

@api.route('/<test_suite>')
@api.param('test_suite', 'The test suite to query')
@api.response(404, 'Script not found.')
class TestSuiteGet(Resource):
    @token_required
    @organization_team_required_by_args
    @api.doc('get_the_test_cases')
    @api.marshal_with(_test_cases)
    def get(self, test_suite, **kwargs):
        """Get the test cases of a test suite"""
        organization = kwargs['organization']
        team = kwargs['team']

        test = Test.objects(test_suite=test_suite, organization=organization, team=team).first()
        if not test:
            return response_message(ENOENT, 'Test {} not found'.format(test_suite)), 404

        return {
            'test_cases': test.test_cases,
            'test_suite': test.test_suite
        }

@api.route('/')
class TestSuitesList(Resource):
    @token_required
    @organization_team_required_by_args
    @api.doc('get_the_test_suite_list')
    @api.marshal_list_with(_test_suite)
    def get(self, **kwargs):
        """Get the test suite list which contains some necessary test details"""
        organization = kwargs['organization']
        team = kwargs['team']
        
        tests = Test.objects(organization=organization, team=team)

        ret = []
        for t in tests:
            ret.append({
                'id': str(t.id),
                'test_suite': t.test_suite,
                'test_cases': t.test_cases,
                'variables': t.variables,
                'author': t.author.name
            })
        return ret
