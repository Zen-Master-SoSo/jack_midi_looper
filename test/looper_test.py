#  jack_midi_looper/test/looper_test.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import sys, logging
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QShortcut
from PyQt5.QtGui import QKeySequence
from qt_extras import DevilBox
from jack import JackError
from jack_midi_looper import Looper
from jack_midi_looper.looper_widget import LooperWidget
from jack_midi_looper.test import test_db


class LooperTestWindow(QMainWindow):

	def __init__(self):
		super().__init__()
		self.setWindowTitle('Looper')
		self.looper_widget = LooperWidget(self, test_db(), Looper())
		self.setCentralWidget(self.looper_widget)
		self.looper_widget.layout().setContentsMargins(8,8,8,8)
		self.quit_shortcut = QShortcut(QKeySequence('Ctrl+Q'), self)
		self.quit_shortcut.activated.connect(self.close)

	def closeEvent(self, event):
		self.looper_widget.looper.stop()
		event.accept()

	def system_signal(self, sig, frame):
		logging.debug('Caught signal - shutting down')
		self.close()


if __name__ == "__main__":
	log_level = logging.DEBUG
	log_format = "[%(filename)24s:%(lineno)4d] %(levelname)-8s %(message)s"
	logging.basicConfig(level = log_level, format = log_format)
	app = QApplication([])
	try:
		main_window = LooperTestWindow()
	except JackError:
		DevilBox('Could not connect to JACK server. Is it running?')
		sys.exit(1)
	main_window.show()
	sys.exit(app.exec())


#  end jack_midi_looper/test/looper_test.py
