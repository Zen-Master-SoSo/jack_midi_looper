#  jack_midi_looper/test/__init__.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os
from appdirs import user_config_dir
from jack_midi_looper import Looper, LoopsDB


def test_dbfile():
	return os.path.join(user_config_dir(), 'ZenSoSo', 'looper-tests.db')


class TestLooper(Looper):

	def create_client(self):
		"""
		Setup client and ports.
		"""
		self.client = FakeClient()
		self.out_port = FakePort()


class FakeClient:
	"""
	A Drop-in replacement for Jack-Client's Client class,
	used strictly for testing.
	"""
	samplerate = 100
	blocksize = 33


class FakePort:
	"""
	A Drop-in replacement for Jack-Client's OwnMIDIPort class,
	used strictly for testing.
	"""
	rc = 0

	def clear_buffer(self):
		"""
		Fake -out clear_buffer before writing MIDI data.
		"""
		pass

	def write_midi_event(self, offset, tup):
		"""
		Pretends to write to a midi port, but just prints data to the console.
		"""
		print('MIDI EVENT: {:7d}  0x{:x}  {:d}  {:d}'.format(offset, tup[0], tup[1], tup[2]))
		self.rc += 1


#  end jack_midi_looper/test/__init__.py
