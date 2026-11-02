[app]
title = HED 11.1.2
package.name = hed
package.domain = org.lucas
source.dir = .
source.include_exts = py,png,jpg,kv,json,gz
source.exclude_dirs = .github, bin, .buildozer, sf, libs, motores, tests
version = 11.1.2.17
# versionCode sempre crescente (11.2.1 = 924110201) para instalar por cima sem perder os dados
android.numeric_version = 924110370
requirements = python3,kivy==2.3.0,chess,certifi
orientation = portrait
fullscreen = 0

android.api = 34
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.permissions = INTERNET

# Stockfish compilado no workflow e empacotado como biblioteca nativa
# (Android 10+ só executa binários da pasta de bibliotecas do app)
android.add_libs_arm64_v8a = libs/arm64-v8a/*.so

p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 0
