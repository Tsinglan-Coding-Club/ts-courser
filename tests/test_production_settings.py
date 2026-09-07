import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPORT = 'import ts_courser.settings_production'


class ProductionSettingsFailClosedTests(unittest.TestCase):
    def run_import(self, **updates):
        environment = os.environ.copy()
        environment.pop('DJANGO_SECRET_KEY', None)
        environment.pop('DJANGO_ALLOWED_HOSTS', None)
        environment.update(updates)
        return subprocess.run(
            [sys.executable, '-c', IMPORT],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )

    def test_missing_secret_fails_closed(self):
        result = self.run_import(DJANGO_ALLOWED_HOSTS='example.com')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY must be set', result.stderr)

    def test_short_secret_fails_closed(self):
        result = self.run_import(
            DJANGO_SECRET_KEY='too-short', DJANGO_ALLOWED_HOSTS='example.com'
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('long, unique production secret', result.stderr)

    def test_wildcard_or_empty_hosts_fail_closed(self):
        secret = 'production-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz'
        for hosts in ('*', ',', ' , '):
            with self.subTest(hosts=hosts):
                result = self.run_import(
                    DJANGO_SECRET_KEY=secret, DJANGO_ALLOWED_HOSTS=hosts
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('explicit hosts', result.stderr)


if __name__ == '__main__':
    unittest.main()
