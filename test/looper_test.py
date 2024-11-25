#  jack_midi_looper/test/looper_test.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import sys, os, argparse, logging
from appdirs import user_config_dir
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QShortcut
from PyQt5.QtGui import QKeySequence
from qt_extras import DevilBox
from jack import JackError
from jack_midi_looper import Loops
from jack_midi_looper.looper_widget import LooperWidget


class LooperTestWindow(QMainWindow):

	def __init__(self, loops):
		super().__init__()
		self.setWindowTitle('Looper')
		self.looper_widget = LooperWidget(self, loops)
		self.setCentralWidget(self.looper_widget)
		self.looper_widget.layout().setContentsMargins(8,8,8,8)
		self.quit_shortcut = QShortcut(QKeySequence('Ctrl+Q'), self)
		self.quit_shortcut.activated.connect(self.close)

	def closeEvent(self, event):
		self.looper_widget.looper.stop()
		event.accept()

	def system_signal(self, sig, frame):
		logging.debug("Caught signal - shutting down")
		self.close()


if __name__ == "__main__":

	p = argparse.ArgumentParser()
	p.epilog = """
	Write your help text!
	"""
	p.add_argument('Filename', type=str, nargs='*', help='SFZ file[s] to include at startup')
	p.add_argument("--verbose", "-v", action="store_true", help="Show more detailed debug information")
	options = p.parse_args()

	log_level = logging.DEBUG if options.verbose else logging.ERROR
	log_format = "[%(filename)24s:%(lineno)4d] %(levelname)-8s %(message)s"
	logging.basicConfig(level = log_level, format = log_format)

	try:
		del os.environ['SESSION_MANAGER']
	except KeyError:
		pass
	app = QApplication([])

	try:
		dbpath = os.path.join(user_config_dir(), 'ZenSoSo', 'midibanks.db')
		try:
			os.mkdir(dbpath)
		except FileExistsError:
			pass
		main_window = LooperTestWindow(Loops(dbpath))
	except JackError:
		DevilBox('Could not connect to JACK server. Is it running?')
		sys.exit(1)
	main_window.show()
	sys.exit(app.exec())


#  end jack_midi_looper/test/looper_test.py
