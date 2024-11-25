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

	def __init__(self, loop_id):
		cursor = Loops.conn().cursor()
		cursor.execute('SELECT * FROM loops WHERE loop_id = ?', (loop_id,))
		self.loop_id, self.loop_group, self.name, self.beats_per_measure, self.measures, midi_events = cursor.fetchone()
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
		return '<Loop #{0.loop_id}: "{0.name}"; {0.beats_per_measure} beats per measure; {0.measures} measures; {0.event_count} events>'.format(self)

	def print_events(self):
		for i in range(len(self.events)):
			print("{:3d}: ".format(i), end = "")
			print("{:.3f}  0x{:x} {} {}".format(self.events[i][0], *self.events[i][1]))


class Loops:

	_connection = None
	_loop_ids = None
	_groups = None

	@classmethod
	def dbfile(cls):
		try:
			os.mkdir(os.path.join(user_config_dir(), 'ZenSoSo'))
		except FileExistsError:
			pass
		return os.path.join(user_config_dir(), 'ZenSoSo', 'midibanks.db')

	@classmethod
	def conn(cls):
		if cls._connection is None:
			cls._connection = sqlite3.connect(cls.dbfile())
			cls._connection.execute('PRAGMA foreign_keys = ON')
			cls._connection.execute('PRAGMA foreign_keys = ON')
			cursor = cls._connection.execute('SELECT name FROM sqlite_master WHERE type="table"')
			rows = cursor.fetchall()
			if len(rows) == 0:
				cls.init_schema()
		return cls._connection

	@classmethod
	def init_schema(cls):
		cls.conn().execute("DROP INDEX IF EXISTS bpm_index")
		cls.conn().execute("DROP INDEX IF EXISTS measures_index")
		cls.conn().execute("DROP INDEX IF EXISTS pitch_index")
		cls.conn().execute("DROP TABLE IF EXISTS pitches")
		cls.conn().execute("DROP TABLE IF EXISTS loops")
		cls.conn().execute("""
			CREATE TABLE loops (
				loop_id INTEGER PRIMARY KEY,
				loop_group TEXT,
				name TEXT,
				beats_per_measure INTEGER,
				measures INTEGER,
				midi_events BLOB
			)""")
		cls.conn().execute("""
			CREATE TABLE pitches (
				loop_id INTEGER,
				pitch INTEGER,
				FOREIGN KEY(loop_id) REFERENCES loops(loop_id) ON DELETE CASCADE
			)""")
		cls.conn().execute("CREATE INDEX bpm_index ON loops (beats_per_measure)")
		cls.conn().execute("CREATE INDEX measures_index ON loops (measures)")
		cls.conn().execute("CREATE INDEX pitch_index ON pitches (pitch)")

	@classmethod
	def delete_all(cls):
		cls.conn().execute("DELETE FROM loops")
		cls.conn().commit()

	@classmethod
	def import_dirs(cls, base_dir):
		cursor = cls.conn().cursor()
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
				beats_per_measure, measures, pitches, events = cls.read_midi_file(filename)
				evfile = io.BytesIO()
				np.save(evfile, events)
				evfile.seek(0)
				cursor.execute(loop_sql, (loop_group, name, beats_per_measure, measures, evfile.read()))
				cursor.executemany(pitch_sql, [ (cursor.lastrowid, pitch) for pitch in pitches ])
				cls.conn().commit()
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

	@classmethod
	def groups(cls):
		if cls._groups is None:
			cursor = Loops.conn().cursor()
			cursor.execute('SELECT DISTINCT(loop_group) FROM loops')
			cls._groups = [ row[0] for row in cursor.fetchall() ]
		return cls._groups

	@classmethod
	def group_loops(cls, loop_group):
		"""
		Returns list of tuples, each containing (loop_id, name)
		"""
		cursor = Loops.conn().cursor()
		cursor.execute('SELECT loop_id, name FROM loops WHERE loop_group = ?', (loop_group,))
		return cursor.fetchall()

	@classmethod
	def loop_ids(cls):
		if cls._loop_ids is None:
			cursor = Loops.conn().cursor()
			cursor.execute('SELECT loop_id FROM loops')
			cls._loop_ids = [ row[0] for row in cursor.fetchall() ]
		return cls._loop_ids

	@classmethod
	def random_loop(cls):
		return Loop(choice(cls.loop_ids()))



if __name__ == "__main__":
	print(len(Loops.loop_ids()), 'loops')

#  end jack_midi_looper/utils/loops.py
