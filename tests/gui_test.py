#  jack_midi_looper/test/gui_test.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
"""
Run the gui with a test database (generated from included midi files).
"""
import os, sys, logging
from PyQt5.QtWidgets import QApplication
from appdirs import user_config_dir
from qt_extras import DevilBox
from jack import JackError
from jack_midi_looper.gui import MainWindow as LooperWindow


class LooperTestWindow(LooperWindow):
	"""
	Same as the main LooperWindow, but overrides the database to use a test db.
	"""

	def __init__(self):
		dbfile = os.path.join(user_config_dir(), 'ZenSoSo', 'looper-tests.db')
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
