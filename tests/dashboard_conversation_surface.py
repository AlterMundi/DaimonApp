"""Real canonical HTTP shell/auth/frame policy; synthetic Home identity only."""
import time
import uuid
from unittest.mock import patch
from dashboard_companion_io import Companion
from dashboard.conversation_surface import parent_origins


class Surface(Companion):
    def test_configured_surface_keeps_home_auth_and_scoped_frame_policy(self):
        self.web_only()
        self.config['conversation_surface']={'parent_origins':['https://world.test']}
        self.client.close();self.client=self.client_for()
        visit=str(uuid.uuid4());query={'view':'conversation','client':'standalone','surface':'holodeck','surface_parent':'https://world.test','surface_visit':visit}
        shell=self.client.get('/',params=query)
        self.assertEqual(shell.status_code,200,shell.text)
        self.assertIn('data-surface-parent="https://world.test"',shell.text)
        self.assertIn('data-shared-auth="true"',shell.text)
        self.assertIn('conversation-surface',shell.text)
        self.assertIn('assets/conversation-surface.js?v=',shell.text)
        self.assertEqual(shell.headers['permissions-policy'],'microphone=(self)')
        self.assertTrue(shell.headers['content-security-policy'].endswith("frame-ancestors 'self' https://web.telegram.org https://world.test"))
        normal=self.client.get('/?view=conversation&client=standalone')
        self.assertNotIn('https://world.test',normal.headers['content-security-policy'])
        self.assertNotIn('data-surface-parent=',normal.text)
        self.assertEqual(self.client.get('/api/interaction/access').status_code,401)
        identity={'contract':'dm.home-session/v1','origin':self.config['origin'],'expires':int(time.time())+3600,'actor':{'kind':'human','ref':'human:telegram:100'}}
        headers={'Host':'example.test','Origin':self.config['origin'],'Cookie':'__Host-home='+'h'*43}
        with patch('dashboard.home_auth.identity_response',return_value=identity):
            self.assertEqual(self.client.get('/api/interaction/access',headers=headers).json()['actor_ref'],'human:telegram:100')
            identity['actor']['ref']='human:telegram:101'
            self.assertEqual(self.client.get('/api/interaction/access',headers=headers).status_code,403)
        for mutation in [{'surface_parent':'https://evil.test'},{'surface_visit':'not-uuid'},{'client':'other'},{'surface':'other'}]:
            refused=self.client.get('/',params={**query,**mutation})
            self.assertEqual(refused.status_code,400)
            self.assertNotIn('https://world.test',refused.headers['content-security-policy'])

    def test_parent_configuration_is_bounded_and_exact(self):
        for origin in ['*','http://world.test','https://world.test/path','https://user@world.test','https://world.test#x','https://world.test/','https://world.test;bad']:
            with self.assertRaises(ValueError):parent_origins({'conversation_surface':{'parent_origins':[origin]}})
        self.assertEqual(parent_origins({}),())


if __name__=='__main__':
    import unittest
    unittest.main()
