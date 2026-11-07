# Uninstrumephy

Interface gráfica em Python (Qt6) para **Tone Matching** automatizado: casamento de timbres de guitarra a partir de uma música de referência.

O software usa Inteligência Artificial para separar os instrumentos da faixa e Processamento Digital de Sinais (DSP) para extrair os parâmetros ideais de emulação em hardware (como placas ESP32).

> **Status:** projeto em desenvolvimento. Suporte oficial apenas ao Linux.

## Sumário

- [Funcionalidades](#funcionalidades)
- [Requisitos](#requisitos)
- [AppImage (sem instalar o Python)](#appimage-sem-instalar-o-python)
- [Instalação](#instalação)
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
- **Análise de sinais (MIR):** extração, via **Librosa**, da curva de equalização ideal (Bass, Mid, Treble) e do limiar do Noise Gate.
- **Controle da Placa A via CDC:** envio de parâmetros pelo protocolo v2 do firmware (COBS, CRC-8, sequência e confirmação), incluindo os efeitos novos.
- **Escuta da pedaleira em tempo real:** o áudio mono processado capturado via UAC é encaminhado direto para fones ou caixas, sem passar pelo disco.

## Requisitos

- Linux
- Python **3.12 ou superior** (recomendado: **3.14+**)
- FFmpeg
- Conjunto completo de dependências do `requirements.txt`

O Demucs (Torch) é obrigatório, pois a separação de guitarra faz parte do fluxo principal. Sem ele, o programa interrompe a inicialização em vez de ocultar a funcionalidade.

Principais bibliotecas: `PyQt6`, `sounddevice`, `soundfile`, `numpy`, `pyserial`, `tinytag` (metadados), `librosa` e `matplotlib` (aba de Tone Matching).

## AppImage (sem instalar o Python)

Cada versão publicada em [Releases](https://github.com/broken-usb/uninstrumephy/releases) traz um arquivo `Uninstrumephy-<versão>-x86_64.AppImage` com tudo incluído (Python, Demucs, PyTorch e Qt):

```bash
chmod +x Uninstrumephy-*-x86_64.AppImage
./Uninstrumephy-*-x86_64.AppImage
```

O único requisito externo é o **FFmpeg** (veja a tabela em [Instalação](#instalação)), usado pelo Demucs para ler as músicas. Na primeira separação, o modelo do Demucs é baixado da internet uma única vez.

O AppImage usa o PyTorch **só para CPU**, porque a versão com CUDA ultrapassaria o limite de 2 GB por arquivo das releases do GitHub. Para separar faixas pela GPU (NVIDIA), instale a partir do código-fonte, como abaixo.

## Instalação

1. **Instale o Python (mínimo 3.12, recomendado 3.14+) e o FFmpeg**

   | Distribuição | Python | FFmpeg |
   | --- | --- | --- |
   | Ubuntu/Debian | `sudo apt update && sudo apt install python3-full` | `sudo apt install ffmpeg` |
   | Arch | `sudo pacman -S python` | `sudo pacman -S ffmpeg` |
   | RHEL/Fedora | `sudo dnf install python` | `sudo dnf swap ffmpeg-free ffmpeg --allowerasing` (requer RPM Fusion) |

   > Verifique a versão com `python3 --version`. A versão mínima é a 3.12, mas recomendamos a 3.14 ou superior. Se o repositório da sua distribuição não oferece a versão desejada, instale-a por outro meio (por exemplo, `uv python install 3.14`).

2. **Clone o repositório**

   ```bash
   git clone https://github.com/broken-usb/uninstrumephy.git
   cd uninstrumephy
   ```

3. **Crie e ative o ambiente virtual**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

4. **Instale as dependências**

   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

   Alternativa com [uv](https://docs.astral.sh/uv/):

   ```bash
   uv venv --python 3.14
   uv pip install -r requirements.txt
   ```

   Se você já tem um ambiente virtual em `../.venv`, é possível reaproveitá-lo:

   ```bash
   uv pip install --python ../.venv/bin/python -r requirements.txt
   ```

## Uso

Com o ambiente virtual ativo:

```bash
python main.py
```

Com `uv`:

```bash
uv run main.py
```

Para conferir se tudo está funcionando (PyTorch, Demucs, certificados HTTPS, análise, áudio, interface e pastas) sem abrir a janela:

```bash
./Uninstrumephy-*-x86_64.AppImage --self-test   # pelo AppImage
python main.py --self-test                      # pelo código-fonte
```

## Onde ficam os dados

| Executando a partir de | Logs, gravações e faixas separadas | Presets |
| --- | --- | --- |
| Código-fonte | `output/` na pasta do projeto | `presets/` na pasta do projeto |
| AppImage | `~/.local/share/uninstrumephy/` | `~/.local/share/uninstrumephy/presets/` (criada na primeira execução com os presets de demonstração) |

A variável de ambiente `UNINSTRUMEPHY_DATA_DIR` substitui essa pasta em ambos os casos. O log da sessão atual fica em `logs/latest-log.txt`, e o da anterior em `logs/previous-log.txt`.

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

> O simulador antigo, que enviava um bloco COBS de 140 bytes, não é usado em hardware.

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
| `Device unavailable` | Outra captura pode estar usando a interface ALSA em modo exclusivo. Pare o gravador anterior (ou `arecord`), aguarde a UAC liberar o dispositivo e inicie o monitor novamente. |
| `PortAudio library not found` | Instale a PortAudio (Fedora: `sudo dnf install portaudio`; Ubuntu/Debian: `sudo apt install libportaudio2`). O AppImage já traz uma cópia de reserva. |
| Avisos de `input/output underflow/overflow` | O host está perdendo blocos. Reduza a carga do computador ou aumente o buffer da DAW para 128 amostras. |

## Estrutura do repositório

```text
.
├── .github/workflows/ # CI (testes) e release (AppImage)
├── core/              # Lógica principal (separação, análise, protocolo)
├── gui/               # Interface Qt6 (.ui do Qt Designer + código)
├── packaging/         # Montagem do AppImage
├── presets/           # Presets JSON de demonstração
├── tests/             # Testes (pytest)
├── main.py            # Ponto de entrada
└── requirements.txt   # Dependências
```

A interface é definida pelos arquivos `.ui` em `gui/`, carregados em tempo de execução por `gui/ui_loader.py`. Para mudar o layout, edite-os no Qt Designer; não é preciso gerar código com `pyuic6`.

## Testes

```bash
pip install pytest
QT_QPA_PLATFORM=offscreen python -m pytest
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

O build demora alguns minutos (baixar e empacotar o PyTorch é a parte mais lenta). O AppImage também fica disponível por 14 dias nos artefatos da execução, mesmo que a publicação falhe.

Para montar localmente (Linux x86_64, com `gcc`, `make`, `curl`, os cabeçalhos da ALSA e a `libxcb-cursor`; Fedora: `sudo dnf install gcc make alsa-lib-devel xcb-util-cursor curl`):

```bash
bash packaging/build_appimage.sh 1.0.0   # gera dist/Uninstrumephy-1.0.0-x86_64.AppImage
```

## Créditos

- **Ícone do aplicativo:** "Guitar bass head icon" by [Delapouite](https://delapouite.com) under [CC BY 3.0](http://creativecommons.org/licenses/by/3.0/).

## Licença

Distribuído sob a licença **GPL-3.0**. Veja o arquivo [COPYING](COPYING).