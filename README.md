Interface gráfica inteligente para **Tone Matching** (casamento de timbres de guitarra) automatizado. O software utiliza Inteligência Artificial para separar os instrumentos de uma música de referência e Processamento Digital de Sinais (DSP) para extrair os parâmetros físicos ideais para emulação em hardware (como placas ESP32).

---

## Funcionalidades principais

* **Carregamento de Mídia:** Extração automática de metadados e capa do álbum.
* **Reprodutor de Áudio Independente:** Dois motores de reprodução na memória (música original vs. faixas isoladas) com sliders de tempo (*seek*) e volume independentes.
* **Separação de Faixas por IA:** Integração nativa do modelo **Demucs v4 (htdemucs_6s)** com suporte a aceleração por GPU (NVIDIA CUDA).
* **Análise de Sinais (MIR):** Extração matemática via **Librosa** da curva de equalização ideal (Bass, Mid, Treble) e do limiar do Noise Gate.
* **Escuta da pedaleira em tempo real:** a captura UAC mono processada da Placa A pode ser encaminhada, sem salvar primeiro em disco, para fones ou caixas selecionados no diálogo de gravação.
* **Controle CDC da Placa A:** o envio de parâmetros usa o protocolo v2 do firmware (COBS, CRC-8, sequência e confirmação), incluindo os efeitos novos. O simulador antigo que enviava um bloco COBS de 140 bytes não é usado em hardware.

## Escutar a pedaleira no computador

1. Conecte a USB nativa da **Placa A** e aguarde o dispositivo composto aparecer. A Placa A anuncia uma entrada UAC de 44,1 kHz, mono, 24 bits em slot de 32 bits, contendo o sinal **depois do DSP**.
2. Abra **Gravação Direta — ESP32-S3 / Microfone** pelo botão de gravação da janela principal.
3. Em **Entrada UAC**, selecione `ESP32-S3 Processed Audio` (ou o nome equivalente exibido pelo sistema). Em **Saída para escutar**, selecione fones/caixas do computador.
4. Clique em **Monitorar ao vivo**. O aplicativo abre um fluxo duplex do PortAudio a 44,1 kHz e copia o canal mono da pedaleira para a saída selecionada. O medidor mostra o pico recebido.
5. Para encerrar, clique em **Parar monitor**. A gravação em WAV continua disponível separadamente pelo botão **Iniciar Gravação**. O monitor usa o menor bloco nativo do backend (`blocksize=0`) e exibe a latência de entrada/saída reportada pelo PortAudio.

O firmware atual não implementa reprodução de áudio do computador para a pedaleira: a interface USB é captura UAC + CDC de controle. O monitoramento acima é a reprodução local no computador e não altera o sinal enviado ao DAC. Se a saída escolhida não aceitar 44,1 kHz mono, o diálogo informa o erro; selecione outra saída ou ajuste o dispositivo no sistema operacional.

Para monitorar em uma DAW, fixe projeto, entrada e saída em 44,1 kHz, use
buffer de 64 ou 128 amostras e mantenha apenas um monitoramento ativo. Prefira
fone/caixa com fio; buffers do sistema, PipeWire/ALSA e a própria saída podem
ser maiores que os valores configurados na DAW. Avisos de `input/output
underflow/overflow` exibidos pelo PortAudio indicam que o host está perdendo
blocos; reduza o trabalho do computador ou aumente a DAW para 128 amostras.

O diálogo atualiza entradas e saídas automaticamente enquanto está parado e
seleciona a UAC da ESP32 quando ela é enumerada. Se a placa for conectada
depois da abertura, use **Atualizar** ou aguarde a próxima atualização. Uma
entrada genérica de 48 kHz não pode ser usada como substituta da UAC de 44,1
kHz; nesse caso o aplicativo identifica o dispositivo selecionado e orienta a
escolher `ESP32-S3 Processed Audio`.

Se aparecer `Device unavailable`, outra captura pode estar usando a interface
ALSA em modo exclusivo. Pare o gravador anterior (ou `arecord`), aguarde a
UAC liberar o dispositivo e inicie o monitor novamente.

### Controle da placa

Ao clicar em **Enviar para hardware**, a aba de hardware faz um `HELLO` CDC, confere taxa, canais e tamanho de estado e envia os campos individualmente com `SET_PARAM` absoluto. Cada quadro tem cabeçalho versão 2 (`version`, `type`, `sequence` little-endian), payload, CRC-8 polinômio `0x07`, codificação COBS e terminador `0x00`. A aplicação repete comandos sem resposta e o firmware deduplica a última mutação por sequência/CRC. O cab sim (efeito 8) só é enviado quando o `effect_mask` de `CAPS` anuncia `EFFECT_CAP_CAB_SIM`; assim o mesmo cliente funciona tanto com o perfil padrão (`ENABLE_CAB_SIM=0`) quanto com o ambiente `*-cab`.

### Presets de demonstração

O aplicativo já inclui quatro presets JSON em `presets/`, que aparecem na lista
da aba **Hardware**:

* **Clean Chorus** — compressor leve, modulação/chorus, equalização aberta e
  reverb curto para bases limpas;
* **Blues Drive** — overdrive moderado, médios destacados, delay curto e
  reverb discreto para fraseados;
* **Ambient Phaser** — phaser lento, modulação profunda, delay e reverb longos
  para sons ambientes;
* **Lo-Fi Tremolo** — bitcrusher, tremolo triangular e overdrive para um timbre
  degradado e rítmico.

Selecione um nome, clique em **Carregar preset** para preencher os controles e
em **Enviar para hardware** para publicar o estado na Placa A. Os arquivos são
editáveis e mantêm os valores exibidos pela interface; o firmware valida e
limita cada parâmetro antes de aplicá-lo.

O aplicativo exige o conjunto completo de dependências do `requirements.txt`. O
Demucs é obrigatório porque a separação de guitarra faz parte do fluxo
principal; sem Torch/Demucs o programa deve interromper a inicialização em vez
de ocultar essa funcionalidade. O monitor USB também requer `PyQt6`,
`sounddevice`, `soundfile`, `numpy` e `pyserial`.

Se o ambiente virtual já estiver em `../.venv`, a instalação mínima pode ser feita com:

```bash
uv pip install --python ../.venv/bin/python -r requirements.txt
uv run main_gui.py
```

`tinytag` é usado para ler metadados dos arquivos carregados. Librosa e
Matplotlib também fazem parte da aba de Tone Matching e são carregados durante
a inicialização.

---

## Como Instalar e Rodar

Atualmente o projeto só tem suporte oficial ao Linux e dentro de ambientes virtuais do Python 3.14 ou superior.

1. **Instale o Python 3.14+**
```bash
sudo apt update && sudo apt install python3-full # Ubuntu
```

```bash
sudo pacman -S python # Arch
```

```bash
sudo dnf install python # RHEL/Fedora
```

2. **Instale o FFmpeg**
```bash
sudo apt update && sudo apt install ffmpeg # Ubuntu
```

```bash
sudo pacman -S ffmpeg # Arch
```

```bash
sudo dnf swap ffmpeg-free ffmpeg --allowerasing # RHEL/Fedora, Precisa do RPM Fusion
```

3. **Clone o repositório:**
```bash
git clone https://github.com/broken-usb/uninstrumephy.git
cd uninstrumephy
```

4. **Crie e ative seu ambiente virtual (`venv`):**
```bash
python -m venv .venv
```
```bash
source .venv/bin/activate # Linux (Bash)
```

5. **Instale as dependências:**
```bash
pip install --upgrade pip
```
```bash
pip install -r requirements.txt
```

6. **Execute o aplicativo:**
```bash
python main_gui.py
```
