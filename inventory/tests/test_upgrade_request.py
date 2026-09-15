"""The web "Upgrade now" button writes a marker; the host agent applies it.

The web process can't rebuild its own container, so request_upgrade only drops a file
into the bind-mounted data dir (parent of MEDIA_ROOT) and read_upgrade_result reads
whatever the host agent wrote back. These tests pin that hand-off without touching a
real host.
"""
import os
import tempfile

from django.conf import settings
from django.test import TestCase, override_settings

from inventory import updates


@override_settings(MEDIA_ROOT=os.path.join(tempfile.mkdtemp(), "media"))
class UpgradeRequestTests(TestCase):
    def test_request_writes_a_marker_in_the_data_dir(self):
        path = updates.request_upgrade()
        self.assertTrue(os.path.exists(path))
        self.assertEqual(path, os.path.join(os.path.dirname(settings.MEDIA_ROOT), "upgrade-request"))

    def test_result_is_empty_before_the_host_runs(self):
        updates.request_upgrade()
        self.assertEqual(updates.read_upgrade_result(), "")

    def test_result_is_read_once_the_host_writes_it(self):
        with open(os.path.join(os.path.dirname(settings.MEDIA_ROOT), "upgrade-result"), "w", encoding="utf-8") as f:
            f.write("OK: upgraded")
        self.assertEqual(updates.read_upgrade_result(), "OK: upgraded")
