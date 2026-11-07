#!/usr/bin/env bash
# Monta o AppImage do Uninstrumephy (Linux x86_64).
#
#   Uso: packaging/build_appimage.sh <versão>       ex.: packaging/build_appimage.sh 1.0.0
#
# Gera dist/Uninstrumephy-<versão>-x86_64.AppImage e o testa com --self-test.
# É o mesmo script usado pelo GitHub Actions (.github/workflows/release.yml).
#
# Precisa de: curl, tar, gcc, make, os cabeçalhos da ALSA (para compilar a
# PortAudio) e a libxcb-cursor (embutida para o Qt abrir em sessões X11):
#   Ubuntu/Debian: sudo apt install build-essential libasound2-dev libxcb-cursor0 curl
#   Fedora:        sudo dnf install gcc make alsa-lib-devel xcb-util-cursor curl
#
# Variáveis opcionais (reaproveitar downloads em builds locais):
#   PYTHON_VERSION   Python embutido (padrão: 3.12)
#   BASE_APPIMAGE    AppImage do python-appimage já baixado
#   APPIMAGETOOL     appimagetool já baixado
#   PORTAUDIO_LIB    libportaudio.so.2 já compilada (com suporte a ALSA)
#   XCB_CURSOR_LIB   libxcb-cursor.so.0 a embutir (padrão: a do sistema)
#   TORCH_INDEX_URL  índice do PyTorch (padrão: versão só para CPU)

set -euo pipefail

VERSION="${1:-}"
[[ -n "$VERSION" ]] || { echo "Uso: $0 <versão>   (ex.: $0 1.0.0)" >&2; exit 2; }
VERSION="${VERSION#v}"

PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
PORTAUDIO_TAG="v19.7.0"
ARCH="x86_64"
MAX_ASSET_BYTES=$((2 * 1024 * 1024 * 1024))   # limite do GitHub por arquivo de release

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/build/appimage"
APPDIR="$WORK/AppDir"
DIST="$ROOT/dist"
OUTPUT="$DIST/Uninstrumephy-$VERSION-$ARCH.AppImage"
APP="$APPDIR/opt/uninstrumephy"

# Sem isto, o pip veria os pacotes do usuário (~/.local) como já instalados
# e não os copiaria para dentro do AppImage.
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME

step() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERRO: %s\n' "$*" >&2; exit 1; }

# Baixa um arquivo de uma release do GitHub. Usa o gh (autenticado, como no
# Actions) se disponível; senão, lê a lista pública de arquivos da release.
download_release_asset() {
    local repo="$1" tag="$2" glob="$3" regex="$4" dest="$5" name
    if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
        gh release download "$tag" --repo "$repo" --pattern "$glob" --output "$dest" --clobber
        return
    fi
    name="$(curl -fsSL "https://github.com/$repo/releases/expanded_assets/$tag" \
        | grep -oE "$regex" | head -n 1)" || true
    [[ -n "$name" ]] || die "não encontrei '$glob' na release $tag de $repo"
    curl -fL --retry 3 -o "$dest" "https://github.com/$repo/releases/download/$tag/$name"
}

rm -rf "$WORK"
mkdir -p "$WORK" "$DIST"
cd "$WORK"

step "1/8 Python $PYTHON_VERSION portátil (python-appimage, manylinux_2_28)"
if [[ -n "${BASE_APPIMAGE:-}" ]]; then
    cp "$BASE_APPIMAGE" python.AppImage
else
    download_release_asset niess/python-appimage "python$PYTHON_VERSION" \
        "python$PYTHON_VERSION.*-manylinux_2_28_$ARCH.AppImage" \
        "python${PYTHON_VERSION//./\\.}\.[0-9]+-cp[0-9]+-cp[0-9]+-manylinux_2_28_$ARCH\.AppImage" \
        python.AppImage
fi
chmod +x python.AppImage
./python.AppImage --appimage-extract >/dev/null   # não precisa de FUSE
mv squashfs-root "$APPDIR"
PYTHON=("$APPDIR/AppRun")                          # AppRun original: o Python embutido
[[ -x "$APPDIR/usr/bin/python$PYTHON_VERSION" ]] \
    || die "estrutura inesperada do python-appimage: falta usr/bin/python$PYTHON_VERSION"
SITE="$("${PYTHON[@]}" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
[[ "$SITE" == "$APPDIR"/* ]] || die "o site-packages ($SITE) não está dentro do AppDir"

step "2/8 Dependências Python (PyTorch só para CPU)"
"${PYTHON[@]}" -m pip install --no-cache-dir --upgrade pip
"${PYTHON[@]}" -m pip install --no-cache-dir --index-url "$TORCH_INDEX_URL" torch torchaudio
"${PYTHON[@]}" -m pip install --no-cache-dir -r "$ROOT/requirements.txt"
# Uma dependência pode puxar o PyTorch com CUDA do PyPI (vários GB):
"${PYTHON[@]}" -c 'import sys, torch; sys.exit(torch.version.cuda is not None)' \
    || die "o PyTorch instalado é a versão com CUDA; o AppImage passaria do limite de 2 GB"
rm -rf "$SITE/torch/include" "$SITE/torch/share/cmake"   # cabeçalhos C++, só para compilar extensões

step "3/8 Código do Uninstrumephy"
mkdir -p "$APP/lib"
cp -r "$ROOT/main.py" "$ROOT/core" "$ROOT/gui" "$ROOT/presets" \
      "$ROOT/requirements.txt" "$ROOT/COPYING" "$ROOT/README.md" "$APP/"
find "$APP" -name __pycache__ -type d -prune -exec rm -rf {} +
"${PYTHON[@]}" -m compileall -q "$APP"   # o AppImage é somente leitura em uso

step "4/8 Bibliotecas nativas: PortAudio $PORTAUDIO_TAG (reserva) e libxcb-cursor"
if [[ -n "${PORTAUDIO_LIB:-}" ]]; then
    cp "$PORTAUDIO_LIB" "$APP/lib/libportaudio.so.2"
else
    curl -fsSL "https://github.com/PortAudio/portaudio/archive/refs/tags/$PORTAUDIO_TAG.tar.gz" | tar xz
    (
        cd "portaudio-${PORTAUDIO_TAG#v}"
        # Só ALSA: no Linux atual o PipeWire/PulseAudio atende pela ALSA.
        ./configure --quiet --disable-static --with-alsa --without-jack --without-oss
        make -j"$(nproc)" >/dev/null
    )
    cp "portaudio-${PORTAUDIO_TAG#v}/lib/.libs/libportaudio.so.2.0.0" "$APP/lib/libportaudio.so.2"
fi
grep -q "PaAlsa_" "$APP/lib/libportaudio.so.2" \
    || die "a PortAudio foi compilada sem suporte a ALSA (instale libasound2-dev / alsa-lib-devel)"

# O Qt 6.5+ exige a libxcb-cursor para abrir em sessões X11, e várias distros
# não a instalam por padrão (ex.: Ubuntu): sem ela, o programa nem abre. As
# bibliotecas do Qt procuram dependências primeiro na própria pasta (RUNPATH
# $ORIGIN), então basta copiá-la para lá. As dependências dela (libxcb-image,
# -render, -render-util) o Qt já exige de qualquer forma.
QT_LIB="$("${PYTHON[@]}" -c 'import os, PyQt6; print(os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "lib"))')"
XCB_CURSOR="${XCB_CURSOR_LIB:-$(ldconfig -p | awk '/libxcb-cursor\.so\.0 .*x86-64/ {print $NF; exit}')}"
[[ -n "$XCB_CURSOR" && -f "$XCB_CURSOR" ]] \
    || die "libxcb-cursor não encontrada (instale libxcb-cursor0 / xcb-util-cursor)"
[[ -f "$QT_LIB/libQt6XcbQpa.so.6" ]] || die "estrutura inesperada do PyQt6: falta $QT_LIB/libQt6XcbQpa.so.6"
cp -L "$XCB_CURSOR" "$QT_LIB/libxcb-cursor.so.0"

step "5/8 Atalho, ícone e AppRun"
rm -f "$APPDIR"/*.desktop "$APPDIR"/*.png "$APPDIR"/*.svg "$APPDIR/.DirIcon" "$APPDIR/AppRun"
rm -rf "$APPDIR/usr/share/metainfo" "$APPDIR/usr/share/applications"
cp "$ROOT/packaging/uninstrumephy.desktop" "$APPDIR/uninstrumephy.desktop"
cp "$ROOT/gui/icons/app.png" "$APPDIR/uninstrumephy.png"
ln -s uninstrumephy.png "$APPDIR/.DirIcon"
mkdir -p "$APPDIR/usr/share/icons/hicolor/512x512/apps"
cp "$ROOT/gui/icons/app.png" "$APPDIR/usr/share/icons/hicolor/512x512/apps/uninstrumephy.png"
sed "s/@PYTHON_VERSION@/$PYTHON_VERSION/g" "$ROOT/packaging/AppRun" > "$APPDIR/AppRun"
chmod 755 "$APPDIR/AppRun"

step "6/8 appimagetool"
TOOL="${APPIMAGETOOL:-}"
if [[ -z "$TOOL" ]]; then
    TOOL="$WORK/appimagetool"
    download_release_asset AppImage/appimagetool continuous \
        "appimagetool-$ARCH.AppImage" "appimagetool-$ARCH\.AppImage" "$TOOL"
    chmod +x "$TOOL"
fi
rm -f "$OUTPUT"
ARCH="$ARCH" APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUTPUT"

step "7/8 Tamanho"
size="$(stat -c %s "$OUTPUT")"
printf '%s: %d MB\n' "$(basename "$OUTPUT")" $((size / 1024 / 1024))
(( size < MAX_ASSET_BYTES )) || die "o AppImage passou do limite de 2 GB por arquivo do GitHub"

step "8/8 Autoteste do AppImage"
# HOME separado: o autoteste não mexe nos dados reais de quem está montando.
# Sem tela e sem som: o backend de áudio fixo evita que o player do Qt trave
# em máquinas com a biblioteca do PipeWire mas sem a configuração dele (como
# servidores de CI). Quem roda o programa normalmente usa o áudio do sistema.
HOME="$WORK/home" XDG_DATA_HOME="$WORK/home/.local/share" \
QT_QPA_PLATFORM=offscreen QT_AUDIO_BACKEND=alsa \
    "$OUTPUT" --appimage-extract-and-run --self-test \
    || die "o autoteste do AppImage falhou (veja as linhas [FALHA] acima)"

printf '\nPronto: %s\n' "$OUTPUT"
