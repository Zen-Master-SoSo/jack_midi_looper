#  jack_midi_looper/gui.py
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
A Qt5 -based GUI.
"""
import os, sys, argparse, logging
from functools import partial
from appdirs import user_config_dir
from jack import JackError
from PyQt5.QtWidgets import QApplication, QMainWindow, QShortcut, QFrame, QPushButton, QGridLayout
from PyQt5.QtCore import pyqtSlot, QTimer, QSize
from PyQt5.QtGui import QKeySequence, QIcon
from PyQt5 import uic
from qt_extras import ShutUpQT, SigBlock, DevilBox
from jack_midi_looper import Looper, LoopsDB


class MainWindow(QMainWindow):

	def __init__(self, dbfile = None):
		super().__init__()
		if dbfile is None:
			dbfile = os.path.join(user_config_dir(), 'ZenSoSo', 'looper-loops.db')
		self.loops_db = LoopsDB(dbfile)
		self.setWindowTitle(f'Looper ({dbfile})')
		self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), 'res', 'musecbox-icon.png')))
		self.looper_widget = LooperWidget(self, self.loops_db, Looper())
		self.setCentralWidget(self.looper_widget)
		self.looper_widget.layout().setContentsMargins(4,4,4,4)
		self.quit_shortcut = QShortcut(QKeySequence('Ctrl+Q'), self)
		self.quit_shortcut.activated.connect(self.close)

	def closeEvent(self, event):
		self.looper_widget.looper.stop()
		event.accept()

	def system_signal(self, *_):
		logging.debug('Caught signal - shutting down')
		self.close()


class LooperWidget(QFrame):
	"""
	A widget inheriting QFrame which can be embedded in your GUI application.
	"""

	columns = 6

	def __init__(self, parent, loops_db, looper):
		super().__init__(parent)
		self.loops_db = loops_db
		self.looper = looper
		my_dir = os.path.dirname(__file__)
		with ShutUpQT():
			uic.loadUi(os.path.join(my_dir, 'res', 'looper_widget.ui'), self)
		self.cmb_group.addItem('')
		self.cmb_group.addItems(self.loops_db.groups())
		self.cmb_group.currentTextChanged.connect(self.slot_group_changed)
		self.beat_spinner.valueChanged.connect(self.slot_bpm_changed)
		self.rb_layered.clicked.connect(self.slot_layered_clicked)
		self.rb_single.clicked.connect(self.slot_single_clicked)
		self.loops_layout = QGridLayout()
		self.loops_layout.setContentsMargins(0,0,0,0)
		self.loops_layout.setSpacing(2)
		self.frm_loops.setLayout(self.loops_layout)
		self.loops_font = self.lbl1.font()
		self.loops_font.setPointSize(8)
		self.update_timer = QTimer()
		self.update_timer.setInterval(int(1 / 8 * 1000))
		self.update_timer.timeout.connect(self.slot_timer_timeout)

	def toggle_play(self, state):
		if state:
			self.update_timer.start()
			self.looper.play()
		else:
			self.update_timer.stop()
			self.looper.stop()

	@pyqtSlot()
	def slot_timer_timeout(self):
		self.beat.display(int(self.looper.beat + 1.0))

	@pyqtSlot(str)
	def slot_group_changed(self, text):
		self.looper.clear()
		self.toggle_play(False)
		for button in self.frm_loops.findChildren(QPushButton):
			self.loops_layout.removeWidget(button)
			button.deleteLater()
		if text == '':
			return
		new_loops = self.loops_db.group_loops(text)
		if len(new_loops):
			self.looper.extend_loops(new_loops)
			rows = len(new_loops) // self.columns + 1
			ord_ = 0
			for loop in new_loops:
				button = LoopButton('{} ({}/4 - {} beats)'.format(
						loop.name, loop.beats_per_measure,
						loop.beats_per_measure * loop.measures),
					self.frm_loops)
				button.setFont(self.loops_font)
				button.setCheckable(True)
				button.loop_id = loop.loop_id
				button.toggled.connect(partial(self.loop_select, loop.loop_id))
				self.loops_layout.addWidget(button, ord_ % rows, int(ord_ / rows))
				ord_ += 1

	@pyqtSlot(int, bool)
	def loop_select(self, loop_id, state):
		self.looper.enable_loop(loop_id, state)
		buttons = self.frm_loops.findChildren(QPushButton)
		with SigBlock(*buttons):
			for button in buttons:
				button.setChecked(self.looper.loop(button.loop_id).active)
		self.toggle_play(self.looper.any_loop_active())

	@pyqtSlot(bool)
	def slot_layered_clicked(self, _):
		self.looper.loop_exclusive = True

	@pyqtSlot(bool)
	def slot_single_clicked(self, _):
		for button in self.frm_loops.findChildren(QPushButton):
			button.setChecked(False)
		self.looper.loop_exclusive = False

	@pyqtSlot(int)
	def slot_bpm_changed(self, bpm):
		self.looper.bpm = bpm

	def sizeHint(self):
		return QSize(490, 50)


class LoopButton(QPushButton):
	"""
	Inherited to facilitate styling with CSS
	"""



def main():

	p = argparse.ArgumentParser()
	p.epilog = """
	Write your help text!
	"""
	p.add_argument('Database', type=str, nargs='?', help='Loops database to load')
	p.add_argument("--log-file", "-l", type=str, help="Log to this file")
	p.add_argument("--verbose", "-v", action="store_true", help="Show more detailed debug information")
	options = p.parse_args()

	log_level = logging.DEBUG if options.verbose else logging.ERROR
	log_format = "[%(filename)24s:%(lineno)4d] %(levelname)-8s %(message)s"
	if options.log_file:
		logging.basicConfig(
			filename = options.log_file,
			filemode = 'w',
			level = log_level,
			format = log_format
		)
	else:
		logging.basicConfig(
			level = log_level,
			format = log_format
		)

	#-----------------------------------------------------------------------
	# Annoyance fix per:
	# https://stackoverflow.com/questions/986964/qt-session-management-error
	try:
		del os.environ['SESSION_MANAGER']
	except KeyError:
		pass
	#-----------------------------------------------------------------------

	app = QApplication([])
	try:
		main_window = MainWindow(options.Database)
	except JackError:
		DevilBox('Could not connect to JACK server. Is it running?')
		sys.exit(1)
	main_window.show()
	sys.exit(app.exec())


if __name__ == "__main__":
	sys.exit(main())


#  end jack_midi_looper/gui.py
