#  jack_midi_looper/test/gui_test.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import sys, logging
from PyQt5.QtWidgets import QApplication
from qt_extras import DevilBox
from jack import JackError
from jack_midi_looper.gui import MainWindow as LooperWindow
from jack_midi_looper.test import test_dbfile


class LooperTestWindow(LooperWindow):

	def __init__(self):
		dbfile = test_dbfile()
		super().__init__(dbfile)
		if len(self.loops_db.loop_ids()) == 0:
			self.loops_db.import_dirs(os.path.join(os.path.dirname(__file__), 'drum-loops'))


def main():
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


if __name__ == "__main__":
	sys.exit(main())


#  end jack_midi_looper/test/gui_test.py
