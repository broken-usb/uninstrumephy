Interface gráfica inteligente para **Tone Matching** (casamento de timbres de guitarra) automatizado. O software utiliza Inteligência Artificial para separar os instrumentos de uma música de referência e Processamento Digital de Sinais (DSP) para extrair os parâmetros físicos ideais para emulação em hardware (como placas ESP32).

---

## Funcionalidades principais

* **Carregamento de Mídia:** Extração automática de metadados e capa do álbum.
* **Reprodutor de Áudio Independente:** Dois motores de reprodução na memória (música original vs. faixas isoladas) com sliders de tempo (*seek*) e volume independentes.
* **Separação de Faixas por IA:** Integração nativa do modelo **Demucs v4 (htdemucs_6s)** com suporte a aceleração por GPU (NVIDIA CUDA).
* **Análise de Sinais (MIR):** Extração matemática via **Librosa** da curva de equalização ideal (Bass, Mid, Treble) e do limiar do Noise Gate.

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
