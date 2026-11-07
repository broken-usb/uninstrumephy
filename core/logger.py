import sys
import logging
from pathlib import Path

from core import paths


def setup_logging(log_dir: str | Path | None = None) -> logging.Logger:
    """
    Configura o sistema de logging para gravar mensagens no console (stdout)
    e em arquivo de texto. Rotaciona 'latest-log.txt' para 'previous-log.txt' a cada execução.
    Sem log_dir, usa core.paths.logs_dir().
    """
    log_path = Path(log_dir if log_dir is not None else paths.logs_dir()).resolve()
    log_path.mkdir(parents=True, exist_ok=True)

    latest_log = log_path / "latest-log.txt"
    previous_log = log_path / "previous-log.txt"

    # Rotaciona a sessão anterior se o arquivo já existir
    if latest_log.exists():
        try:
            if previous_log.exists():
                previous_log.unlink()
            latest_log.rename(previous_log)
        except OSError as exc:
            print(f"[AVISO] Falha ao rotacionar logs anteriores: {exc}", file=sys.stderr)

    log_format = "%(asctime)s [%(levelname)s] %(name)s -> %(message)s"
    formatter = logging.Formatter(log_format)

    # Handler do Terminal (Console)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Handler do Arquivo (latest-log.txt com detalhes em nível DEBUG)
    file_handler = logging.FileHandler(latest_log, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Configuração do Logger Raiz para capturar chamadas de todos os módulos
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Limpa handlers anteriores para evitar mensagens duplicadas
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    return root_logger