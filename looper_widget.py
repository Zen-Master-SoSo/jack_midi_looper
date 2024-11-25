#  jack_midi_looper/looper_widget.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os
from functools import partial
from PyQt5 import uic
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QFrame
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QGridLayout

from qt_extras import ShutUpQT

from jack_midi_looper import Loops, Looper


class LooperWidget(QFrame):

	single_loop	= False # Set True to play one loop at a time
	columns = 6

	def __init__(self, parent, loops):
		super().__init__(parent)
		self.loops = loops
		my_dir = os.path.dirname(__file__)
		with ShutUpQT():
			uic.loadUi(os.path.join(my_dir, 'res', 'looper_widget.ui'), self)
		self.cmb_group.addItem('')
		self.cmb_group.addItems(self.loops.groups())
		self.cmb_group.currentTextChanged.connect(self.group_changed)
		self.beat_spinner.valueChanged.connect(self.set_bpm)
		self.play_button.toggled.connect(self.play_toggle)
		self.loops_layout = QGridLayout()
		self.loops_layout.setContentsMargins(0,0,0,0)
		self.loops_layout.setSpacing(2)
		self.frm_loops.setLayout(self.loops_layout)
		self.loops_font = self.play_button.font()
		self.loops_font.setPointSize(8)
		self.looper = Looper()
		self.update_timer = QTimer()
		self.update_timer.setInterval(int(1 / 8 * 1000))
		self.update_timer.timeout.connect(self.slot_timer_timeout)

	@pyqtSlot()
	def slot_timer_timeout(self):
		self.beat.display(int(self.looper.beat + 1.0))

	@pyqtSlot(str)
	def group_changed(self, text):
		self.looper.stop()
		self.looper.clear()
		self.play_button.setChecked(False)
		self.play_button.setEnabled(False)
		for button in self.frm_loops.findChildren(QPushButton):
			self.loops_layout.removeWidget(button)
			button.deleteLater()
		if text == '':
			return
		new_loops = [self.loops.loop(tup[0]) for tup in self.loops.group_loops(text)]
		if new_loops:
			new_loops.sort(key=lambda loop: loop.name)
			self.looper.extend_loops(new_loops)
			rows = len(new_loops) // self.columns + 1
			ord_ = 0
			for loop in new_loops:
				button = QPushButton('{} ({} measures)'.format(loop.name, loop.measures), self.frm_loops)
				button.setFont(self.loops_font)
				button.setCheckable(True)
				button.loop_id = loop.loop_id
				button.toggled.connect(partial(self.loop_select, loop.loop_id))
				self.loops_layout.addWidget(button, ord_ % rows, int(ord_ / rows))
				ord_ += 1

	@pyqtSlot(int, bool)
	def loop_select(self, loop_id, state):
		if state and self.single_loop:
			for button in self.frm_loops.findChildren(QPushButton):
				if button.loop_id != loop_id:
					button.setChecked(False)
		self.looper.loop(loop_id).play = state
		if state:
			self.looper.remeasure()
		self.play_button.setEnabled(self.looper.any_loop_active())

	@pyqtSlot(bool)
	def play_toggle(self, state):
		if state:
			self.update_timer.start()
			self.looper.play()
		else:
			self.update_timer.stop()
			self.looper.stop()

	@pyqtSlot(int)
	def set_bpm(self, bpm):
		self.looper.bpm = bpm

	def sizeHint(self):
		return QSize(490, 50)


#  end jack_midi_looper/looper_widget.py
