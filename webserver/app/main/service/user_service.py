# import uuid
import datetime
import os
from pathlib import Path

from app.main.model.database import User, Organization
from flask import current_app

from ..config import get_config
from ..util.response import *
from ..util.identicon import *

USERS_ROOT = Path(get_config().USERS_ROOT)

def save_new_user(data, admin=None):
    user = User.objects(email=data['email']).first()
    if not user:
        new_user = User(
            # public_id=str(uuid.uuid4()),
            email=data['email'],
            name=data.get('username', ''),
            registered_on=datetime.datetime.utcnow(),
            roles=data.get('roles', ['admin']),
            avatar=data.get('avatar', ''),
            introduction=data.get('introduction', '')
        )
        new_user.password = data['password']
        try:
            new_user.save()
        except Exception as e:
            current_app.logger.exception(e)
            return response_message(EINVAL, 'Field validating for User failed'), 401

        user_root = USERS_ROOT / data['email']
        try:
            os.mkdir(user_root)
        except FileExistsError as e:
            return response_message(EEXIST), 401
        try:
            os.mkdir(user_root / 'test_results')
        except FileExistsError as e:
            return response_message(EEXIST), 401

        if new_user.avatar == '':
            img = render_identicon(hash(data['email']), 27)
            img.save(user_root / ('%s.png' % new_user.id))
            new_user.avatar = '%s.png' % new_user.id
        if new_user.name == '':
            new_user.name = new_user.email.split('@')[0]
        if not admin:
            organization = Organization(name='Personal')
            organization.owner = new_user
            organization.path = new_user.email
            organization.members = [new_user]
            organization.personal = True
            organization.save()
            new_user.organizations = [organization]
        new_user.save()

        return generate_token(new_user)
    else:
        return response_message(USER_ALREADY_EXIST), 409


def get_all_users():
    return [user for user in User.objects()]


def get_a_user(user_id):
    return User.objects(pk=user_id).first()


def generate_token(user):
    try:
        # generate the auth token
        auth_token = User.encode_auth_token(str(user.id))
        return response_message(SUCCESS, token=auth_token.decode()), 201
    except Exception as e:
        current_app.logger.exception(e)
        return response_message(UNKNOWN_ERROR), 401

