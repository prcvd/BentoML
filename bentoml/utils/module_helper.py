# BentoML - Machine Learning Toolkit for packaging and deploying models
# Copyright (C) 2019 Atalaya Tech, Inc.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import inspect
import subprocess
import shutil
from importlib import import_module
from modulefinder import ModuleFinder

from six import string_types, iteritems

from bentoml.utils import Path
from bentoml.utils.exceptions import BentoMLException


def _get_module_src_file(module):
    return module.__file__[:-1] if module.__file__.endswith('.pyc') else module.__file__


def _guess_project_base(module):
    try:
        # By default, use git root path as package base
        p = subprocess.Popen(["git", "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                             stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.communicate()[0].decode().strip()
    except (IOError, subprocess.CalledProcessError):
        # when not inside a git repository, use "..." folder as package base
        return os.path.dirname(os.path.dirname(module.__file__))


def _copy_entire_project(project_base_dir, destination):
    shutil.copytree(project_base_dir, destination)


def copy_module_and_local_dependencies(module, destination, project_base_dir=None,
                                       copy_entire_project=False):
    """
    bundle given module, and all its dependencies, copy files to path/src
    """
    if isinstance(module, string_types):
        module = import_module(module)
    else:
        module = inspect.getmodule(module)

    if module.__name__ == '__main__' and not module.__file__:
        raise BentoMLException(
            "Custom BentoModel class can not be defined in Python interactive REPL")

    if module.__name__ == '__main__' and module.__file__:
        # Running from Python cli
        module_name = os.path.split(module.__file__)[1].split('.')[0]
    else:
        module_name = module.__name__
    module_file = _get_module_src_file(module)

    if copy_entire_project:
        if project_base_dir is None:
            raise ValueError("Must provide project base dir when copy_entire_project=True")
        _copy_entire_project(project_base_dir, destination)
        return module_name, module_file

    # Find all modules must be imported for target module to run
    finder = ModuleFinder()
    # NOTE: This method could take a few seconds to run
    try:
        finder.run_script(module_file)
    except SyntaxError:
        # For package with conditional import that may only work with py2
        # or py3, ModuleFinder#run_script will try to compile the source
        # with current python version. And that may result in SyntaxError.
        pass

    module_files = {}
    for name, module in iteritems(finder.modules):
        if module.__file__ is not None:
            module_files[name] = _get_module_src_file(module)

    if project_base_dir is None:
        project_base_dir = _guess_project_base(module)
    elif not os.path.isabs(project_base_dir):
        # Convert to absolute path when arg project_base_dir is relative path
        project_base_dir = os.path.abspath(project_base_dir)

    # Remove dependencies not in current project (those specified in bentoml.env)
    module_files = {
        name: module_file
        for name, module_file in iteritems(module_files) if module_file.startswith(project_base_dir)
    }

    # Lastly, add target module itself
    module_files[module_name] = module_file

    # Remove "__main__" module, if target module is loaded as __main__, it should
    # be in module_files as (module_name, module_file) in current context
    if '__main__' in module_files:
        del module_files['__main__']

    for mod_name, mod_file in iteritems(module_files):
        with open(mod_file, "rb") as f:
            src_code = f.read()

        _, file_name = os.path.split(mod_file)
        if file_name == '__init__.py':
            target_file = os.path.join(destination, mod_name.replace('.', '/'), '__init__.py')
        else:
            target_file = os.path.join(destination, mod_name.replace('.', '/') + '.py')
        target_path = os.path.dirname(target_file)
        Path(target_path).mkdir(parents=True, exist_ok=True)

        with open(target_file, 'wb') as f:
            f.write(src_code)

    for root, dirs, files in os.walk(destination):
        if '__init__.py' not in files:
            Path(os.path.join(root, '__init__.py')).touch()

    return module_name, module_file