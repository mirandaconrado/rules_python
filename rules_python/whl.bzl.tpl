load("@io_bazel_rules_python//python:whl.bzl", "download_or_build_wheel", "extract_wheels")

_additional_buildtime_deps = {%{additional_buildtime_deps}
}
_additional_buildtime_env = {%{additional_buildtime_env}
}
_additional_runtime_deps = {%{additional_runtime_deps}
}
_additional_build_content = {%{additional_build_content}
}
_remove_runtime_deps = {%{remove_runtime_deps}
}
_patch_runtime = {%{patch_runtime}
}

def get_transitive_deps(all_libs, key):
    res = depset(all_libs[key].get("transitive_runtime_deps", []))
    if key in _additional_runtime_deps:
        for d in _additional_runtime_deps[key]:
            res = res + get_transitive_deps(d)
    return res

def _global_wheel(all_libs, key):
  return "@%s_wheel//:%s" % (all_libs[key]["name"], all_libs[key]["wheel_name"])

def _wheel(all_libs, key):
  return "@%s_wheel//:%s" % (all_libs[key]["name"], all_libs[key]["wheel_name"])

def _extracted_wheel(all_libs, key):
  return "@%s//:%s" % (all_libs[key]["name"], all_libs[key]["wheel_name"])

def whl_library(key, all_libs, name, wheel_name, version=None, urls=None, whl=None, transitive_runtime_deps=[], runtime_deps=[], extras=[], python=None):
    repository = "%{repo}"
    dirty_repo_name = "%s_dirty" % name
    wheel_repo_name = "%s_wheel" % name
    requirement = None if urls != None else "%s==%s" % (key, version)

    buildtime_deps = _additional_buildtime_deps.get(key, [])
    buildtime_env = _additional_buildtime_env.get(key, {})
    additional_runtime_deps = _additional_runtime_deps.get(key, [])
    additional_build_content = _additional_build_content.get(key, None)
    remove_runtime_deps = _remove_runtime_deps.get(key, [])
    patch_runtime = _patch_runtime.get(key, [])

    build_deps = depset()
    for d in buildtime_deps:
        build_deps = build_deps + get_transitive_deps(all_libs, d) + depset([d])
    build_deps = build_deps.to_list()

    if name not in native.existing_rules():
        if whl:
            extract_wheels(
                name = name,
                wheels = [whl],
                additional_runtime_deps = additional_runtime_deps,
                additional_build_content = additional_build_content,
                remove_runtime_deps = remove_runtime_deps,
                patch_runtime = patch_runtime,
                repository = repository,
                extras = extras,
                python = python,
            )
        else:
            download_or_build_wheel(
                name = wheel_repo_name,
                requirement = requirement,
                urls = urls,
                wheel_name = wheel_name,
                buildtime_env = buildtime_env,
                buildtime_deps = [_extracted_wheel(all_libs, d) for d in build_deps],
                pip_args = [%{pip_args}],
                python = python,
            )
            extract_wheels(
                name = name,
                wheels = ["@%s//:%s" % (wheel_repo_name, wheel_name)],
                additional_runtime_deps = additional_runtime_deps,
                additional_build_content = additional_build_content,
                remove_runtime_deps = remove_runtime_deps,
                patch_runtime = patch_runtime,
                repository = repository,
                extras = extras,
                python = python,
            )

    if dirty_repo_name not in native.existing_rules():
        # Make sure the current package's wheel is the first element in the "wheels" list,
        # since piptool will generate the BUILD file based on that.  The remaining wheels
        # on the list should be all transitive runtime dependencies (unless explicitly
        # dropped at pip_import rule level).
        dep_keys = {d.split("[")[0]: None for d in transitive_runtime_deps if d not in remove_runtime_deps}
        if whl:
            wheels = ["@%s//:%s" % (repository, all_libs[key]["wheel_name"])] + \
                     ["@%s//:%s" % (repository, all_libs[key]["wheel_name"]) for key in dep_keys]
        else:
            wheels = [_wheel(all_libs, key)] + \
                     [_wheel(all_libs, d) for d in dep_keys]
        extract_wheels(
            name = dirty_repo_name,
            wheels = wheels,
            additional_runtime_deps = additional_runtime_deps,
            additional_build_content = additional_build_content,
            remove_runtime_deps = remove_runtime_deps,
            patch_runtime = patch_runtime,
            repository = repository,
            extras = extras,
            python = python,
        )
