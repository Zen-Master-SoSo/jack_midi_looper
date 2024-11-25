#  jack_midi_looper/looper.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os
import logging
import numpy as np
from math import ceil
from jack import Client, CallbackExit
from jack_midi_looper import Loop

DEFAULT_BEATS_PER_MINUTE = 120


class Looper:

	# state constants:
	INACTIVE	= 0
	PLAYING		= 1

	def __init__(self, client_name='looper', test=False):
		self._bpm = DEFAULT_BEATS_PER_MINUTE
		self.beats_per_measure = None
		self.beat = 0.0
		self.last_beat = 0.0
		self.loops = []
		self.state = Looper.INACTIVE
		self.__real_process_callback = self.null_process_callback
		self.client_name = client_name
		if test:
			self.client = FakeClient()
			self.out_port = FakePort()
			self.rescale()
		else:
			self.client = Client(self.client_name, no_start_server=True)
			self.client.set_blocksize_callback(self.blocksize_callback)
			self.client.set_samplerate_callback(self.samplerate_callback)
			self.client.set_process_callback(self.process_callback)
			self.client.set_shutdown_callback(self.shutdown_callback)
			self.client.set_xrun_callback(self.xrun_callback)
			self.client.activate()
			self.client.get_ports()
			self.out_port = self.client.midi_outports.register('out')

	@property
	def bpm(self):
		"""
		Play position offset, i.e.
			If offset is 4, all notes are played 4 beats late
		"""
		return self._bpm

	@bpm.setter
	def bpm(self, val):
		self._bpm = val
		self.rescale()

	def append_loop(self, loop):
		"""
		Loads a single loop.
		Throws up if the loop's beats per measure does not
		match all the loaded loop's beats per measure.
		Returns appended loop for chaining.
		"""
		if self.beats_per_measure is not None and \
			loop.beats_per_measure != self.beats_per_measure:
			raise Exception("beats_per_measure mismatch")
		with Pause(self):
			self.beats_per_measure = loop.beats_per_measure
			self.loops.append(loop)
			self.remeasure()
		return loop

	def extend_loops(self, loop_list):
		"""
		Loads multiple loops.
		Throws up if any loop's beats per measure does not
		match all the loaded loop's beats per measure.
		"""
		if self.beats_per_measure is None:
			self.beats_per_measure = loop_list[0].beats_per_measure
		for loop in loop_list:
			if loop.beats_per_measure != self.beats_per_measure:
				raise Exception("beats_per_measure mismatch")
		with Pause(self):
			self.loops.extend(loop_list)
			self.remeasure()

	def remeasure(self):
		if self.loops:
			last_beat = max([loop.last_beat for loop in self.loops])
			self.last_beat = float(ceil(last_beat / self.beats_per_measure) * self.beats_per_measure)
			if self.beat > self.last_beat:
				self.beat = 0.0
		else:
			self.beat = 0.0
			self.last_beat = 0.0

	def loop(self, loop_id):
		for loop in self.loops:
			if loop.loop_id == loop_id:
				return loop
		return None

	def loaded_loop_ids(self):
		return [loop.loop_id for loop in self.loops]

	def any_loop_active(self):
		for loop in self.loops:
			if loop.play:
				return True
		return False

	def clear(self):
		self.stop()
		self.loops = []
		self.beats_per_measure = None

	def rescale(self):
		beats_per_second = self._bpm / 60
		self.samples_per_beat = self.client.samplerate / beats_per_second
		seconds_per_process = self.client.blocksize / self.client.samplerate
		self.beats_per_process = beats_per_second * seconds_per_process

	def stop(self):
		if self.state == Looper.INACTIVE:
			return
		logging.debug('STOP')
		self.__real_process_callback = self.stop_process_callback

	def play(self):
		if self.state == Looper.PLAYING:
			return
		logging.debug('PLAY')
		self.__real_process_callback = self.play_process_callback
		self.state = Looper.PLAYING

	def null_process_callback(self, frames):
		pass

	def play_process_callback(self, frames):
		if self.any_loop_active():
			self.out_port.clear_buffer()
			last_beat = self.beat + self.beats_per_process
			while True:
				events_this_block = np.hstack([loop.events_between(self.beat, last_beat) \
					for loop in self.loops if loop.play])
				if len(events_this_block):
					for evt in np.sort(events_this_block, kind="heapsort", order="beat"):
						offset = int((evt['beat'] - self.beat) * self.samples_per_beat)
						self.out_port.write_midi_event(offset, evt['msg'])
				if last_beat < self.last_beat:
					self.beat = last_beat
					break
				last_beat -= self.last_beat
				self.beat = 0.0

	def stop_process_callback(self, frames):
		"""
		Sends MIDI message "All Notes Off" (0x7B) to all channels from 0 - 15
		"""
		self.out_port.clear_buffer()
		msg = bytearray.fromhex('B07B')
		for channel in range(16):
			self.out_port.write_midi_event(0, msg)
			msg[0] += 1
		self.beat = 0.0
		self.__real_process_callback = self.null_process_callback
		self.state = Looper.INACTIVE

	# -----------------------
	# JACK callbacks

	def blocksize_callback(self, blocksize):
		self.rescale()

	def samplerate_callback(self, samplerate):
		self.rescale()

	def process_callback(self, frames):
		try:
			self.__real_process_callback(frames)
		except Exception as e:
			tb = e.__traceback__
			logging.error('{} {}(), line {}: {} "{}"'.format(
				os.path.basename(tb.tb_frame.f_code.co_filename),
				tb.tb_frame.f_code.co_name,
				tb.tb_lineno,
				type(e).__name__,
				str(e),
			))
			raise CallbackExit

	def shutdown_callback(self, status, reason):
		"""
		The argument status is of type jack.Status.
		"""
		logging.debug('JACK Shutdown')
		if self.state != Looper.INACTIVE:
			raise JackShutdownError

	def xrun_callback(self, delayed_usecs):
		"""
		The callback argument is the delay in microseconds due to the most recent XRUN
		occurrence. The callback is supposed to raise CallbackExit on error.
		"""
		logging.debug(f'xrun: delayed {delayed_usecs:.2f} microseconds')
		pass


class JackShutdownError(Exception):

	pass


class FakeClient:

	samplerate = 48000
	blocksize = 1024


class FakePort:

	rc = 0

	def clear_buffer(self):
		pass

	def write_midi_event(self, offset, tup):
		print('MIDI EVENT: {:7d}  0x{:x}  {:d}  {:d}'.format(offset, tup[0], tup[1], tup[2]))
		self.rc += 1


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



#  end jack_midi_looper/gui.py
