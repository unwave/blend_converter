from __future__ import annotations

import importlib
import sys
import traceback
import types
import typing


try:
    import bpy
except ModuleNotFoundError:
    pass


if typing.TYPE_CHECKING:
    import bpy_types
    class Menu_Type(bpy_types.RNAMeta, bpy_types.Menu, bpy.types.Menu):
        pass


class Addon_Register:

    def __init__(self, addon_prefix: str):

        self.addon_prefix = addon_prefix

        self.modules: typing.Set[str] = set()
        self.properties: typing.List[typing.Tuple[bpy.types.ID, str, bpy.types.Property]] = []
        self.menu_items: typing.List[typing.Tuple['Menu_Type', typing.Callable]] = []
        self.registered_classes = set()


    @staticmethod
    def import_module(module: str):
        package, path = module.split('.', maxsplit=1)
        try:
            importlib.import_module('.' + path, package = package)
        except Exception:
            traceback.print_exc()


    @staticmethod
    def get_register_priority(_class: type) -> int:
        return getattr(_class, '_ui_register_priority', 0)


    def get_classes(self, module: types.ModuleType):
        return [_class for name, _class in module.__dict__.items() if name.startswith(self.addon_prefix)]


    def get_registered_classes(self):
        return [getattr(bpy.types, attr) for attr in dir(bpy.types) if attr.startswith(self.addon_prefix)]


    def get_all_classes(self):
        classes: typing.List[type] = []

        for module in self.modules:
            classes.extend(self.get_classes(sys.modules[module]))

        classes.sort(key = self.get_register_priority, reverse = True)

        return classes


    def register(self):

        self.modules.update(self.get_addon_modules())
        for module in self.modules:
            if not module in sys.modules:
                self.import_module(module)

        count = 0
        for _class in self.get_all_classes():
            try:
                bpy.utils.register_class(_class)
            except Exception:
                traceback.print_exc()
                print("Class register error:", repr(_class), file=sys.stderr)
            else:
                count += 1
                self.registered_classes.add(_class)

        print(f"{self.addon_prefix.title()}: {count} classes registered.")


        count = 0
        for bpy_type, name, value in self.properties:
            try:
                setattr(bpy_type, name, value)
            except Exception:
                traceback.print_exc()
                print("Property register error:", repr(bpy_type), repr(name), file=sys.stderr)
            else:
                count += 1

        print(f"{self.addon_prefix.title()}: {count} properties registered.")


        count = 0
        for menu, object in self.menu_items:
            try:
                menu.append(object)
            except Exception:
                traceback.print_exc()
                print("Menu register error:", repr(bpy_type), repr(name), file=sys.stderr)
            else:
                count += 1

        print(f"{self.addon_prefix.title()}: {count} menu items registered.")


    def unregister(self):

        for menu, object in reversed(self.menu_items):
            try:
                menu.remove(object)
            except Exception:
                traceback.print_exc()
                print("Menu unregister error:", repr(menu), repr(object), file=sys.stderr)

        for bpy_type, name, value in reversed(self.properties):
            try:
                delattr(bpy_type, name)
            except Exception:
                traceback.print_exc()
                print("Property unregister error:", repr(bpy_type), repr(name), file=sys.stderr)

        for _class in reversed(self.get_all_classes()):
            try:
                bpy.utils.unregister_class(_class)
            except Exception:
                traceback.print_exc()
                print("Class unregister error:", repr(_class), file=sys.stderr)

        self.registered_classes.clear()


    def property(self, name: str, value: bpy.types.Property, bpy_type: bpy.types.ID = bpy.types.WindowManager):
        self.properties.append((bpy_type, name, value))

    def menu_item(self, menu: 'Menu_Type', func: typing.Callable):
        self.menu_items.append((menu, func))


    def register_module(self, module: types.ModuleType):

        self.modules.add(module.__name__)

        for _class in self.get_classes(module):
            if _class in self.registered_classes:
                continue

            try:
                bpy.utils.register_class(_class)
            except Exception:
                traceback.print_exc()
                print(repr(_class), file=sys.stderr)
            else:
                self.registered_classes.add(_class)

        for bpy_type, name, value in self.properties:
            if hasattr(bpy_type, name):
                continue

            try:
                setattr(bpy_type, name, value)
            except Exception:
                traceback.print_exc()
                print("Property register error:", repr(bpy_type), repr(name), file=sys.stderr)

        for menu, func in self.menu_items:
            if func in getattr(menu.draw, '_draw_funcs', ()):
                continue

            try:
                menu.append(func)
            except Exception:
                traceback.print_exc()
                print("Menu register error:", repr(bpy_type), repr(name), file=sys.stderr)


    def reload_modules(self):

        self.menu_items.clear()
        self.properties.clear()

        for name in self.get_addon_modules():

            try:
                importlib.reload(sys.modules[name])
            except Exception:
                traceback.print_exc()


    def get_addon_modules(self):
        """ Get a list of the addon's modules. """
        raise NotImplementedError('Subclass the class and override the function.')


    def reload(self):
        """ Addon reload code. """
        raise NotImplementedError('Subclass the class and override the function.')
