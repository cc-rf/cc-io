import os


def arg_env_or_req(key):
    """Return for argparse 'default=os.environ[key]' if set else required=True
    """
    return {'default': os.environ.get(key)} if os.environ.get(key) else {'required': True}


def arg_env_or_none(key, default=None):
    """Return for argparse 'default=os.environ[key]' if set else default=None
    """
    return {'default': os.environ.get(key, default=default)}
