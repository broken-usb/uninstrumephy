from PyQt6.QtWidgets import QDialog
from gui.ui_loader import load_ui_file

class DialogRecord(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        load_ui_file("dialog_record.ui", self)

        # Os componentes já estão instanciados conforme os nomes do .ui:
        # self.comboDevice, self.vuMeter, self.btnRecord, etc.
        self.btnRecord.clicked.connect(self._start_recording)
        self.btnStop.clicked.connect(self._stop_recording)
        self.btnSave.clicked.connect(self.accept)

    def _start_recording(self):
        # Integração com core.audio_recorder
        pass

    def _stop_recording(self):
        pass