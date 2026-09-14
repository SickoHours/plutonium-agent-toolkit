"""Regressions found while reviewing the delegated transport implementation."""
import itertools
import json
import unittest
from unittest.mock import Mock, patch

from plutonium_agent_toolkit.agent import ws_rpc
from plutonium_agent_toolkit.core.errors import Failure
from test_agent_ws_rpc import Socket, TOKEN, success


class TransportReviewTests(unittest.TestCase):
    def call(self, sock, payload=None, timeout=1):
        with patch.object(ws_rpc, 'connect', return_value=sock):
            return ws_rpc.call('http://127.0.0.1:3773', TOKEN,
                               'orchestration.launchThread', payload or {}, timeout=timeout)

    def test_launch_error_uses_the_actual_contract_tag_without_rollback_claim(self):
        sock = Socket([lambda rid: {'_tag': 'Exit', 'requestId': rid, 'exit': {
            '_tag': 'Failure', 'cause': [{'_tag': 'Fail', 'error': {
                '_tag': 'OrchestrationV2ThreadLaunchError', 'message': TOKEN}}]}}])
        with self.assertRaises(Failure) as ctx:
            self.call(sock)
        self.assertEqual(ctx.exception.code, 'input_invalid')
        self.assertNotIn('not applied', ctx.exception.message)
        self.assertNotIn(TOKEN, json.dumps(ctx.exception.to_dict()))

    def test_untrusted_tags_bad_causes_and_nested_json_stay_sanitized(self):
        for frame in ({'_tag': TOKEN}, {'_tag': [TOKEN]}, '[' * 1500 + '0' + ']' * 1500,
                      lambda rid: {'_tag': 'Exit', 'requestId': rid, 'exit': {
                          '_tag': 'Failure', 'cause': [None]}}):
            sock = Socket([frame])
            with self.subTest(frame=type(frame)), self.assertRaises(Failure) as ctx:
                self.call(sock)
            self.assertEqual(ctx.exception.code, 'delivery_uncertain')
            self.assertNotIn(TOKEN, json.dumps(ctx.exception.to_dict()))
            self.assertTrue(sock.closed)

    def test_unicode_prompt_at_route_limit_fits_the_transport(self):
        sock = Socket([lambda rid: success(rid)])
        self.call(sock, {'text': '\U0001f30d' * 200_000})
        self.assertEqual(len(sock.sent), 1)

    def test_unrelated_messages_do_not_extend_the_deadline(self):
        sock = Socket([{'_tag': 'Pong'}] * 20)
        ticks = itertools.count(0, 0.05)
        with patch.object(ws_rpc.time, 'monotonic', side_effect=lambda: next(ticks)):
            with self.assertRaises(Failure) as ctx:
                self.call(sock, timeout=0.2)
        self.assertEqual(ctx.exception.code, 'delivery_uncertain')
        self.assertEqual(len(sock.sent), 1)
        self.assertTrue(sock.closed)

    def test_cannot_bound_socket_write_means_no_command_sent(self):
        sock = Socket()
        sock.socket = Mock()
        sock.socket.settimeout.side_effect = OSError(TOKEN)
        with self.assertRaises(Failure) as ctx:
            self.call(sock)
        self.assertEqual(ctx.exception.code, 'backend_failed')
        self.assertEqual(sock.sent, [])
        self.assertNotIn(TOKEN, json.dumps(ctx.exception.to_dict()))

    def test_send_failure_is_uncertain_and_cleanup_does_not_override_it(self):
        sock = Socket()
        sock.send = Mock(side_effect=OSError(TOKEN))
        sock.close = Mock(side_effect=OSError(TOKEN))
        with self.assertRaises(Failure) as ctx:
            self.call(sock)
        self.assertEqual(ctx.exception.code, 'delivery_uncertain')
        self.assertNotIn(TOKEN, json.dumps(ctx.exception.to_dict()))
        sock.send.assert_called_once()
        sock.close.assert_called_once()
