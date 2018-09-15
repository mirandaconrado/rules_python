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
"""The piptool module imports pip requirements into Bazel rules."""

import argparse
import atexit
import itertools
import json
import os
import pkgutil
import pkg_resources
import re
import requests
import shutil
import sys
import tempfile
import toposort
import zipfile

# Note: We carefully import the following modules in a particular
# order, since these modules modify the import path and machinery.
import pkg_resources


def extract_packages(package_names):
    """Extract zipfile contents to disk and add to import path"""

    # Set a safe extraction dir
    extraction_tmpdir = tempfile.mkdtemp()
    atexit.register(lambda: shutil.rmtree(
        extraction_tmpdir, ignore_errors=True))
    pkg_resources.set_extraction_path(extraction_tmpdir)

    # Extract each package to disk
    dirs_to_add = []
    for package_name in package_names:
        req = pkg_resources.Requirement.parse(package_name)
        extraction_dir = pkg_resources.resource_filename(req, '')
        dirs_to_add.append(extraction_dir)

    # Add extracted directories to import path ahead of their zip file
    # counterparts.
    sys.path[0:0] = dirs_to_add
    existing_pythonpath = os.environ.get('PYTHONPATH')
    if existing_pythonpath:
        dirs_to_add.extend(existing_pythonpath.split(':'))
    os.environ['PYTHONPATH'] = ':'.join(dirs_to_add)


# Wheel, pip, and setuptools are much happier running from actual
# files on disk, rather than entries in a zipfile.  Extract zipfile
# contents, add those contents to the path, then import them.
extract_packages(['pip', 'setuptools', 'wheel'])

# Defeat pip's attempt to mangle sys.path
saved_sys_path = sys.path
sys.path = sys.path[:]
import pip
sys.path = saved_sys_path

import setuptools
import wheel


def pip_main(argv):
    # Extract the certificates from the PAR following the example of get-pip.py
    # https://github.com/pypa/get-pip/blob/430ba37776ae2ad89/template.py#L164-L168
    cert_path = os.path.join(tempfile.mkdtemp(), "cacert.pem")
    with open(cert_path, "wb") as cert:
      cert.write(pkgutil.get_data("pip._vendor.requests", "cacert.pem"))
    argv = ["--disable-pip-version-check", "--cert", cert_path] + argv
    return pip.main(argv)

from rules_python.whl import Wheel


global_parser = argparse.ArgumentParser(
    description='Import Python dependencies into Bazel.')
subparsers = global_parser.add_subparsers()

def split_extra(s):
  parts = s.split("[")
  if len(parts) == 1:
    return parts[0], None
  return parts[0], parts[1][:-1]


# piptool build
# -------------

def build_wheel(args):
  pip_args = ["wheel"]
  if args.directory:
    pip_args += ["-w", args.directory]
  if len(args.args) > 0 and args.args[0] == '--':
    pip_args += args.args[1:]
  else:
    pip_args += args.args
  # https://github.com/pypa/pip/blob/9.0.1/pip/__init__.py#L209
  if pip_main(pip_args):
    sys.exit(1)

  cache_url = get_cache_url(args)
  if cache_url:
    wheel_filename = os.path.join(args.directory, cache_url.split('/')[-1])
    with open(wheel_filename, 'rb') as f:
      try:
        r = requests.put(cache_url, data=f.read())
        if r.status_code == requests.codes.ok:
          print("Uploaded {}".format(cache_url))
      except requests.exceptions.ConnectionError:
        # Probably no access to write to the cache
        pass

def get_cache_url(args):
  cache_base = os.environ.get("BAZEL_WHEEL_CACHE")
  if not cache_base or not args.cache_key:
    return None
  return "http://{}/{}".format(cache_base, args.cache_key)

def build(args):
  cache_url = get_cache_url(args)
  if cache_url:
    r = requests.get(cache_url)
    # 404 (not found) means cache miss
    # 502 (bad gateway) usually means the proxy dropped the request (e.g. no access to cache)
    if r.status_code in [404, 502]:
      build_wheel(args)
    else:
      r.raise_for_status()
      wheel_filename = os.path.join(args.directory, cache_url.split('/')[-1])
      with open(wheel_filename, 'w') as f:
        for chunk in r.iter_content(chunk_size=128):
          f.write(chunk)
      print("Downloaded {}".format(cache_url))
  else:
    build_wheel(args)

parser = subparsers.add_parser('build', help='Download or build a single wheel, optionally checking from cache first')
parser.set_defaults(func=build)

parser.add_argument('--directory', action='store', default='.',
                    help=('The directory into which to put .whl files.'))

parser.add_argument('--cache-key', action='store',
                    help=('The cache key to use when looking up .whl file from cache.'))

parser.add_argument('args', nargs=argparse.REMAINDER,
                    help=('Extra arguments to send to pip.'))


# piptool extract
# ---------------

def extract(args):
  whls = [Wheel(w) for w in args.whl]
  whl = whls[0]

  extra_deps = args.add_dependency or []
  drop_deps = {d: None for d in args.drop_dependency or []}

  # Extract the files into the current directory
  # TODO(conrado): do one expansion for each extra? It might be easier to create completely new
  # wheel repos
  for w in whls:
    w.expand(args.directory)

  for root, dirs, files in os.walk(args.directory):
    if root != args.directory and '__init__.py' not in files:
      open(os.path.join(root, '__init__.py'), 'a').close()

  imports = ['.']

  wheel_map = {w.name(): w for w in whls}
  external_deps = [d for d in itertools.chain(whl.dependencies(), extra_deps) if d not in wheel_map and d not in drop_deps]

  contents = []
  add_build_content = args.add_build_content or []
  for name in add_build_content:
      with open(name) as f:
          contents.append(f.read() + '\n')
  contents = '\n'.join(contents)

  parser = whl.entrypoints()
  entrypoints_build = ''
  if parser:
      if parser.has_section('console_scripts'):
          for name, location in parser.items('console_scripts'):
              # Assumes it doesn't depend on extras. TODO(conrado): fix
              entrypoint_file = 'entrypoint_%s.py' % name
              with open(os.path.join(args.directory, entrypoint_file), 'w') as f:
                  f.write("""from %s import %s as main; main()""" % tuple(location.split(":")))
              entrypoints_build += """
py_binary(
    name = "{entrypoint_name}",
    srcs = ["{entrypoint_file}"],
    main = "{entrypoint_file}",
    deps = [":pkg"],
)""".format(
        entrypoint_name='entrypoint_%s' % name,
        entrypoint_file=entrypoint_file
        )

  with open(os.path.join(args.directory, 'BUILD'), 'w') as f:
    f.write("""
package(default_visibility = ["//visibility:public"])

load("@{repository}//:requirements.bzl", "requirement")

filegroup(
  name = "wheel",
  data = ["{wheel}"],
)
py_library(
    name = "pkg",
    srcs = glob(["**/*.py"]),
    data = glob(["**/*"], exclude=["**/*.py", "**/* *", "*.whl", "BUILD", "WORKSPACE"]),
    # This makes this directory a top-level in the python import
    # search path for anything that depends on this.
    imports = [{imports}],
    deps = [
        {dependencies}
    ],
)
{extras}
{entrypoints_build}
{contents}""".format(
  wheel = whl.basename(),
  repository=args.repository,
  dependencies=''.join([
    ('\n        "%s",' % d) if d[0] == "@" else ('\n        requirement("%s"),' % d)
    for d in external_deps
  ]),
  imports=','.join(map(lambda i: '"%s"' % i, imports)),
  extras='\n\n'.join([
    """py_library(
    name = "{extra}",
    deps = [
        ":pkg",{deps}
    ],
)""".format(extra=extra,
            deps=','.join([
                'requirement("%s")' % dep
                for dep in whl.dependencies(extra)
            ]))
    for extra in args.extras or []
  ]),
  entrypoints_build=entrypoints_build,
  contents=contents))

parser = subparsers.add_parser('extract', help='Extract one or more wheels as a py_library')
parser.set_defaults(func=extract)

parser.add_argument('--whl', action='append', required=True,
                    help=('The .whl file we are expanding.'))

parser.add_argument('--repository', action='store', required=True,
                    help='The pip_import from which to draw dependencies.')

parser.add_argument('--add-dependency', action='append',
                    help='Specify additional dependencies beyond the ones specified in the wheel.')

parser.add_argument('--drop-dependency', action='append',
                    help='Specify dependencies to ignore.')

parser.add_argument('--add-build-content', action='append',
                    help='Specify lines to add to the BUILD file.')

parser.add_argument('--directory', action='store', default='.',
                    help='The directory into which to expand things.')

parser.add_argument('--extras', action='append',
                    help='The set of extras for which to generate library targets.')


# piptool resolve
# ---------------

def determine_possible_extras(whls):
  """Determines the list of possible "extras" for each .whl

  The possibility of an extra is determined by looking at its
  additional requirements, and determinine whether they are
  satisfied by the complete list of available wheels.

  Args:
    whls: a list of Wheel objects

  Returns:
    a dict that is keyed by the Wheel objects in whls, and whose
    values are lists of possible extras.
  """
  whl_map = {
    whl.name(): whl
    for whl in whls
  }

  # TODO(mattmoor): Consider memoizing if this recursion ever becomes
  # expensive enough to warrant it.
  def is_possible(name, extra):
    # If we don't have the .whl at all, then this isn't possible.
    if name not in whl_map:
      return False
    whl = whl_map[name]
    # If we have the .whl, and we don't need anything extra then
    # we can satisfy this dependency.
    if not extra:
      return True
    # If we do need something extra, then check the extra's
    # dependencies to make sure they are fully satisfied.
    for extra_dep in whl.dependencies(extra=extra):
      req = pkg_resources.Requirement.parse(extra_dep)
      # Check that the dep and any extras are all possible.
      if not is_possible(req.project_name, None):
        return False
      for e in req.extras:
        if not is_possible(req.project_name, e):
          return False
    # If all of the dependencies of the extra are satisfiable then
    # it is possible to construct this dependency.
    return True

  return {
    whl: [
      extra
      for extra in whl.extras()
      if is_possible(whl.name(), extra)
    ]
    for whl in whls
  }

def build_dep_graph(args):
    pattern = re.compile('[a-zA-Z0-9_-]+')

    requirements = {}
    for i in args.input:
        with open(i) as f:
            for l in f.readlines():
                l = l.strip()
                m = pattern.match(l)
                if m:
                    requirements[m.group()] = l

    if not args.build_dep:
        return [requirements.values()]

    deps = {}
    for i in args.build_dep:
        k,v = i.split('=')
        if k not in requirements:
            continue
        if k not in deps:
            deps[k] = []
        deps[k].append(requirements[v])

    graph = {r: set(deps[n]) if n in deps else set() for n,r in requirements.items()}
    result = list(toposort.toposort(graph))
    return result

def resolve(args):
  ordering = build_dep_graph(args)

  tempdir = tempfile.mkdtemp()

  existing_pythonpath = os.environ.get('PYTHONPATH', '')
  os.environ['PYTHONPATH'] = tempdir + ':' + existing_pythonpath

  for i, o in enumerate(ordering):
      # Install the wheels since they can be dependent at build time
      for _, _, filelist in os.walk(args.directory):
          filelist = [f for f in filelist if f.endswith('.whl')]
          filelist = [os.path.join(args.directory, f) for f in filelist]
          if filelist:
            pip_args = ["install", "-q", "--upgrade", "-t", tempdir] + filelist
            if pip_main(pip_args):
              shutil.rmtree(tempdir)
              sys.exit(1)

      # Fake init files for the degenerate packages
      for dirname, _, filelist in os.walk(tempdir):
          if '__init__.py' not in filelist:
              with open(os.path.join(dirname, '__init__.py'), 'w') as f:
                  pass

      with tempfile.NamedTemporaryFile() as f:
          with tempfile.NamedTemporaryFile() as f2:
              f.write('\n'.join(o))
              f.flush()

              f2.write('\n'.join(['\n'.join(c) for c in ordering[:i]]))
              f2.flush()

              pip_args = ["wheel"]
              #pip_args += ["--cache-dir", cache_dir]
              if args.directory:
                pip_args += ["-w", args.directory]
              #if args.input:
              #  pip_args += ["--requirement=" + i for i in args.input]
              pip_args += ["--requirement=" + f.name]
              pip_args += ["--constraint=" + f2.name]
              if len(args.args) > 0 and args.args[0] == '--':
                pip_args += args.args[1:]
              else:
                pip_args += args.args
              # https://github.com/pypa/pip/blob/9.0.1/pip/__init__.py#L209
              if pip_main(pip_args):
                shutil.rmtree(tempdir)
                sys.exit(1)

  shutil.rmtree(tempdir)

  # Find all http/s URLs explicitly stated in the requirements.txt file - these
  # URLs will be passed through to the bazel rules below to support wheels that
  # are not in any index.
  url_pattern = re.compile(r'(https?://\S+).*')
  def get_url(line):
    m = url_pattern.match(line)
    return m.group(1) if m else None
  requirements_urls = []
  for inputfile in args.input:
    with open(inputfile) as f:
      requirements_urls += [get_url(x) for x in f.readlines() if get_url(x)]
  def requirement_download_url(wheel_name):
    for url in requirements_urls:
      if wheel_name in url:
        return url
    return None

  # Enumerate the .whl files we downloaded.
  def wheels_from_dir(dir):
    def list_whls(dir):
      for root, _, filenames in os.walk(dir + "/"):
        for fname in filenames:
          if fname.endswith('.whl'):
            yield Wheel(os.path.join(root, fname))
    whls = list(list_whls(dir))
    whls.sort(key=lambda x: x.name())
    return whls

  whls = wheels_from_dir(args.directory)
  possible_extras = determine_possible_extras(whls)

  def quote(string):
    return '"{}"'.format(string)

  whl_map = {
    whl.name(): whl
    for whl in whls
  }

  def transitive_deps(wheel, extra=None, collected=None):
    deps = wheel.dependencies(extra)
    if collected is None:
      collected = set()
    for dep in wheel.dependencies(extra):
      if dep not in collected:
        collected.add(dep)
        d, extra = split_extra(dep)
        deps = deps.union(transitive_deps(whl_map[d], extra, collected))
    return deps

  if args.output_format == 'download':
    # We are generating a checked-in version of requirements.bzl.
    # For determinism, avoid clashes with other pip_import repositories,
    # and prefix the current pip_import domain to the lib repo name.
    lib_repo = lambda w: w.repository_name(prefix=args.name)
    # Each wheel has its own repository that, refer to that.
    wheel_repo = lambda w: lib_repo(w) + '_wheel'
  else:
    # We are generating requirements.bzl to the bazel output area (legacy mode).
    # Use the good old 'pypi__' refix.
    lib_repo = lambda w: w.repository_name(prefix='pypi')
    # Wheels are downloaded to the pip_import repository, refer to that.
    wheel_repo = lambda w: args.name

  def whl_library(wheel):
    attrs = []
    attrs += [("name", quote(lib_repo(wheel)))]
    attrs += [("version", quote(wheel.version()))]
    attrs += [("wheel_name", quote(wheel.basename()))]
    url = requirement_download_url(wheel.basename())
    if url:
      attrs += [("urls", '[{}]'.format(quote(url)))]
    if args.output_format != 'download':
      attrs += [("whl", '"@{}//:{}"'.format(args.name, wheel.basename()))]
    extras = ', '.join([quote(extra) for extra in sorted(possible_extras.get(wheel, []))])
    if extras != '':
      attrs += [("extras", '[{}]'.format(extras))]
    runtime_deps = ', '.join([quote(dep) for dep in wheel.dependencies()])
    #if runtime_deps != '':
    #  attrs["runtime_deps"] = '[{}]'.format(runtime_deps)
    transitive_runtime_deps = set([split_extra(dep)[0] for dep in transitive_deps(wheel)])
    transitive_runtime_deps = ', '.join([quote(dep) for dep in sorted(transitive_runtime_deps)])
    if transitive_runtime_deps != '':
      attrs += [("transitive_runtime_deps", '[{}]'.format(transitive_runtime_deps))]

    # Indentation here matters.  whl_library must be within the scope
    # of the function below.  We also avoid reimporting an existing WHL.
    return """"{}": {{
      {},
    }},""".format(wheel.name(), ",\n      ".join(['"{}": {}'.format(k, v) for k, v in attrs]))

  requirements_map = ',\n  '.join([
    ',\n  '.join([
      '"{name}": "@{repo}//:pkg",\n  "{name}:dirty": "@{repo}_dirty//:pkg"'.format(
          name=whl.name(), repo=lib_repo(whl))
    ] + [
      # For every extra that is possible from this requirements.txt
      '"{name}[{extra_lower}]": "@{repo}//:{extra}",\n  "{name}:dirty[{extra_lower}]": "@{repo}_dirty//:{extra}"'.format(
        name=whl.name(), repo=lib_repo(whl), extra=extra, extra_lower=extra.lower())
      for extra in sorted(possible_extras.get(whl, []))
    ])
    for whl in whls
  ])

  with open(args.output, 'w') as f:
    f.write("""\
# Install pip requirements.
#
{comment}

load("@{name}//python:whl.bzl", "whl_library")

_requirements = {{
  {requirements_map}
}}

all_requirements = _requirements.values()
requirements_map = _requirements

def requirement_repo(name):
  return requirement(name).split(":")[0]

def requirement(name):
  key = name.lower()
  if key not in _requirements:
    fail("Could not find pip-provided dependency: '%s'" % name)
  return _requirements[key]

def pip_install():
  all_libs = {{
    {all_libs}
  }}

  for key, attributes in all_libs.items():
    whl_library(
      key = key,
      all_libs = all_libs,{python}
      **attributes
    )

""".format(comment='\n'.join(['# Generated from ' + i for i in args.input]),
           name=args.name,
           all_libs='\n    '.join(map(whl_library, whls)),
           requirements_map=requirements_map,
           python='\n      python = "{}",'.format(args.python) if args.python else ''))

parser = subparsers.add_parser('resolve', help='Resolve requirements.bzl from requirements.txt')
parser.set_defaults(func=resolve)

parser.add_argument('--name', action='store', required=True,
                    help=('The namespace of the import.'))

parser.add_argument('--build-dep', action='append',
                    help=('Build-time dependency of wheels.'))

parser.add_argument('--input', action='append', required=True,
                    help=('The requirements.txt file(s) to import.'))

parser.add_argument('--output', action='store', required=True,
                    help=('The requirements.bzl file to export.'))

parser.add_argument('--output-format', choices=['refer', 'download'], default='refer',
                    help=('How whl_library rules should obtain the wheel.'))

parser.add_argument('--directory', action='store', default='.',
                    help=('The directory into which to put .whl files.'))

parser.add_argument('--python', action='store',
                    help=('The python interpreter to use for building wheels.'))

parser.add_argument('args', nargs=argparse.REMAINDER,
                    help=('Extra arguments to send to pip.'))


def main():
  args = global_parser.parse_args()
  args.func(args)

if __name__ == '__main__':
  main()
