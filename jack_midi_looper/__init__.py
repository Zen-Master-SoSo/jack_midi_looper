#  jack_midi_looper/__init__.py
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
A jack client which generates MIDI events by beat, not time, using "loops" imported from midi files.
"""
import os, sqlite3, glob, re, io, logging
from threading import Event, Lock
from math import ceil
from random import choice
import numpy as np
from appdirs import user_config_dir
from mido import MidiFile
from jack import Client, CallbackExit
from log_soso import log_error
from progress.bar import IncrementalBar

__version__ = "1.1.0"

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
		self.active = False

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
		"""
		Nicely formatted event printing
		"""
		for i, event in enumerate(self.events):
			print("{:3d}: ".format(i), end = "")
			print("{:.3f}  0x{:x} {} {}".format(event[0], *event[1]))


class LoopsDB:
	"""
	Interface to sqlite database in which loops are saved.
	"""

	_connection = None
	_loop_names = None
	_groups = None

	def __init__(self, dbfile):
		if not os.path.isfile(dbfile):
			db_dir = os.path.dirname(dbfile)
			try:
				os.mkdir(db_dir)
			except FileExistsError:
				pass
		self._connection = sqlite3.connect(dbfile)
		self._connection.execute('PRAGMA foreign_keys = ON')
		cursor = self._connection.execute('SELECT name FROM sqlite_master WHERE type="table"')
		rows = cursor.fetchall()
		if len(rows) == 0:
			self.init_schema()

	def conn(self):
		"""
		Public access to the database connection.
		"""
		return self._connection

	def init_schema(self):
		"""
		Nukes any existing tables (if they exist) and rebuilds the database schema.
		"""
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
		"""
		Deletes all loops (and thus, groups) from the database.
		"""
		self._connection.execute("DELETE FROM loops")
		self._connection.commit()

	def import_dirs(self, base_dir):
		"""
		Recursively searches for midi files in the given directory and adds each of
		them to the database as a new Loop.
		"""
		cursor = self._connection.cursor()
		loop_sql = """
			INSERT INTO loops(loop_group, name, beats_per_measure, measures, midi_events)
			VALUES (?,?,?,?,?)
			"""
		pitch_sql = """
			INSERT INTO pitches VALUES (?,?)
			"""
		files = glob.glob(os.path.join(base_dir, '**' , '*.mid'), recursive=True)
		with IncrementalBar('Importing loops', max=len(files)) as progress_bar:
			for filename in files:
				loop_group = re.sub(r'(_|[^\w])+', ' ', os.path.dirname(filename).replace(base_dir, '')).strip()
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
				progress_bar.next()
		self._loop_names = None
		self._groups = None

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
		"""
		Returns list of strings, all group names in the database.
		"""
		if self._groups is None:
			cursor = self._connection.cursor()
			cursor.execute('SELECT DISTINCT(loop_group) FROM loops')
			self._groups = [ row[0] for row in cursor.fetchall() ]
		return self._groups

	def group_loops(self, loop_group):
		"""
		Returns list of Loop objects belonging to the given group.
		loop_group: (string) group name
		"""
		cursor = self._connection.cursor()
		cursor.execute('SELECT * FROM loops WHERE loop_group = ? ORDER BY name', (loop_group,))
		return [ Loop(row) for row in cursor.fetchall() ]

	def loop_ids(self):
		"""
		Return a list of all loop_ids in the database.
		"""
		return list(self.loop_names().keys())

	def loop_names(self):
		"""
		Returns dict(loop_id:name)
		"""
		if self._loop_names is None:
			cursor = self._connection.cursor()
			cursor.execute('SELECT loop_id, name FROM loops')
			self._loop_names = { row[0]:row[1] for row in cursor.fetchall() }
		return self._loop_names

	def loop(self, loop_id):
		"""
		Returns a Loop identified by the given loop_id.
		"""
		cursor = self._connection.cursor()
		cursor.execute('SELECT * FROM loops WHERE loop_id = ?', (loop_id,))
		return Loop(cursor.fetchone())

	def random_loop(self):
		"""
		Returns one random Loop object.
		"""
		return self.loop(choice(self.loop_ids()))


class Looper:

	def __init__(self, client_name = 'looper'):
		self.client_name = client_name
		self._bpm = DEFAULT_BEATS_PER_MINUTE
		self.beats_per_measure = None
		self.beat = 0.0
		self.beats_length = 0.0
		self.loops = {} 	# dict indexed on loop_id
		self.loop_exclusive = True
		self.is_playing = False
		self.stop_event = Event()
		self.loop_manipulation_lock = Lock()
		self._real_process_callback = self._null_process_callback
		self.create_client()
		self._rescale()

	def create_client(self):
		"""
		Setup client and ports. Extend for custom classes.
		"""
		self.client = Client(self.client_name, no_start_server=True)
		self.client.set_blocksize_callback(self._blocksize_callback)
		self.client.set_samplerate_callback(self._samplerate_callback)
		self.client.set_process_callback(self._process_callback)
		self.client.set_shutdown_callback(self._shutdown_callback)
		self.client.set_xrun_callback(self._xrun_callback)
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
		self._rescale()

	def append_loop(self, loop):
		"""
		Loads a single loop.
		Throws up if the loop's beats per measure does not
		match all the loaded loop's beats per measure.
		Returns appended loop for chaining.
		"""
		if self.beats_per_measure is not None and \
			loop.beats_per_measure != self.beats_per_measure:
			raise RuntimeError("beats_per_measure mismatch")
		with self.loop_manipulation_lock:
			self.beats_per_measure = loop.beats_per_measure
			self.loops[loop.loop_id] = loop
			self._remeasure()
		return loop

	def extend_loops(self, loop_list):
		"""
		Loads multiple loops.
		Throws up if any loop's beats per measure does not
		match all the loaded loop's beats per measure.
		"""
		beats_per_measure = loop_list[0].beats_per_measure \
			if self.beats_per_measure is None \
			else self.beats_per_measure
		for loop in loop_list:
			if loop.beats_per_measure != beats_per_measure:
				raise RuntimeError("beats_per_measure mismatch")
		with self.loop_manipulation_lock:
			self.beats_per_measure = beats_per_measure
			self.loops.update({ loop.loop_id:loop for loop in loop_list })
			self._remeasure()

	def enable_loop(self, loop_id, state):
		"""
		Sets the "active" property on the loop identified by loop_id to match the
		"state" condition (True/False).
		If "self.loop_exclusive" is True, and "state" is True, resets the "active"
		property on all other loaded loops so that only one loop is active at a time.
		"""
		if state and self.loop_exclusive:
			for loop in self.loops.values():
				loop.active = loop.loop_id == loop_id
		else:
			self.loops[loop_id].active = state
		with self.loop_manipulation_lock:
			self._remeasure()

	def _remeasure(self):
		"""
		Determines how many beats to loop based on the beats-per-measure and total
		number of beats in all active loops. Called from "append_loop" and
		"extend_loops" functions.
		"""
		if self.any_loop_active():
			last_beat = max( loop.last_beat for loop in self.loops.values() if loop.active )
			self.beats_length = float(ceil(last_beat / self.beats_per_measure) * self.beats_per_measure)
		else:
			self.beats_length = 0.0
		if self.beat > self.beats_length:
			self.beat = 0.0

	def loop(self, loop_id):
		return self.loops[loop_id]

	def loaded_loop_ids(self):
		"""
		Returns the loop_id of every loaded loop.
		"""
		return list(self.loops.keys())

	def any_loop_active(self):
		"""
		Returns boolean True if any loaded loop's "active" attribute is True.
		"""
		return any(loop.active for loop in self.loops.values())

	def clear(self):
		"""
		Removes all loops from the current loaded loops.
		"""
		self.stop()
		self.loops = {}
		self.beats_per_measure = None

	def _rescale(self):
		beats_per_second = self._bpm / 60
		self.samples_per_beat = self.client.samplerate / beats_per_second
		seconds_per_process = self.client.blocksize / self.client.samplerate
		self.beats_per_process = beats_per_second * seconds_per_process

	def stop(self):
		"""
		Transitions to "_stop_process_callback", which sends "Note Off"
		to all channels.
		"""
		if self.is_playing:
			self.is_playing = False
			self.stop_event.clear()
			self._real_process_callback = self._stop_process_callback
			self.stop_event.wait()

	def play(self):
		"""
		Start playing any active loops (loops whose "active" attribute is True).
		"""
		if not self.is_playing:
			self.is_playing = True
			self._real_process_callback = self._play_process_callback

	def _null_process_callback(self, frames):
		pass

	def _play_process_callback(self, _):
		self.out_port.clear_buffer()
		if self.any_loop_active() and not self.loop_manipulation_lock.locked():
			last_beat = self.beat + self.beats_per_process
			while True:
				events_this_block = np.hstack([loop.events_between(self.beat, last_beat) \
					for loop in self.loops.values() if loop.active])
				if len(events_this_block):
					for evt in np.sort(events_this_block, kind="heapsort", order="beat"):
						offset = int((evt['beat'] - self.beat) * self.samples_per_beat)
						self.out_port.write_midi_event(offset, evt['msg'])
				if last_beat < self.beats_length:
					self.beat = last_beat
					break
				last_beat -= self.beats_length
				self.beat -= self.beats_length

	def _stop_process_callback(self, _):
		"""
		Sends MIDI message "All Notes Off" (0x7B) to all channels from 0 - 15,
		and then transitions to "_null_process_callback"
		"""
		self.out_port.clear_buffer()
		msg = bytearray.fromhex('B07B')
		for channel in range(16):
			self.out_port.write_midi_event(0, msg)
			msg[0] += 1
		self._real_process_callback = self._null_process_callback
		self.stop_event.set()

	# -----------------------
	# JACK callbacks

	def _blocksize_callback(self, _):
		"""
		Called from jack client when blocksize changes.
		"""
		self._rescale()

	def _samplerate_callback(self, _):
		"""
		Called from jack client when samplerate changes.
		"""
		self._rescale()

	def _process_callback(self, frames):
		"""
		Called from jack client once per process block
		"""
		try:
			self._real_process_callback(frames)
		except Exception as e:
			log_error(e)
			self.stop_event.set()
			raise CallbackExit

	def _shutdown_callback(self, *_):
		"""
		The argument status is of type jack.Status.
		"""
		logging.debug('JACK Shutdown')
		if self.is_playing:
			raise JackShutdownError

	def _xrun_callback(self, delayed_usecs):
		"""
		The callback argument is the delay in microseconds due to the most recent XRUN
		occurrence. The callback is supposed to raise CallbackExit on error.
		"""
		logging.debug('xrun: delayed %.2f microseconds', delayed_usecs)


class JackShutdownError(RuntimeError):
	"""
	Used to notify calling process that the Jack server has shutdown.
	"""


#  end jack_midi_looper/__init__.py
