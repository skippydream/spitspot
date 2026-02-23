"""
This class was an attempt at user-namespacing keys in Redis,
in order to allow every registered user to have a personal workspace.
It actually shortcircuits back at the original redis class.
@todo make it work MAYBE
"""
import logging

import redis
from django.contrib.auth.models import User

import os

def get_redis_connection():
    """
    Returns a Redis client using REDIS_URL or REDIS_HOST from environment variables.
    Defaults to 'redis' if not specified (for docker-compose compatibility).
    """
    redis_url = os.environ.get('REDIS_URL')
    if redis_url:
        return redis.from_url(redis_url, decode_responses=True)
    
    host = os.environ.get('REDIS_HOST', 'redis')
    port = int(os.environ.get('REDIS_PORT', 6379))
    return redis.Redis(host=host, port=port, decode_responses=True)

def redis_client(user: User):
    return get_redis_connection()

class NamespacedRedis(redis.Redis):
    prefix = ""
    def set_prefix(self, prefix):
        self.prefix = prefix
    def execute_command(self, *args, **options):
        args_as_list = list(args)
        if len(args) > 1:
            args_as_list[1] = "%s:%s" % (self.prefix, args[1])
        return super().execute_command(*tuple(args_as_list), **options)
