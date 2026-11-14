#!/usr/bin/env bash
# Instala as dependências travadas no uv.lock com o PyTorch só para CPU.
#
# O `uv sync` instala o PyTorch do PyPI, que no Linux é a versão com CUDA
# (cerca de 3 GB de bibliotecas da NVIDIA): bom para separar faixas pela GPU,
# mas grande demais para o CI e para o AppImage (limite de 2 GB do GitHub).
# Aqui são instaladas as mesmas versões do uv.lock, trocando só o PyTorch pela
# versão para CPU (mesma versão, do índice oficial do PyTorch) e deixando de
# fora os pacotes que só existem por causa do CUDA.
#
# Sem conferência de hash: o PyTorch para CPU é outro arquivo, com hash
# diferente do registrado no lock. As versões continuam travadas pelo lock.
#
# Uso: bash packaging/install_cpu_deps.sh <python> [opções do uv export]
#   bash packaging/install_cpu_deps.sh .venv/bin/python             # com pytest e flake8
#   bash packaging/install_cpu_deps.sh /caminho/do/python --no-dev  # só o programa
set -euo pipefail

[[ $# -ge 1 ]] || { echo "Uso: $0 <python> [opções do uv export]" >&2; exit 2; }
PYTHON="$1"; shift
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v uv >/dev/null || { echo "ERRO: uv não encontrado (veja https://docs.astral.sh/uv/)" >&2; exit 1; }

REQS="$(mktemp)"
trap 'rm -f "$REQS"' EXIT

# --locked: para se o uv.lock não corresponder mais ao pyproject.toml.
uv export --project "$ROOT" --locked --format requirements.txt \
    --no-emit-project --no-hashes --no-header --no-annotate "$@" \
    | grep -Ev '^(nvidia-|cuda-|triton)' > "$REQS"
grep -q '^torch==' "$REQS" || { echo "ERRO: o torch não está na exportação do uv.lock" >&2; exit 1; }

uv pip install --python "$PYTHON" --torch-backend cpu -r "$REQS"
