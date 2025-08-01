#  jack_midi_looper/test/fake_out_test.py
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
Run a test of the looping algo - displays beat and offsets.
"""
import sys, os
from appdirs import user_config_dir
from jack_midi_looper import Looper, LoopsDB

class TestLooper(Looper):
	"""
	A drop-in replacement for the Looper class, which creates fake clients for
	testing.
	"""

	def create_client(self):
		"""
		Setup client and ports.
		"""
		self.client = FakeClient()
		self.out_port = FakePort()


class FakeClient:
	"""
	A drop-in replacement for Jack-Client's Client class,
	used strictly for testing.
	"""
	samplerate = 100
	blocksize = 33


class FakePort:
	"""
	A drop-in replacement for Jack-Client's OwnMIDIPort class,
	used strictly for testing.
	"""
	rc = 0

	def clear_buffer(self):
		"""
		Fake -out clear_buffer before writing MIDI data.
		"""

	def write_midi_event(self, offset, tup):
		"""
		Pretends to write to a midi port, but just prints data to the console.
		"""
		print(f'MIDI EVENT: {offset:7d}  0x{tup[0]:x}  {tup[1]:d}  {tup[2]:d}')
		self.rc += 1


def main():
	looper = TestLooper()
	test_db_path = os.path.join(user_config_dir(), 'ZenSoSo', 'looper-tests.db')
	print('using', test_db_path)
	loops_db = LoopsDB(test_db_path)
	if len(loops_db.loop_ids()) == 0:
		loops_db.import_dirs(os.path.join(os.path.dirname(__file__), 'drum-loops'))
	loop = loops_db.random_loop()
	print('using loop', loop)
	loop.active = True
	looper.append_loop(loop)
	for i in range(250):
		print(f'beat {looper.beat:.2f}')
		looper._play_process_callback(FakeClient.blocksize)


if __name__ == "__main__":
	sys.exit(main())


#  end jack_midi_looper/test/fake_out_test.py
