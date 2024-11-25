#  jack_midi_looper/__init__.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os, sqlite3, glob, re, io, logging
import numpy as np
from math import ceil
from appdirs import user_config_dir
from random import choice
from mido import MidiFile
from jack import Client, CallbackExit


EVENT_STRUCT = np.dtype([ ('beat', float), ('msg', np.uint8, 3) ])
DEFAULT_BEATS_PER_MEASURE = 4
DEFAULT_BEATS_PER_MINUTE = 120
DEFAULT_USECS_PER_BEAT = 500000
USECS_PER_SECOND = 1000000


class Loop:

	def __init__(self, fetched_row):
		self.loop_id, self.loop_group, self.name, \
			self.beats_per_measure, self.measures, midi_events = fetched_row
		evfile = io.BytesIO(midi_events)
		self.events = np.load(evfile)
		self._beat_offset = 0
		self.play = False

	@property
	def event_count(self):
		"""
		Returns the number of note on/off events
		"""
		return len(self.events)

	@property
	def last_beat(self):
		"""
		Returns the highest beat of all events
		"""
		return self.events[-1]['beat']

	@property
	def beat_offset(self):
		"""
		Play position offset, i.e.
			If offset is 4, all notes are played 4 beats late
		"""
		return self._beat_offset

	@beat_offset.setter
	def beat_offset(self, val):
		self.events['beat'] += (val - self._beat_offset)
		self._beat_offset = val

	def events_between(self, start, end):
		"""
		Returns events whose "beat" is >= start and < end
		"""
		return self.events[(self.events['beat'] >= start) & (self.events['beat'] < end)]

	def __str__(self):
		return '<Loop #{0.loop_id}: "{0.name}", {0.beats_per_measure} beats per measure, {0.measures} measures, {0.event_count} events>'.format(self)

	def print_events(self):
		for i in range(len(self.events)):
			print("{:3d}: ".format(i), end = "")
			print("{:.3f}  0x{:x} {} {}".format(self.events[i][0], *self.events[i][1]))


class Loops:

	_connection = None
	_loop_ids = None
	_groups = None

	def __init__(self, dbfile):
		self.dbfile = dbfile
		self._connection = sqlite3.connect(self.dbfile)
		self._connection.execute('PRAGMA foreign_keys = ON')
		cursor = self._connection.execute('SELECT name FROM sqlite_master WHERE type="table"')
		rows = cursor.fetchall()
		if len(rows) == 0:
			self.init_schema()

	def conn(self):
		return self._connection

	def init_schema(self):
		self._connection.execute("DROP INDEX IF EXISTS bpm_index")
		self._connection.execute("DROP INDEX IF EXISTS measures_index")
		self._connection.execute("DROP INDEX IF EXISTS pitch_index")
		self._connection.execute("DROP TABLE IF EXISTS pitches")
		self._connection.execute("DROP TABLE IF EXISTS loops")
		self._connection.execute("""
			CREATE TABLE loops (
				loop_id INTEGER PRIMARY KEY,
				loop_group TEXT,
				name TEXT,
				beats_per_measure INTEGER,
				measures INTEGER,
				midi_events BLOB
			)""")
		self._connection.execute("""
			CREATE TABLE pitches (
				loop_id INTEGER,
				pitch INTEGER,
				FOREIGN KEY(loop_id) REFERENCES loops(loop_id) ON DELETE CASCADE
			)""")
		self._connection.execute("CREATE INDEX bpm_index ON loops (beats_per_measure)")
		self._connection.execute("CREATE INDEX measures_index ON loops (measures)")
		self._connection.execute("CREATE INDEX pitch_index ON pitches (pitch)")

	def delete_all(self):
		self._connection.execute("DELETE FROM loops")
		self._connection.commit()

	def import_dirs(self, base_dir):
		cursor = self._connection.cursor()
		loop_sql = """
			INSERT INTO loops(loop_group, name, beats_per_measure, measures, midi_events)
			VALUES (?,?,?,?,?)
			"""
		pitch_sql = """
			INSERT INTO pitches VALUES (?,?)
			"""
		files = glob.glob(os.path.join(base_dir, '**' , '*.mid'), recursive=True)
		for filename in files:
			loop_group = re.sub(r'(_|[^\w])+', ' ', os.path.dirname(filename).replace(base_dir, ''))
			name = os.path.splitext(os.path.basename(filename))[0]
			try:
				beats_per_measure, measures, pitches, events = self.read_midi_file(filename)
				evfile = io.BytesIO()
				np.save(evfile, events)
				evfile.seek(0)
				cursor.execute(loop_sql, (loop_group, name, beats_per_measure, measures, evfile.read()))
				cursor.executemany(pitch_sql, [ (cursor.lastrowid, pitch) for pitch in pitches ])
				self._connection.commit()
			except Exception as e:
				print('Failed to import {}. ERROR {} "{}".'.format(name, type(e).__name__, e))

	@classmethod
	def read_midi_file(cls, midi_filename):
		"""
		Returns beats_per_measure, measures, pitches, events
			beats_per_measure	: (int)
			measures			: (int) measure count, rounded up
			pitches				: (set) pitches of a noteon events
			events				: nparray of EVENT_STRUCT
		"""
		# Use mido to open
		mid = MidiFile(midi_filename)
		# Default calculations, overriden by set_tempo and time_signature events
		usecs_per_beat = DEFAULT_USECS_PER_BEAT
		beats_per_measure = DEFAULT_BEATS_PER_MEASURE
		seconds_per_beat = usecs_per_beat / USECS_PER_SECOND
		seconds_per_measure = seconds_per_beat * beats_per_measure
		# Initialize numpy array
		note_event_count = 0
		for msg in mid:
			if msg.type == 'note_on':
				note_event_count += 1
		events = np.zeros(note_event_count, EVENT_STRUCT)
		# Initialize running vars
		time = 0
		ordinal = 0
		measure = 0
		pitches = []
		for msg in mid:
			if msg.type == 'set_tempo':
				usecs_per_beat = msg.tempo
				seconds_per_beat = usecs_per_beat / USECS_PER_SECOND
				seconds_per_measure = seconds_per_beat * beats_per_measure
			elif msg.type == 'time_signature':
				beats_per_measure = msg.numerator * 4 / msg.denominator
				seconds_per_measure = seconds_per_beat * beats_per_measure
			elif msg.type == 'note_on':
				measure = int(time / seconds_per_measure)
				beat = time / seconds_per_beat
				events[ordinal] = ( beat, msg.bytes() )
				ordinal += 1
				pitches.append(msg.note)
			time += msg.time
		return int(beats_per_measure), measure + 1, set(pitches), events

	def groups(self):
		if self._groups is None:
			cursor = self._connection.cursor()
			cursor.execute('SELECT DISTINCT(loop_group) FROM loops')
			self._groups = [ row[0] for row in cursor.fetchall() ]
		return self._groups

	def group_loops(self, loop_group):
		"""
		Returns list of tuples, each containing (loop_id, name)
		"""
		cursor = self._connection.cursor()
		cursor.execute('SELECT loop_id, name FROM loops WHERE loop_group = ?', (loop_group,))
		return cursor.fetchall()

	def loop_ids(self):
		if self._loop_ids is None:
			cursor = self._connection.cursor()
			cursor.execute('SELECT loop_id FROM loops')
			self._loop_ids = [ row[0] for row in cursor.fetchall() ]
		return self._loop_ids

	def loop(self, loop_id):
		cursor = self._connection.cursor()
		cursor.execute('SELECT * FROM loops WHERE loop_id = ?', (loop_id,))
		return Loop(cursor.fetchone())

	def random_loop(self):
		return self.loop(choice(self.loop_ids()))


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



if __name__ == "__main__":
	loops = Loops(os.path.join(user_config_dir(), 'ZenSoSo', 'midibanks.db'))
	print(len(loops.groups()), 'groups')
	print(len(loops.loop_ids()), 'loops')
	print('Random loop:')
	print(loops.random_loop())

#  end jack_midi_looper/__init__.py
