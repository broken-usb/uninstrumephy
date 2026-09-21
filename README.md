
Interface gráfica inteligente para **Tone Matching** (casamento de timbres de guitarra) automatizado. O software utiliza Inteligência Artificial para separar os instrumentos de uma música de referência e Processamento Digital de Sinais (DSP) para extrair os parâmetros físicos ideais para emulação em hardware (como placas ESP32)

---

## Funcionalidades principais

* **Carregamento de Multimédia:** Extração automática de metadados e capa do álbum a partir de ficheiros de áudio locais (MP3, WAV, FLAC, OGG, AAC)[cite: 1].
* **Reprodutor de Áudio Independente:** Dois motores de reprodução em memória (áudio original vs. faixas isoladas) com barras deslizantes de procura (*seek*) e controlo de volume independentes[cite: 1].
* **Separação de Faixas por IA:** Integração nativa do modelo **Demucs v4 (htdemucs_6s)** com suporte para aceleração por GPU (NVIDIA CUDA) ou CPU[cite: 1].
* **Entrada Direta e Gravação:** Diálogo de captura de áudio em tempo real via microfone ou interface de som externa, permitindo direcionar o sinal gravado imediatamente para o Tone Matching e contornar a separação do Demucs.
* **Tone Matching Adaptativo (MIR/DSP):** Extração matemática via **Librosa** da curva de equalização ideal em 4 bandas (Low, Mid 1, Mid 2 e High) e cálculo automático do limiar do *Noise Gate*[cite: 1].
* **Comunicação com Hardware (ESP32-S3):** Transmissão serial do estado completo de parâmetros e blocos de efeitos (pacote estruturado de 140 bytes), com suporte integrado a modo de simulação (*Mock*).
* **Gestão de Registos (Logging):** Registo simultâneo na consola e em ficheiro de texto, com rotação automática de sessões (`output/logs/latest-log.txt` e `output/logs/previous-log.txt`).

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
git clone [https://github.com/broken-usb/uninstrumephy.git](https://github.com/broken-usb/uninstrumephy.git)
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