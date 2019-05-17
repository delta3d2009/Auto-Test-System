from flask import request
from flask_restplus import Resource

from app.main.util.decorator import admin_token_required
from app.main.model.user import User

from ..service.user_service import get_a_user, get_all_users, save_new_user
from ..service.auth_helper import Auth
from ..util.dto import UserDto
from ..util.errors import *

api = UserDto.api
_user = UserDto.user


@api.route('/')
class UserList(Resource):
    @api.doc('list_of_registered_users')
    @admin_token_required
    @api.marshal_list_with(_user, envelope='data')
    def get(self):
        """List all registered users"""
        return get_all_users()

    @api.expect(_user, validate=True)
    @api.response(201, 'User successfully created.')
    @api.doc('create a new user')
    def post(self):
        """Creates a new User """
        data = request.json
        return save_new_user(data=data)


@api.route('/info')
class UserInfo(Resource):
    """
    User information
    """
    @api.doc('get the information of a user')
    def get(self):
        data, status = Auth.get_logged_in_user(request)
        token = data.get('data')

        return data, status
