from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .icons import section_icon_catalog, section_icon_choices, validate_section_icon


class SectionIconCatalogTests(SimpleTestCase):
    def test_catalog_icons_resolve_to_installed_static_files(self):
        catalog = section_icon_catalog()
        self.assertIn('devicon:python:original', catalog)
        self.assertIn('heroicons:24-outline:academic-cap', catalog)
        self.assertIn('heroicons:24-solid:academic-cap', catalog)
        for icon in catalog.values():
            with self.subTest(icon=icon['name']):
                self.assertIsNotNone(finders.find(icon['path']))
                self.assertLessEqual(len(icon['name']), 128)

    def test_only_installed_icon_references_are_accepted(self):
        for value in ('🐍', '👩🏽‍💻', '', 'devicon:python:original', 'heroicons:24-solid:academic-cap'):
            validate_section_icon(value)
        for value in ('x' * 33, 'devicon:missing:original', 'heroicons:../../secrets', 'devicon:python:../../secrets'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_section_icon(value)

    def test_devicon_browse_choice_is_consistent_across_tool_variants(self):
        choices = section_icon_choices()
        for tool, browse in (('python', True), ('aerospike', False)):
            variants = [icon for icon in choices if icon['name'].startswith(f'devicon:{tool}:')]
            self.assertGreater(len(variants), 1)
            self.assertEqual({icon['browse'] for icon in variants}, {browse})
