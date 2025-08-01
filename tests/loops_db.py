#  jack_midi_looper/test/loops_db.py
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
Run a test of the looper db - displays all events in a loop.
"""
import sys, os
from appdirs import user_config_dir
from jack_midi_looper import LoopsDB


def main():
	test_db_path = os.path.join(user_config_dir(), 'ZenSoSo', 'looper-tests.db')
	print('using', test_db_path)
	loops_db = LoopsDB(test_db_path)
	if len(loops_db.loop_ids()) == 0:
		loops_db.import_dirs(os.path.join(os.path.dirname(__file__), 'drum-loops'))
	loop = loops_db.random_loop()
	print('using loop', loop)
	loop.print_events()


if __name__ == "__main__":
	sys.exit(main())


#  end jack_midi_looper/test/loops_db.py
