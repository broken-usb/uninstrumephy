# Uninstrumephy

Interface gráfica em Python (Qt6) para **Tone Matching** automatizado: casamento de timbres de guitarra a partir de uma música de referência.

O software usa Inteligência Artificial para separar os instrumentos da faixa e Processamento Digital de Sinais (DSP) para extrair os parâmetros ideais de emulação em hardware (como placas ESP32).

> **Status:** projeto em desenvolvimento. Suporte oficial apenas ao **Linux**. O Windows funciona de forma **experimental** (veja [Windows (experimental)](#windows-experimental)).

## Sumário

- [Funcionalidades](#funcionalidades)
- [Requisitos](#requisitos)
- [AppImage (sem instalar o Python)](#appimage-sem-instalar-o-python)
- [Instalação](#instalação)
- [Windows (experimental)](#windows-experimental)
- [Uso](#uso)
- [Onde ficam os dados](#onde-ficam-os-dados)
- [Integração com o hardware (Placa A)](#integração-com-o-hardware-placa-a)
  - [Controle via CDC](#controle-via-cdc)
  - [Presets de demonstração](#presets-de-demonstração)
  - [Escutar a pedaleira no computador](#escutar-a-pedaleira-no-computador)
  - [Solução de problemas](#solução-de-problemas)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Testes](#testes)
- [Publicar uma versão (AppImage)](#publicar-uma-versão-appimage)
- [Créditos](#créditos)
- [Licença](#licença)

## Funcionalidades

- **Carregamento de mídia:** extração automática de metadados e capa do álbum.
- **Reprodutor de áudio independente:** dois motores de reprodução em memória (música original e faixas isoladas), cada um com controles próprios de tempo (*seek*) e volume.
- **Separação de faixas por IA:** integração nativa com o modelo **Demucs v4 (`htdemucs_6s`)**, com aceleração por GPU NVIDIA (CUDA).
- **Análise de sinais (MIR):** extração, via **Librosa**, da curva de equalização ideal (Bass, Mid, Treble), do brilho e da dinâmica, aplicados ao EQ, Overdrive e Compressor. O limiar do Noise Gate é calculado apenas como sugestão: o Gate nunca é alterado automaticamente.
- **Controle da Placa A via CDC:** envio de parâmetros pelo protocolo v2 do firmware (COBS, CRC-8, sequência e confirmação), para todos os efeitos suportados pelo firmware.
- **Escuta da pedaleira em tempo real:** o áudio mono processado capturado via UAC é encaminhado direto para fones ou caixas, sem passar pelo disco.

## Requisitos

- Linux x86_64 (suporte oficial) ou Windows 10/11 64 bits ([experimental](#windows-experimental))
- [uv](https://docs.astral.sh/uv/) 0.13.5 ou mais novo (ele instala o Python sozinho: mínimo 3.12, padrão 3.14)
- FFmpeg
- Dependências definidas em `pyproject.toml`, com as versões travadas em `uv.lock`

O Demucs (Torch) é obrigatório, pois a separação de guitarra faz parte do fluxo principal. Sem ele, o programa interrompe a inicialização em vez de ocultar a funcionalidade.

Principais bibliotecas: `PyQt6`, `sounddevice`, `soundfile`, `numpy`, `pyserial`, `tinytag` (metadados), `librosa` e `matplotlib` (aba de Tone Matching).

## AppImage (sem instalar o Python)

Cada versão publicada em [Releases](https://github.com/broken-usb/uninstrumephy/releases) traz um arquivo `Uninstrumephy-<versão>-x86_64.AppImage` com tudo incluído (Python, Demucs, PyTorch e Qt):

```bash
chmod +x Uninstrumephy-*-x86_64.AppImage
./Uninstrumephy-*-x86_64.AppImage
```

O único requisito externo é o **FFmpeg** (veja a tabela em [Instalação](#instalação)), usado pelo Demucs para ler as músicas. O AppImage também usa a biblioteca do PulseAudio (`libpulse`), que já vem instalada em qualquer desktop com som (PipeWire ou PulseAudio). Na primeira separação, o modelo do Demucs é baixado da internet uma única vez.

O AppImage usa o PyTorch **só para CPU**, porque a versão com CUDA ultrapassaria o limite de 2 GB por arquivo das releases do GitHub. Para separar faixas pela GPU (NVIDIA), instale a partir do código-fonte, como abaixo.

## Instalação

O projeto usa o [uv](https://docs.astral.sh/uv/) para instalar o Python e as dependências. Não é preciso instalar o Python antes nem criar ou ativar um ambiente virtual: o uv faz isso sozinho.

1. **Instale o uv e o FFmpeg**

   Prefira os pacotes da sua distribuição: eles são atualizados junto com o resto do sistema.

   | Distribuição | uv | FFmpeg |
   | --- | --- | --- |
   | Arch | `sudo pacman -S uv` | `sudo pacman -S ffmpeg` |
   | Fedora 43 ou mais novo | `sudo dnf install uv` | `sudo dnf swap ffmpeg-free ffmpeg --allowerasing` (requer RPM Fusion) |
   | Ubuntu/Debian | instalador oficial (veja abaixo) | `sudo apt install ffmpeg` |
   | Outras distribuições | pacote `uv` da distribuição, se for 0.13.5 ou mais novo; senão, o instalador oficial | pacote `ffmpeg` da distribuição |

   O projeto exige o **uv 0.13.5 ou mais novo**. Confira com `uv --version` depois de instalar. Se a versão da distribuição for mais antiga (o `uv sync` avisa: *Required uv version `>=0.13.5` does not match*), ou se ela não tiver o pacote, como o Ubuntu e o Debian, use o instalador oficial:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   > O uv instalado pelo gerenciador de pacotes é atualizado por ele (`sudo dnf upgrade`, `sudo pacman -Syu`...). O comando `uv self update` só funciona no uv do instalador oficial.

   No Windows (experimental), use o `winget`: `winget install --id=astral-sh.uv -e` e `winget install Gyan.FFmpeg`. Veja [Windows (experimental)](#windows-experimental).

2. **Clone o repositório**

   ```bash
   git clone https://github.com/broken-usb/uninstrumephy.git
   cd uninstrumephy
   ```

3. **Instale as dependências**

   ```bash
   uv sync
   ```

   Isso cria o ambiente em `.venv` (baixando o Python 3.14, se preciso) e instala exatamente as versões do `uv.lock`. No Linux, o PyTorch vem com suporte a GPU NVIDIA (CUDA), o que soma cerca de 3 GB. Sem GPU NVIDIA, dá para instalar só a versão para CPU, bem menor:

   ```bash
   uv venv
   bash packaging/install_cpu_deps.sh .venv/bin/python
   ```

   Nesse caso, rode os comandos com `uv run --no-sync` (ex.: `uv run --no-sync main.py`). Sem o `--no-sync`, o `uv run` sincroniza o ambiente com o `uv.lock` e reinstalaria o PyTorch com CUDA.

## Windows (experimental)

O Windows 10/11 (64 bits) pode rodar o programa a partir do código-fonte, mas o suporte é **experimental**: o desenvolvimento e os testes com a Placa A são feitos no Linux, que é a única plataforma com suporte oficial. Problemas no Windows podem ser relatados em [Issues](https://github.com/broken-usb/uninstrumephy/issues), mas não têm garantia de correção.

**Diferenças em relação ao Linux**

- **Áudio:** o programa usa o WASAPI, o sistema de áudio do Windows. Cada dispositivo aparece uma vez só, e o Windows converte a taxa de amostragem automaticamente quando os fones estão em 48 kHz.
- **Pastas:** rodando de uma pasta sem permissão de escrita (ex.: `C:\Program Files`), os dados vão para `%LOCALAPPDATA%\uninstrumephy`.
- **Porta serial:** a Placa A aparece como `COM3`, `COM4`... e é encontrada automaticamente.
- **Testes:** o CI também roda os testes automáticos no Windows, mas sem placa de som nem a Placa A conectada.

**Instalação**

1. No Prompt de Comando ou no PowerShell:

   ```bat
   winget install --id=astral-sh.uv -e
   winget install Gyan.FFmpeg
   ```

2. Feche e abra o terminal, para que `uv` e `ffmpeg` sejam encontrados.
3. Siga os passos 2 e 3 da [Instalação](#instalação) (clonar e `uv sync`) e abra com `uv run main.py`. No Windows, o PyTorch instalado pelo `uv sync` já é a versão para CPU.

**Limitações conhecidas**

- Não há AppImage nem instalador para Windows: só a execução pelo código-fonte.
- O áudio em tempo real com a Placa A (monitor ao vivo e reconexão após uma alteração via CDC) não foi validado em hardware no Windows.
- Aberto sem console (`pythonw`), cada separação pode mostrar rapidamente janelas pretas do FFmpeg. Abrindo por `uv run main.py` num terminal, isso não acontece.

## Uso

```bash
uv run main.py
```

Para conferir se tudo está funcionando (PyTorch, Demucs, certificados HTTPS, análise, áudio, interface e pastas) sem abrir a janela:

```bash
./Uninstrumephy-*-x86_64.AppImage --self-test   # pelo AppImage
uv run main.py --self-test                      # pelo código-fonte
```

Para adicionar ou atualizar uma dependência, use `uv add <pacote>` ou `uv lock --upgrade-package <pacote>` e inclua o `uv.lock` atualizado no commit.

## Onde ficam os dados

| Executando a partir de | Logs, gravações e faixas separadas | Presets |
| --- | --- | --- |
| Código-fonte | `output/` na pasta do projeto | `presets/` na pasta do projeto |
| AppImage | `~/.local/share/uninstrumephy/` | `~/.local/share/uninstrumephy/presets/` (criada na primeira execução com os presets de demonstração) |
| Pasta sem permissão de escrita (ex.: `C:\Program Files`) | Linux: `~/.local/share/uninstrumephy/`; Windows (experimental): `%LOCALAPPDATA%\uninstrumephy\` | `presets\` dentro dessa pasta (criada com os presets de demonstração) |

A variável de ambiente `UNINSTRUMEPHY_DATA_DIR` substitui essa pasta em todos os casos. O log da sessão atual fica em `logs/latest-log.txt`, e o da anterior em `logs/previous-log.txt`.

## Integração com o hardware (Placa A)

Esta seção só é necessária se você usa a Placa A (ESP32-S3) conectada pela USB nativa.

### Controle via CDC

Ao clicar em **Enviar para hardware**, a aba Hardware:

1. faz um `HELLO` CDC e confere taxa, canais e tamanho de estado;
2. envia cada campo individualmente com `SET_PARAM` absoluto.

Cada quadro segue o formato abaixo:

| Etapa | Descrição |
| --- | --- |
| Cabeçalho (versão 2) | `version`, `type` e `sequence` (little-endian) |
| Payload | Dados do comando |
| Integridade | CRC-8, polinômio `0x07` |
| Codificação | COBS, com terminador `0x00` |

A aplicação reenvia comandos sem resposta, e o firmware deduplica a última mutação por sequência/CRC.

O *cab sim* (efeito 8) só é enviado quando o `effect_mask` de `CAPS` anuncia `EFFECT_CAP_CAB_SIM`. Assim, o mesmo cliente funciona tanto com o perfil padrão (`ENABLE_CAB_SIM=0`) quanto com o ambiente `*-cab`.
### Presets de demonstração

O diretório `presets/` traz quatro presets JSON, listados na aba **Hardware**:

| Preset | Descrição |
| --- | --- |
| **Clean Chorus** | Compressor leve, chorus, equalização aberta e reverb curto, para bases limpas |
| **Blues Drive** | Overdrive moderado, médios destacados, delay curto e reverb discreto, para fraseados |
| **Ambient Phaser** | Phaser lento, modulação profunda, delay e reverb longos, para sons ambientes |
| **Lo-Fi Tremolo** | Bitcrusher, tremolo triangular e overdrive, para um timbre degradado e rítmico |

Para usar: selecione um preset, clique em **Carregar preset** para preencher os controles e em **Enviar para hardware** para aplicar o estado na Placa A.

Os arquivos são editáveis e mantêm os valores exibidos pela interface. O firmware valida e limita cada parâmetro antes de aplicá-lo.

### Escutar a pedaleira no computador

A Placa A anuncia uma entrada UAC de **44,1 kHz, mono, 24 bits em slot de 32 bits**, com o sinal **depois do DSP**.

1. Conecte a USB nativa da Placa A e aguarde o dispositivo composto aparecer.
2. Abra **Gravação Direta — ESP32-S3 / Microfone** pelo botão de gravação da janela principal.
3. Em **Entrada UAC**, selecione `ESP32-S3 Processed Audio` (ou o nome equivalente exibido pelo sistema). Em **Saída para escutar**, selecione fones ou caixas do computador.
4. Clique em **Monitorar ao vivo**. O aplicativo abre um fluxo duplex do PortAudio a 44,1 kHz e copia o canal mono da pedaleira para a saída escolhida. O medidor mostra o pico recebido.
5. Para encerrar, clique em **Parar monitor**.

Detalhes importantes:

- A gravação em WAV é independente e continua disponível em **Iniciar Gravação**.
- O monitor usa o menor bloco nativo do backend (`blocksize=0`) e exibe a latência de entrada/saída reportada pelo PortAudio.
- O firmware atual **não** reproduz áudio do computador na pedaleira: a interface USB é captura UAC + CDC de controle. O monitoramento é apenas reprodução local e não altera o sinal enviado ao DAC.
- O diálogo atualiza entradas e saídas automaticamente enquanto está parado e seleciona a UAC da ESP32 quando ela é enumerada. Se a placa for conectada depois, use **Atualizar**.

**Monitorando em uma DAW:** fixe projeto, entrada e saída em 44,1 kHz, use buffer de 64 ou 128 amostras e mantenha apenas um monitoramento ativo. Prefira fones ou caixas com fio: os buffers do sistema (PipeWire/ALSA) e da própria saída podem ser maiores que os configurados na DAW.

### Solução de problemas

| Sintoma | O que fazer |
| --- | --- |
| Saída não aceita 44,1 kHz mono | O diálogo informa o erro. Escolha outra saída ou ajuste o dispositivo no sistema operacional. |
| Entrada genérica de 48 kHz selecionada | Ela não substitui a UAC de 44,1 kHz. Escolha `ESP32-S3 Processed Audio`. |
| `Device unavailable` | Outra captura pode estar usando a interface em modo exclusivo. Linux: pare o gravador anterior (ou `arecord`). Windows (experimental): feche programas como Discord ou OBS e, em *Configurações de som → Mais configurações de som → (dispositivo) → Propriedades → Avançado*, desmarque "Permitir que aplicativos tenham controle exclusivo". Depois aguarde a UAC liberar o dispositivo e inicie o monitor novamente. |
| `PortAudio library not found` | Linux: instale a PortAudio (Fedora: `sudo dnf install portaudio`; Ubuntu/Debian: `sudo apt install libportaudio2`); o AppImage já traz uma cópia de reserva. Windows (experimental): a PortAudio vem com o `sounddevice`; reinstale com `uv sync --reinstall-package sounddevice`. |
| Dispositivos no Windows (experimental) | O programa usa o sistema de áudio WASAPI, então cada dispositivo aparece uma vez só. Se a placa foi conectada com o programa aberto e não aparece, use **Atualizar**. |
| Avisos de `input/output underflow/overflow` | O host está perdendo blocos. Reduza a carga do computador ou aumente o buffer da DAW para 128 amostras. |

## Estrutura do repositório

```text
.
├── .github/workflows/ # CI (testes no Linux e no Windows) e release (AppImage)
├── core/              # Lógica principal (separação, análise, protocolo)
├── gui/               # Interface Qt6 (.ui do Qt Designer + código)
├── packaging/         # Montagem do AppImage e instalação só para CPU
├── presets/           # Presets JSON de demonstração
├── tests/             # Testes (pytest)
├── .flake8            # Configuração do lint (ignora .venv/ e pastas geradas)
├── .python-version    # Versão padrão do Python usada pelo uv
├── main.py            # Ponto de entrada
├── pyproject.toml     # Dependências do projeto
└── uv.lock            # Versões travadas das dependências
```

A interface é definida pelos arquivos `.ui` em `gui/`, carregados em tempo de execução por `gui/ui_loader.py`. Para mudar o layout, edite-os no Qt Designer; não é preciso gerar código com `pyuic6`.

## Testes

```bash
uv run pytest
uv run flake8 . --select=E9,F63,F7,F82   # erros de lint que bloqueiam o CI
```

Os testes não precisam da pedaleira nem de placa de som (ambas são simuladas) e gravam seus dados numa pasta temporária, nunca em `output/`.

## Publicar uma versão (AppImage)

O workflow [`release.yml`](.github/workflows/release.yml) roda os testes, monta o AppImage, testa o AppImage pronto (`--self-test`) e só então cria a release com o arquivo anexado. Se qualquer etapa falhar, nada é publicado. Há duas formas de iniciá-lo:

- **Pelo GitHub:** aba **Actions** > **Release (AppImage)** > **Run workflow**, informe a versão (ex.: `1.0.0`) e, se quiser, marque *pré-lançamento*. A tag `v1.0.0` é criada no commit escolhido.
- **Por tag:**

  ```bash
  git tag v1.0.0
  git push origin v1.0.0
  ```

O build demora alguns minutos (baixar e empacotar o PyTorch é a parte mais lenta). O AppImage também fica disponível por 14 dias nos artefatos da execução, mesmo que a publicação falhe. A release traz um `SHA256SUMS.txt` para conferir o download (`sha256sum -c SHA256SUMS.txt`).

O empacotamento usa o `mksquashfs` da própria distribuição, sem ferramentas de empacotamento de terceiros. As peças baixadas de fora (Python portátil, runtime do AppImage e PortAudio) estão fixadas em versões exatas e conferidas por SHA-256 ou pelo commit do Git: se uma delas mudar na origem, o build para em vez de publicar algo não conferido. Para atualizar uma versão, veja as instruções no topo de `packaging/build_appimage.sh`.

Para montar localmente (Linux x86_64, com o `uv`, `gcc`, `make`, `git`, `curl`, `squashfs-tools`, os cabeçalhos da ALSA e a `libxcb-cursor`; Fedora: `sudo dnf install gcc make git curl squashfs-tools alsa-lib-devel xcb-util-cursor`):

```bash
bash packaging/build_appimage.sh 1.0.0   # gera dist/Uninstrumephy-1.0.0-x86_64.AppImage
```

## Créditos

- **Ícone do aplicativo:** "Guitar bass head icon" by [Delapouite](https://delapouite.com) under [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/).

## Licença

Distribuído sob a licença **GPL-3.0**. Veja o arquivo [COPYING](COPYING).
