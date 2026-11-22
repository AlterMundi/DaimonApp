"""Synthetic cleanup receipts only: no simulator, signal, microphone or provider."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('simulator',Path(__file__).with_name('test-simulator.py'))
simulator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulator)

class CleanupTests(unittest.TestCase):
    def test_unknown_signal_and_exit_preserve_original_error_without_retry(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root); (state/'server.pid').write_text('123')
            server = Mock(); server.poll.return_value = None
            server.wait.side_effect = subprocess.TimeoutExpired('wait',10)
            with patch.object(simulator.subprocess,'run',side_effect=subprocess.TimeoutExpired('kill',10)) as send:
                original = RuntimeError('original boot observation failed')
                with self.assertRaisesRegex(RuntimeError,'original boot observation failed'):
                    try:
                        raise original
                    finally:
                        self.assertEqual(simulator.stop_fixture(server,state),{'signal':'unconfirmed','stopped':False})
                send.assert_called_once_with(['sudo','-n','kill','-TERM','123'],capture_output=True,timeout=10)
                server.wait.assert_called_once_with(timeout=10)

    def test_signal_ack_is_not_exit_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root); (state/'server.pid').write_text('123')
            server = Mock(); server.poll.return_value = None
            server.wait.side_effect = subprocess.TimeoutExpired('wait',10)
            with patch.object(simulator.subprocess,'run',return_value=Mock(returncode=0)) as send:
                self.assertEqual(simulator.stop_fixture(server,state),{'signal':'acknowledged','stopped':False})
                self.assertEqual(send.call_count,1)

    def test_observed_exit_never_sends_another_signal(self):
        with tempfile.TemporaryDirectory() as root:
            server = Mock(); server.poll.return_value = 0
            with patch.object(simulator.subprocess,'run') as send:
                self.assertEqual(simulator.stop_fixture(server,Path(root)),{'signal':'not_needed','stopped':True})
                send.assert_not_called()

if __name__ == '__main__': unittest.main()
