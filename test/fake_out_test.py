#  jack_midi_looper/test/fake_out_test.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import sys
from jack_midi_looper.test import test_db, TestLooper, FakeClient

def main():
	looper = TestLooper()
	loop = test_db().random_loop()
	print(loop)
	loop.active = True
	looper.append_loop(loop)
	for i in range(250):
		print('beat %.2f' % looper.beat)
		looper._play_process_callback(FakeClient.blocksize)


if __name__ == "__main__":
	sys.exit(main())


#  end jack_midi_looper/test/fake_out_test.py
