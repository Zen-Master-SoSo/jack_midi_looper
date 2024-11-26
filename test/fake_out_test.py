#  jack_midi_looper/fake_out_test.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os
from appdirs import user_config_dir
from jack_midi_looper import Looper, LoopsDB, FakeClient

dbpath = os.path.join(user_config_dir(), 'ZenSoSo', 'midibanks.db')
try:
	os.mkdir(dbpath)
except FileExistsError:
	pass
loopsdb = LoopsDB(dbpath)
looper = Looper(test=True)
loop = loopsdb.random_loop()
print(loop)
loop.active = True
looper.append_loop(loop)
for i in range(250):
	print('beat %.2f' % looper.beat)
	looper._play_process_callback(FakeClient.blocksize)
