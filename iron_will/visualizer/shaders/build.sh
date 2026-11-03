#!/usr/bin/env bash
# Recompile the GPU shaders after editing a .frag file.
#
# Qt 6 doesn't take GLSL directly: shaders are shipped as .qsb bundles holding
# GLSL (OpenGL / GLES), HLSL (Direct3D), MSL (Metal) and SPIR-V (Vulkan)
# variants, so one file works on every graphics backend. The compiler (qsb)
# ships inside PySide6, so nothing extra is needed. The .qsb files are
# committed, so users never have to run this.
set -euo pipefail
cd "$(dirname "$0")"
QSB="$(python3 -c 'import PySide6, os; print(os.path.join(os.path.dirname(PySide6.__file__), "qsb"))')"
for src in *.frag; do
  "$QSB" --glsl "100es,120,150" --hlsl 50 --msl 12 -o "$src.qsb" "$src"
  echo "built $src.qsb"
done
