# Copyright 2017 The Bazel Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""The whl modules defines classes for interacting with Python packages."""

import argparse
import collections
import distlib.markers
import itertools
import json
import os
import re
import zipfile

try:
    from ConfigParser import ConfigParser
except ImportError:
    from configparser import ConfigParser


class Wheel(object):

  def __init__(self, path):
    self._path = path
    self._extra_deps = []
    self._extra_buildtime_deps = []
    self._extra_runtime_deps = []

  def add_extra_buildtime_deps(self, deps):
    self._extra_buildtime_deps += deps

  def add_extra_runtime_deps(self, deps):
    self._extra_runtime_deps += deps

  def add_extra_deps(self, deps):
    self._extra_deps += deps

  def get_extra_buildtime_deps(self):
    return sorted(list(set(self._extra_buildtime_deps)))

  def get_extra_runtime_deps(self):
    return sorted(list(set(self._extra_runtime_deps)))

  def get_extra_deps(self):
    return sorted(list(set(self._extra_deps)))

  def path(self):
    return self._path

  def basename(self):
    return os.path.basename(self.path())

  def distribution(self):
    # See https://www.python.org/dev/peps/pep-0427/#file-name-convention
    parts = self.basename().split('-')
    return parts[0]

  def version(self):
    # See https://www.python.org/dev/peps/pep-0427/#file-name-convention
    parts = self.basename().split('-')
    return parts[1]

  def repository_name(self, prefix='pypi'):
    # Returns the canonical name of the Bazel repository for this package.
    canonical = '{}__{}_{}'.format(prefix, self.distribution(), self.version())
    # Escape any illegal characters with underscore.
    return re.sub('[-.]', '_', canonical)

  def _dist_info(self):
    # Return the name of the dist-info directory within the .whl file.
    # e.g. google_cloud-0.27.0-py2.py3-none-any.whl ->
    #      google_cloud-0.27.0.dist-info
    return '{}-{}.dist-info'.format(self.distribution(), self.version())

  def metadata(self):
    # Extract the structured data from metadata.json in the WHL's dist-info
    # directory.
    with zipfile.ZipFile(self.path(), 'r') as whl:
      # first check for metadata.json
      try:
        with whl.open(os.path.join(self._dist_info(), 'metadata.json')) as f:
          return json.loads(f.read().decode("utf-8"))
      except KeyError:
          pass
      # fall back to METADATA file (https://www.python.org/dev/peps/pep-0427/)
      with whl.open(os.path.join(self._dist_info(), 'METADATA')) as f:
        return self._parse_metadata(f.read().decode("utf-8"))

  def entrypoints(self):
      with zipfile.ZipFile(self.path(), 'r') as whl:
          try:
              with whl.open(os.path.join(self._dist_info(), 'entry_points.txt')) as f:
                  parser = ConfigParser()
                  parser.readfp(f)
                  return parser
          except KeyError:
              return None

  def name(self):
    return self.metadata().get('name').lower()

  def dependencies(self, extra=None, all_extras=False):
    """Access the dependencies of this Wheel.

    Args:
      extra: if specified, include the additional dependencies
            of the named "extra".

    Yields:
      the names of requirements from the metadata.json
    """
    # TODO(mattmoor): Is there a schema to follow for this?
    found = set()
    run_requires = self.metadata().get('run_requires', [])

    for requirement in run_requires:
      if requirement.get('extra') != extra:
        # Match the requirements for the extra we're looking for.
        continue
      if 'environment' in requirement:
        try:
          if not distlib.markers.interpret(requirement['environment'], {'extra': extra}):
            continue
        except SyntaxError as e:
          raise RuntimeError('Error interpreting environment for {} ({}): {}'.format(
                             self.name(), requirement['environment'], str(e)))
      requires = requirement.get('requires', [])
      for entry in requires:
        # Strip off any trailing versioning data.
        parts = re.split('[ ><=()]', entry)
        found.add(parts[0].lower())
    return found

  def extras(self):
    return self.metadata().get('extras', [])

  def expand(self, directory):
    with zipfile.ZipFile(self.path(), 'r') as whl:
      whl.extractall(directory)

    # Fix puredata structure
    purelib_path = os.path.join(directory, '%s-%s.data' % (self.distribution(), self.version()), 'purelib')
    if os.path.isdir(purelib_path):
        for _, subdirs, _ in os.walk(purelib_path):
            for s in subdirs:
                os.symlink(os.path.join(purelib_path, s), os.path.join(directory, s))
            break

    # Add empty init files where needed
    for current_dir, _, filelist in os.walk(directory):
        if current_dir != directory and '__init__.py' not in filelist:
            with open(os.path.join(current_dir, '__init__.py'), 'w') as f:
                pass

  # _parse_metadata parses METADATA files according to https://www.python.org/dev/peps/pep-0314/
  def _parse_metadata(self, content):
    name_pattern = re.compile('Name: (.*)')
    extra_pattern = re.compile('Provides-Extra: (.*)')
    dep_pattern = re.compile('Requires-Dist: ([^;]+)(;(.*))?')
    deps = []
    extras = []
    env_deps = collections.defaultdict(list)
    for line in content.splitlines():
      m = dep_pattern.match(line)
      if m:
        dep = m.group(1).strip()
        env = m.group(3)
        if env:
          env_deps[env.strip()] += [dep]
        else:
          deps += [dep]
      m = extra_pattern.match(line)
      if m:
        extras += [m.group(1).strip()]
    return {
      'name': name_pattern.search(content).group(1).strip(),
      'extras': list(set(extras)),
      'run_requires': [{ 'requires': deps }] + [{
        'environment': k,
        'requires': v,
      } for k, v in env_deps.items()],
    }
