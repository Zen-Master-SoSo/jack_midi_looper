#  jack_midi_looper/test/__init__.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os
from appdirs import user_config_dir
from jack_midi_looper import LoopsDB

def test_db():
	try:
		return test_db.instance
	except AttributeError:
		pass
	db_dir = os.path.join(user_config_dir(), 'ZenSoSo')
	try:
		os.mkdir(db_dir)
	except FileExistsError:
		pass
	test_db.instance = LoopsDB(os.path.join(db_dir, 'looper.db'))
	if len(test_db.instance.loop_ids()) == 0:
		test_db.instance.init_schema()
		test_db.instance.import_dirs(os.path.join(os.path.dirname(__file__), 'drum-loops'))
	return test_db.instance

#  end jack_midi_looper/test/__init__.py
