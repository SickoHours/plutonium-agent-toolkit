"""Opt-in smoke check: writes one trivial T3 thread, never controls the game.

PAT_AGENT_LIVE=1 enables this test. PAT_AGENT_PROJECT, PAT_AGENT_INSTANCE and PAT_AGENT_MODEL
must be explicit; PAT_AGENT_ORIGIN and PAT_AGENT_OPTIONS (JSON list of id=value) are optional.
Only t3.token() may obtain the already configured bearer. No other credential source is read.
"""
import json
import os
import unittest

from plutonium_agent_toolkit.agent import t3
from plutonium_agent_toolkit.core.errors import CONFIG_MISSING, Failure


class LiveAgentTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('PAT_AGENT_LIVE') == '1', 'opt-in: set PAT_AGENT_LIVE=1')
    def test_probe_and_launch_trivial_thread(self):
        try:
            bearer = t3.token()
        except Failure as exc:
            if exc.code == CONFIG_MISSING:
                self.skipTest('configured t3_bearer_token is absent; authenticated launch unverified')
            raise
        required = ('PAT_AGENT_PROJECT', 'PAT_AGENT_INSTANCE', 'PAT_AGENT_MODEL')
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            self.skipTest('explicit live target required: ' + ', '.join(missing))
        origin, state = t3.origin_for(os.environ.get('PAT_AGENT_ORIGIN'))
        t3.require_token_safe_origin(origin, state)
        info = t3.probe(origin)
        self.assertTrue(info['drivable'])
        selection = t3.model_selection(os.environ['PAT_AGENT_INSTANCE'], os.environ['PAT_AGENT_MODEL'],
                                       json.loads(os.environ.get('PAT_AGENT_OPTIONS', '[]')))
        result = t3.dispatch(origin, bearer, project_id=os.environ['PAT_AGENT_PROJECT'],
                             title='pat opt-in protocol smoke check',
                             prompt='Reply with exactly OK. Do not use tools, edit files, or run commands.',
                             selection=selection, runtime_mode='approval-required')
        self.assertTrue(result['thread_id'])
        current = t3.status(origin, bearer, result['thread_id'])
        self.assertEqual(current['thread_id'], result['thread_id'])
        self.assertFalse(result['game_touched'])
