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
"""Import pip requirements into Bazel."""

def _expand_deps_to_dict(d):
    return "".join(['\n    "{}": [{}],'.format(k, ", ".join(['"{}"'.format(v) for v in vv])) for k, vv in d.items()])

def _expand_env_to_dict(d):
    return "".join(['\n    "{}": {{{}}},'.format(k, ", ".join(['"{}": "{}"'.format(*v.split('=')) for v in vv])) for k, vv in d.items()])

def _expand_build_deps_to_dict(d):
    return "".join(['\n    "{}": "{}",'.format(k, v) for k, v in d.items()])

def _expand_array(array):
    return "".join(['\n    "{}",'.format(item) for item in array])

def _pip_import_impl(repository_ctx):
  """Core implementation of pip_import."""

  # Add an empty top-level BUILD file.
  # This is because Bazel requires BUILD files along all paths accessed
  # via //this/sort/of:path and we wouldn't be able to load our generated
  # requirements.bzl without it.
  repository_ctx.file("BUILD", """
package(default_visibility = ["//visibility:public"])
sh_binary(
    name = "update",
    srcs = ["update.sh"],
)
""")

  repository_ctx.file("python/BUILD", "")
  repository_ctx.template(
    "python/whl.bzl",
    Label("//rules_python:whl.bzl.tpl"),
    substitutions = {
      "%{repo}": repository_ctx.name,
      "%{pip_args}": ", ".join(["\"%s\"" % arg for arg in repository_ctx.attr.pip_args]),
      "%{requirements}": str(repository_ctx.attr.requirements_bzl),
      "%{additional_buildtime_deps}": _expand_deps_to_dict(repository_ctx.attr.additional_buildtime_deps),
      "%{additional_buildtime_env}": _expand_env_to_dict(repository_ctx.attr.additional_buildtime_env),
      "%{additional_runtime_deps}": _expand_deps_to_dict(repository_ctx.attr.additional_runtime_deps),
      "%{additional_build_content}": _expand_build_deps_to_dict(repository_ctx.attr.additional_build_content),
      "%{remove_runtime_deps}": _expand_deps_to_dict(repository_ctx.attr.remove_runtime_deps),
      "%{patch_runtime}": _expand_deps_to_dict(repository_ctx.attr.patch_runtime),
    })

  repository_ctx.template(
    "update.sh",
    Label("//rules_python:update.sh.tpl"),
    substitutions = {
      "%{python}": str(repository_ctx.path(repository_ctx.attr.python)) if repository_ctx.attr.python else "python",
      "%{python_label}": str(repository_ctx.attr.python) if repository_ctx.attr.python else "",
      "%{piptool}": str(repository_ctx.path(repository_ctx.attr._script)),
      "%{name}": repository_ctx.attr.name,
      "%{build_dependencies}": " ".join(['%s=%s' % (k, vv) for k,v in repository_ctx.attr.additional_buildtime_deps.items() for vv in v]),
      "%{requirements_txt}": " ".join(["\"%s\"" % str(repository_ctx.path(f)) for f in repository_ctx.attr.requirements]),
      "%{requirements_bzl}": str(repository_ctx.path(repository_ctx.attr.requirements_bzl)) if repository_ctx.attr.requirements_bzl else "",
      "%{directory}": str(repository_ctx.path("")),
      "%{pip_args}": " ".join(["\"%s\"" % arg for arg in repository_ctx.attr.pip_args]),
    },
    executable=True,
  )

  if repository_ctx.attr.requirements_bzl:
    repository_ctx.symlink(repository_ctx.path(repository_ctx.attr.requirements_bzl), "requirements.bzl")
  else:
    cmd = [
        "python", repository_ctx.path(repository_ctx.attr._script), "resolve",
        "--name", repository_ctx.attr.name,
        "--output", repository_ctx.path("requirements.bzl"),
        "--directory", repository_ctx.path(""),
    ]
    cmd += ["--input=" + str(repository_ctx.path(f)) for f in repository_ctx.attr.requirements]
    cmd += ["--"] + repository_ctx.attr.pip_args
    cmd += ["--cache-dir", repository_ctx.path("pip-cache")]
    result = repository_ctx.execute(cmd, quiet=False)

    if result.return_code:
        fail("pip_import failed: %s (%s)" % (result.stdout, result.stderr))

pip_import = repository_rule(
    attrs = {
        "requirements": attr.label_list(
            allow_files = True,
            mandatory = True,
        ),
        "requirements_bzl": attr.label(
            allow_files = True,
            single_file = True,
        ),
        "pip_args": attr.string_list(),
        "additional_buildtime_deps": attr.string_list_dict(),
        "additional_buildtime_env": attr.string_list_dict(),
        "additional_runtime_deps": attr.string_list_dict(),
        "additional_build_content": attr.string_dict(),
        "remove_runtime_deps": attr.string_list_dict(),
        "patch_runtime": attr.string_list_dict(),
        "python": attr.label(
            executable = True,
            cfg = "host",
        ),
        "_script": attr.label(
            executable = True,
            default = Label("//tools:piptool.par"),
            cfg = "host",
        ),
    },
    implementation = _pip_import_impl,
)

"""A rule for importing <code>requirements.txt</code> dependencies into Bazel.

This rule imports a <code>requirements.txt</code> file and generates a new
<code>requirements.bzl</code> file.  This is used via the <code>WORKSPACE</code>
pattern:
<pre><code>pip_import(
    name = "foo",
    requirements = ":requirements.txt",
)
load("@foo//:requirements.bzl", "pip_install")
pip_install()
</code></pre>

You can then reference imported dependencies from your <code>BUILD</code>
file with:
<pre><code>load("@foo//:requirements.bzl", "requirement")
py_library(
    name = "bar",
    ...
    deps = [
       "//my/other:dep",
       requirement("futures"),
       requirement("mock"),
    ],
)
</code></pre>

Or alternatively:
<pre><code>load("@foo//:requirements.bzl", "all_requirements")
py_binary(
    name = "baz",
    ...
    deps = [
       ":foo",
    ] + all_requirements,
)
</code></pre>

Args:
  requirements: The label of a requirements.txt file.
"""

def _pip_version_proxy_impl(ctx):
    loads = "".join(["""\
load("{repo}//:requirements.bzl", requirements_map_{key} = "requirements_map")
""".format(repo=v, key=k) for k, v in ctx.attr.values.items()])

    gathers = "".join(["""\
    for req, label in requirements_map_{key}.items():
        if req not in all_reqs:
            all_reqs[req] = {{}}
        all_reqs[req]["{key}"] = label
""".format(key=k) for k in ctx.attr.values.keys()])

    config_settings = "".join(["""\
config_setting(
    name = "{key}",
    define_values = {{
        "{define}": "{key}",
    }},
)
""".format(define=ctx.attr.define, key=k) for k in ctx.attr.values.keys()])

    specific_macros = "".join(["""\
def requirement_{key}(r):
    return "@{name}//:{key}__%s" % _sanitize(r)
""".format(name=ctx.attr.name, key=k) for k in ctx.attr.values.keys()])

    ctx.file("BUILD.bazel", content="""\
load("@{name}//:requirements.bzl", "proxy_install")
package(default_visibility = ["//visibility:public"])

proxy_install()

{config_settings}
""".format(name=ctx.attr.name, config_settings=config_settings))

    ctx.file("requirements.bzl", content="""\
{loads}

def _sanitize(s):
    return s.replace('[', '_').replace(']', '_').replace(':', '_').replace('-', '_')

# Called from autogenerated BUILD file.
# Generate proxy py_library targets that use select() to pick the real wheel.
def proxy_install():
    all_reqs = {{}}
{gathers}
    for req, gathers in all_reqs.items():
        conditions = {{k: [v] for k, v in gathers.items()}}
        name = _sanitize(req)
        native.py_library(
            name = name,
            deps = select(conditions),
        )
        for py_version, label in gathers.items():
            native.py_library(
                name = py_version + "__" + name,
                deps = select({{
                    py_version: [label],
                    "//conditions:default": []
                }}),
            )


def requirement(r):
    return "@{name}//:%s" % _sanitize(r)
{specific_macros}
""".format(loads=loads, gathers=gathers, specific_macros=specific_macros, name=ctx.attr.name))

pip_version_proxy = repository_rule(
    attrs = {
        "define": attr.string(),
        "values": attr.string_dict(),
        "_script": attr.label(
            executable = True,
            default = Label("//tools:piptool.par"),
            cfg = "host",
        ),
        "python": attr.label(
            executable = True,
            cfg = "host",
        ),
    },
    implementation = _pip_version_proxy_impl,
)

"""A rule for proxying requirements between different python runtimes.

This rule generates a <code>requirements.bzl</code> file that provides
a <code>requirements()</code> function that resolves to the correct version
of python dependencies depending on the current python runtime.
This is used via the <code>WORKSPACE</code> pattern:

<pre><code>pip_import(
    name = "pip_deps2",
    requirements = ["//:requirements-pip.txt"],
    python = "@python2//:bin/python",
)
pip_import(
    name = "pip_deps3",
    requirements = ["//:requirements-pip.txt"],
    python = "@python3//:bin/python",
)
load("@pip_deps2//:requirements.bzl", pip_install2 = "pip_install")
pip_install2()
load("@pip_deps3//:requirements.bzl", pip_install3 = "pip_install")
pip_install3()

pip_version_proxy(
    name = "pip_deps",
    define = "python",
    values = {
        "py2": "@pip_deps2",
        "py3": "@pip_deps3",
    },
)
</code></pre>

When importing dependencies from a <code>BUILD</code> file with

<pre><code>load("@pip_deps//:requirements.bzl", "requirement")
py_library(
    name = "bar",
    ...
    deps = [
       requirement("mock"),
    ],
)
</code></pre>

the <code>requirement</code> macro will resolve to <code>pip_deps2</code> when
building with <code>--define python=py2</code>, and to <code>pip_deps3</code> when
building with <code>--define python=py3</code>.

Args:
  define: The key of the <code>--define</code> that selects the python version.
  values: For each item in the dict, the key is the value of the <code>--define</code> to match,
          and the value is the name of the pip_import repository rule that provides
          the pip dependencies for that python runtime.
"""


def pip_repositories():
  """Pull in dependencies needed for pulling in pip dependencies.

  A placeholder method that will eventually pull in any dependencies
  needed to install pip dependencies.
  """
  pass
