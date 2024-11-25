#  jack_midi_looper/utils/loops.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os, io, sqlite3, glob, re
import numpy as np
from appdirs import user_config_dir
from random import choice
from mido import MidiFile


EVENT_STRUCT = np.dtype([ ('beat', float), ('msg', np.uint8, 3) ])
DEFAULT_BEATS_PER_MEASURE = 4
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



if __name__ == "__main__":
	loops = Loops(os.path.join(user_config_dir(), 'ZenSoSo', 'midibanks.db'))
	print(len(loops.groups()), 'groups')
	print(len(loops.loop_ids()), 'loops')
	print('Random loop:')
	print(loops.random_loop())

#  end jack_midi_looper/utils/loops.py
