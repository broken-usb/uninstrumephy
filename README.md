Interface gráfica inteligente para **Tone Matching** (casamento de timbres de guitarra) automatizado. O software utiliza Inteligência Artificial para separar os instrumentos de uma música de referência e Processamento Digital de Sinais (DSP) para extrair os parâmetros físicos ideais para emulação em hardware (como placas ESP32).

---

## Funcionalidades principais

* **Carregamento de Mídia:** Extração automática de metadados e capa do álbum.
* **Reprodutor de Áudio Independente:** Dois motores de reprodução na memória (música original vs. faixas isoladas) com sliders de tempo (*seek*) e volume independentes.
* **Separação de Faixas por IA:** Integração nativa do modelo **Demucs v4 (htdemucs_6s)** com suporte a aceleração por GPU (NVIDIA CUDA).
* **Análise de Sinais (MIR):** Extração matemática via **Librosa** da curva de equalização ideal (Bass, Mid, Treble) e do limiar do Noise Gate.

---

## Como Instalar e Rodar

1. **Clone o repositório:**
```bash
git clone https://github.com/broken-usb/uninstrumephy.git
cd uninstrumephy

```

2. **Crie e ative seu ambiente virtual (`venv`):**
```bash
python -m venv .venv
source .venv/bin/activate
```

3. **Instale as dependências:**
```bash
pip install --upgrade pip
```
```bash
pip install -r requirements.txt # Linux
```
```ps1
pip install -r requirements-win.txt # Windows
```

4. **Execute o aplicativo:**
```bash
python main_gui.py
```
