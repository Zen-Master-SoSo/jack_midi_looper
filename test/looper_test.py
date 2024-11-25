#  jack_midi_looper/looper.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import logging
from jack import JackError
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QVBoxLayout


class LooperTestWindow(QMainWindow):

	def __init__(self):
		super().__init__()
		from jack_midi_looper.looper_widget import LooperWidget
		from PyQt5.QtWidgets import QShortcut
		from PyQt5.QtGui import QKeySequence
		self.setWindowTitle('Looper')
		self.looper_widget = LooperWidget(self)
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


class Pause:
	"""
	A context manager that remembers what state a Looper is in,
	stops it, lets you do work, and then restarts it if it had
	been running.
	"""

	def __init__(self, looper):
		self.looper = looper
		self.previous_state = looper.state

	def __enter__(self):
		self.looper.stop()

	def __exit__(self, *_):
		if self.previous_state == Looper.PLAYING:
			self.looper.play()



if __name__ == "__main__":
	import sys, os, argparse
	from PyQt5.QtWidgets import QApplication
	from qt_extras import DevilBox

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
		main_window = LooperTestWindow()
	except JackError:
		DevilBox('Could not connect to JACK server. Is it running?')
		sys.exit(1)
	main_window.show()
	sys.exit(app.exec())


#  end jack_midi_looper/gui.py
