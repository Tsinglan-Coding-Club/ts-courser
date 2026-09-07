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
        for name in (
            'DJANGO_SECRET_KEY', 'DJANGO_ALLOWED_HOSTS', 'MS_ENTRA_TENANT_ID',
            'MS_ENTRA_CLIENT_ID', 'MS_ENTRA_CLIENT_SECRET',
            'MS_ENTRA_SCHOOL_DOMAIN', 'MS_ENTRA_REDIRECT_URI',
        ):
            environment.pop(name, None)
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

    def test_missing_entra_secret_fails_closed(self):
        result = self.run_import(
            DJANGO_SECRET_KEY='production-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz',
            DJANGO_ALLOWED_HOSTS='courser.tsinglan.top',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MS_ENTRA_TENANT_ID must be set', result.stderr)

    def test_valid_school_entra_configuration_loads(self):
        result = self.run_import(
            DJANGO_SECRET_KEY='production-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz',
            DJANGO_ALLOWED_HOSTS='courser.tsinglan.top',
            MS_ENTRA_TENANT_ID='7222912a-435d-423b-b22b-74b909c3bf8b',
            MS_ENTRA_CLIENT_ID='5910709e-99db-4cc0-9468-88497aa32f23',
            MS_ENTRA_CLIENT_SECRET='test-only-secret',
            MS_ENTRA_SCHOOL_DOMAIN='tsinglan.org',
            MS_ENTRA_REDIRECT_URI=(
                'https://courser.tsinglan.top/accounts/microsoft/callback/'
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_well_formed_school_tenant_fails_closed(self):
        result = self.run_import(
            DJANGO_SECRET_KEY='production-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz',
            DJANGO_ALLOWED_HOSTS='courser.tsinglan.top',
            MS_ENTRA_TENANT_ID='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            MS_ENTRA_CLIENT_ID='5910709e-99db-4cc0-9468-88497aa32f23',
            MS_ENTRA_CLIENT_SECRET='test-only-secret',
            MS_ENTRA_SCHOOL_DOMAIN='tsinglan.org',
            MS_ENTRA_REDIRECT_URI=(
                'https://courser.tsinglan.top/accounts/microsoft/callback/'
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not match the school tenant', result.stderr)


if __name__ == '__main__':
    unittest.main()
