[app]
title = HED 11.2
package.name = hed
package.domain = org.lucas
source.dir = .
source.include_exts = py,png,jpg,kv,json
source.exclude_dirs = .github, bin, .buildozer
version = 11.2.0
requirements = python3,kivy==2.3.0
orientation = portrait
fullscreen = 0

android.api = 34
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.permissions =

p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 0
