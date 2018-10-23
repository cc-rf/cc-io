import os


class adict(dict):
    def __init__(self, *args, **kwargs):
        super(adict, self).__init__(*args, **kwargs)
        self.__dict__ = self


def arg_env_or_req(key):
    """Return for argparse 'default=os.environ[key]' if set else 
    """
    return {'default': os.environ.get(key)} if os.environ.get(key) else {'required': True}
