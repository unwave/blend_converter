import os
import sys
import typing
import json


BC_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def main(data: dict):

    import runpy
    runpy.run_path(os.path.join(BC_ROOT, 'serialization.py'))['bootstrap']()


    from blend_converter import common
    from blend_converter import serialization

    instructions = data['instructions']

    return_values = {}


    for script in instructions:

        func = serialization.Function.from_dict(script['function']).get()

        func(
            *common.replace_return_value(script['args'], return_values, instructions),
            **common.replace_return_value(script['kwargs'], return_values, instructions)
        )


    with open(data['return_values_file'], 'w', encoding='utf-8') as f:
        json.dump(return_values, f, default = lambda x: repr(x))




if __name__ == '__main__':
    with open(sys.argv[1]) as f:
        main(json.load(f))
