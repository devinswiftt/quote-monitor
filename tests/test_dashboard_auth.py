import unittest
from hk_quote.dashboard import access_allowed

class DashboardAccessTests(unittest.TestCase):
 def test_optional_password_keeps_cookie_auth_available(self):
  for cookie in ('', 'hk_session=wrong', 'malformed cookie'):
   self.assertTrue(access_allowed(False,cookie,'secret'))
   self.assertFalse(access_allowed(True,cookie,'secret'))
  self.assertTrue(access_allowed(True,'other=1; hk_session=secret','secret'))
  self.assertFalse(access_allowed(True,'hk_session=secret','new-session'))
