""" This script will import and run the functions inside an Unreal Engine instance. """

import os
import sys
import typing


BC_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

def run(data: dict):

    # reimporting blend_converter as the module will be cached by python
    for module in list(sys.modules):
        if module.startswith('blend_converter'):
            del sys.modules[module]

    import runpy
    runpy.run_path(os.path.join(BC_ROOT, 'serialization.py'))['bootstrap']()

    from blend_converter import serialization

    for script in data['instructions']:

        if not script['is_instruction_enabled']:
            continue

        func = serialization.Function.from_dict(script['function']).get()

        func(*script['args'], **script['kwargs'])
