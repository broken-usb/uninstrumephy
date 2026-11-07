#!/usr/bin/env bash
# Monta o AppImage do Uninstrumephy (Linux x86_64).
#
#   Uso: packaging/build_appimage.sh <versão>       ex.: packaging/build_appimage.sh 1.0.0
#
# Gera dist/Uninstrumephy-<versão>-x86_64.AppImage e o testa com --self-test.
# É o mesmo script usado pelo GitHub Actions (.github/workflows/release.yml).
#
# Precisa de: curl, git, gcc, make, sha256sum, mksquashfs (squashfs-tools),
# os cabeçalhos da ALSA (para compilar a PortAudio) e a libxcb-cursor
# (embutida para o Qt abrir em X11):
#   Ubuntu/Debian: sudo apt install build-essential git squashfs-tools libasound2-dev libxcb-cursor0 curl
#   Fedora:        sudo dnf install gcc make git squashfs-tools alsa-lib-devel xcb-util-cursor curl
#
# Variáveis opcionais (reaproveitar arquivos em builds locais; quem as define
# é responsável pela origem do arquivo, que NÃO é conferida pelo SHA-256):
#   BASE_APPIMAGE    AppImage do python-appimage já baixado
#   PYTHON_VERSION   versão desse AppImage (só junto com BASE_APPIMAGE)
#   RUNTIME_FILE     runtime do AppImage (type2-runtime) já baixado
#   PORTAUDIO_LIB    libportaudio.so.2 já compilada (com suporte a ALSA)
#   XCB_CURSOR_LIB   libxcb-cursor.so.0 a embutir (padrão: a do sistema)
#   TORCH_INDEX_URL  índice do PyTorch (padrão: versão só para CPU)

set -euo pipefail

VERSION="${1:-}"
[[ -n "$VERSION" ]] || { echo "Uso: $0 <versão>   (ex.: $0 1.0.0)" >&2; exit 2; }
VERSION="${VERSION#v}"

# --------------------------------------------------------------------------- #
# Downloads externos: versão exata + SHA-256
# --------------------------------------------------------------------------- #
# Tudo o que vem de fora e é executado ou embutido no AppImage está fixado
# numa versão exata e conferido pelo SHA-256 antes do uso. Assim, uma
# alteração nesses repositórios (nova versão ou arquivo adulterado) faz o
# build PARAR, em vez de entrar silenciosamente no AppImage publicado.
#
# Para atualizar uma versão: na página da release do projeto, o GitHub mostra
# o SHA-256 ao lado de cada arquivo ("sha256:..."). Troque a URL e o hash
# juntos. O python-appimage substitui o arquivo quando sai um novo 3.12.x:
# se o download der 404, é hora de atualizar estas duas linhas.
PYTHON_APPIMAGE_VERSION="3.12"
PYTHON_APPIMAGE_URL="https://github.com/niess/python-appimage/releases/download/python3.12/python3.12.15-cp312-cp312-manylinux_2_28_x86_64.AppImage"
PYTHON_APPIMAGE_SHA256="929ce69b45955bfc74af81fd65a65c3ad240593c99b3574466a94ebf0f987ebf"

# Parte executável que fica no início de todo AppImage: ao abrir o arquivo,
# ela monta (ou extrai) o sistema de arquivos comprimido anexado logo depois.
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64"
RUNTIME_SHA256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"

# A PortAudio não publica arquivos de release: o código-fonte vem do Git e é
# conferido pelo hash do commit (que identifica o conteúdo exato).
PORTAUDIO_REPO="https://github.com/PortAudio/portaudio.git"
PORTAUDIO_TAG="v19.7.0"
PORTAUDIO_COMMIT="147dd722548358763a8b649b3e4b41dfffbcfbb6"

if [[ -n "${BASE_APPIMAGE:-}" ]]; then
    PYTHON_VERSION="${PYTHON_VERSION:-$PYTHON_APPIMAGE_VERSION}"
else
    PYTHON_VERSION="$PYTHON_APPIMAGE_VERSION"
fi
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
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

# Baixa um arquivo e só o entrega se o SHA-256 bater com o esperado. Não usa
# token nenhum: são downloads públicos.
fetch_verified() {
    local url="$1" sha256="$2" dest="$3"
    rm -f "$dest" "$dest.part"
    curl -fL --retry 3 --proto '=https' --tlsv1.2 -o "$dest.part" "$url" \
        || die "falha ao baixar $url (se for 404, a versão fixada saiu do ar: veja o topo do script)"
    if ! printf '%s  %s\n' "$sha256" "$dest.part" | sha256sum --check --status; then
        die "SHA-256 inesperado para $url
       esperado: $sha256
       recebido: $(sha256sum "$dest.part" | cut -d' ' -f1)
       O arquivo foi alterado na origem. Não use este build; confira a release antes de atualizar o hash."
    fi
    mv "$dest.part" "$dest"
}

rm -rf "$WORK"
mkdir -p "$WORK" "$DIST"
cd "$WORK"

step "1/8 Python $PYTHON_VERSION portátil (python-appimage, manylinux_2_28)"
if [[ -n "${BASE_APPIMAGE:-}" ]]; then
    cp "$BASE_APPIMAGE" python.AppImage
else
    fetch_verified "$PYTHON_APPIMAGE_URL" "$PYTHON_APPIMAGE_SHA256" python.AppImage
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
    git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$PORTAUDIO_TAG" \
        "$PORTAUDIO_REPO" portaudio
    got="$(git -C portaudio rev-parse HEAD)"
    [[ "$got" == "$PORTAUDIO_COMMIT" ]] \
        || die "a tag $PORTAUDIO_TAG da PortAudio aponta para $got, e não para o commit fixado $PORTAUDIO_COMMIT"
    (
        cd portaudio
        # Só ALSA: no Linux atual o PipeWire/PulseAudio atende pela ALSA.
        ./configure --quiet --disable-static --with-alsa --without-jack --without-oss
        make -j"$(nproc)" >/dev/null
    )
    cp portaudio/lib/.libs/libportaudio.so.2.0.0 "$APP/lib/libportaudio.so.2"
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

step "6/8 Empacotamento (runtime + squashfs)"
# Um AppImage (tipo 2) é o runtime seguido de um sistema de arquivos squashfs
# com o AppDir. Isto faz o mesmo que o appimagetool, com o mksquashfs da
# própria distribuição: mesmas opções (zstd, blocos de 128K, arquivos como
# root, data zerada) e o squashfs começando logo após o runtime. O
# appimagetool só acrescentaria dados opcionais (atualização automática e
# assinatura GPG), que este projeto não usa.
command -v mksquashfs >/dev/null || die "mksquashfs não encontrado (instale squashfs-tools)"
[[ -x "$APPDIR/AppRun" && -e "$APPDIR/.DirIcon" && -f "$APPDIR/uninstrumephy.desktop" ]] \
    || die "AppDir incompleto: precisa de AppRun, .DirIcon e uninstrumephy.desktop"
if command -v desktop-file-validate >/dev/null; then
    desktop-file-validate "$APPDIR/uninstrumephy.desktop" || die "uninstrumephy.desktop inválido"
fi
RUNTIME="${RUNTIME_FILE:-}"
if [[ -z "$RUNTIME" ]]; then
    RUNTIME="$WORK/runtime-$ARCH"
    fetch_verified "$RUNTIME_URL" "$RUNTIME_SHA256" "$RUNTIME"
fi
# Assinatura do formato: "AI" + versão 2 no byte 8 (especificação do AppImage).
[[ "$(od -An -tx1 -j8 -N3 "$RUNTIME" | tr -d ' \n')" == "414902" ]] \
    || die "o runtime ($RUNTIME) não é um runtime de AppImage tipo 2"
runtime_size="$(stat -c %s "$RUNTIME")"
rm -f "$OUTPUT"
mksquashfs "$APPDIR" "$OUTPUT" -offset "$runtime_size" -comp zstd -b 128K \
    -root-owned -noappend -mkfs-time 0 -quiet -no-progress
dd if="$RUNTIME" of="$OUTPUT" conv=notrunc status=none   # grava o runtime no início
chmod 755 "$OUTPUT"

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
