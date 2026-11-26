# CI failure: CMake version too old after the 5.0 upgrade

After the Orbit 5.0 branch merged, every job on the self-hosted Ubuntu 22.04 runners failed in
the first configure step.

## Symptom

```text
CMake Error at CMakeLists.txt:1 (cmake_minimum_required):
  CMake 3.28 or higher is required.  You are running version 3.22.1


-- Configuring incomplete, errors occurred!
```

## Cause

Orbit 5.0 raised `cmake_minimum_required` to 3.28 for C++20 module scanning. The self-hosted
runners install CMake from Ubuntu 22.04's own package archive, which provides 3.22. The
GitHub-hosted images had a newer CMake preinstalled, so the change passed review there.

## Fix

The runner setup now installs a pinned CMake from PyPI instead of the distribution package:

```bash
python3 -m pip install "cmake==3.31.*"
cmake --version
```

## Prevention

The required CMake version is defined once, in `ci/versions.env`, and both the runner setup
script and a configure-time check read it, so raising the minimum fails the runner image build
rather than every job.
