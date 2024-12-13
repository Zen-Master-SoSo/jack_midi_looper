#  jack_midi_looper/test/fake_out_test.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
from jack_midi_looper import Looper, FakeClient
from jack_midi_looper.test import test_db

looper = Looper(test=True)
loop = test_db().random_loop()
print(loop)
loop.active = True
looper.append_loop(loop)
for i in range(250):
	print('beat %.2f' % looper.beat)
	looper._play_process_callback(FakeClient.blocksize)

#  end jack_midi_looper/test/fake_out_test.py
