import os

from datagym.ui_app import run

if __name__ == '__main__':
    run(port=int(os.environ.get('DATAGYM_PORT', '8765')))
