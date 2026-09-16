import hashlib
import json
import re
import unittest

from vio_mapper.config import PROJECT_ROOT, RULES_DIR, vin_rules_path
from vio_mapper.vin_decoder import decode_nz_vin
from vio_mapper.vin_evidence import vin_context

VIN_RULES = json.loads(vin_rules_path().read_text())


class NzVinTests(unittest.TestCase):
    def test_official_legacy_example(self):
        result = decode_nz_vin("7A8DH1E0701123456")
        self.assertEqual(result.fields["make_code"], "DH")
        self.assertEqual(result.fields["model"], "Bluebird")
        self.assertEqual(result.fields["vehicle_type_code"], "07")
        self.assertEqual(result.fields["vin_assignment_year_code"], "01")

    def test_official_current_example(self):
        result = decode_nz_vin("7AT0DH1EX09123456")
        self.assertEqual(result.fields["make"], "Nissan")
        self.assertEqual(result.fields["model_code"], "1E")
        self.assertEqual(result.fields["filler"], "X")
        self.assertIsNone(result.fields["vehicle_type_code"])

    def test_user_example_does_not_invent_model_or_year(self):
        result = decode_nz_vin("7AT0DH6LX22", allow_prefix=True)
        self.assertEqual(result.fields["model_code"], "6L")
        self.assertEqual(result.fields["vin_assignment_year_code"], "22")
        self.assertIsNone(result.fields["model"])
        self.assertIsNone(result.fields["serial_component"])
        self.assertTrue(result.is_prefix)

    def test_prefix_does_not_shift_fields(self):
        for vin in ("7A8DH1E0701123456", "7AT0DH1EX09123456"):
            full = decode_nz_vin(vin)
            partial = decode_nz_vin(vin[:11], allow_prefix=True)
            for key in full.fields.keys() - {"serial_component"}:
                self.assertEqual(full.fields[key], partial.fields[key])

    def test_factory_vins_are_not_nzta_or_universal_year_decodes(self):
        for vin in ("SAJAC41E42NA26658", "WDD2040422R123456", "7A123456789012345"):
            result = decode_nz_vin(vin)
            self.assertEqual(result.status, "manufacturer_data_required")
            self.assertEqual(result.fields["wmi"], vin[:3])
            self.assertNotIn("model_year", result.fields)
            self.assertEqual(result.fields["vehicle_identifier_section"], vin[9:])
            partial = decode_nz_vin(vin[:11], allow_prefix=True)
            self.assertIsNone(partial.fields["vehicle_identifier_section"])

    def test_ford_ranger_uses_only_the_mirrored_official_approval(self):
        for vin11 in ('MPBUMFF60KX', 'MPBUMFF60LX'):
            with self.subTest(vin11=vin11):
                result = decode_nz_vin(vin11, allow_prefix=True)
                self.assertEqual(result.profile, 'ford_ranger_thailand')
                self.assertEqual(result.status, 'partial_decode')
                self.assertEqual(set(result.sources), {'ford_approval'})
                resolved = {segment['key']: segment['meaning'] for segment in result.segments
                            if segment['meaning'] is not None}
                self.assertEqual(resolved, {
                    'manufacturer_identifier': 'Ford Thailand',
                    'constant': 'Fixed constant; not check digit',
                })
                year = next(segment for segment in result.segments
                            if segment['key'] == 'production_or_model_year_code')
                self.assertEqual(year['raw'], vin11[9])
                self.assertIsNone(year['meaning'])

    def test_colorado_supporting_evidence_does_not_overdecode_unknown_positions(self):
        result = decode_nz_vin('MMU143DK0LH', allow_prefix=True)
        self.assertEqual(result.profile, 'holden_colorado_observed')
        self.assertEqual(result.status, 'partial_decode')
        resolved = {segment['key']: segment['meaning'] for segment in result.segments
                    if segment['meaning'] is not None}
        self.assertEqual(resolved, {
            'wmi': 'Holden Colorado RG approval family',
            'model_variant_code': 'Colorado RG 2.8 turbo-diesel 4x4 variant family (U143DK)',
        })
        self.assertEqual(
            [segment['raw'] for segment in result.segments if segment['meaning'] is None],
            ['0', 'L', 'H'],
        )
        self.assertTrue(all(segment['status'] == 'inferred' for segment in result.segments
                            if segment['meaning'] is not None))

    def test_tucson_sources_ground_applicability_but_not_engine_character(self):
        result = decode_nz_vin('TMAJ381ASLJ', allow_prefix=True)
        self.assertEqual(result.profile, 'hyundai_tucson_tl')
        self.assertIn('tucson_tle_cz', result.sources)
        self.assertIn('tucson_hyundai_spec', result.sources)
        engine = next(segment for segment in result.segments if segment['key'] == 'engine')
        self.assertEqual(engine['raw'], 'A')
        self.assertIsNone(engine['meaning'])
        self.assertEqual(engine['status'], 'unresolved')

    def test_new_supporting_profiles_do_not_become_actionable_kType_evidence(self):
        colorado = vin_context('MMU143DK0LH', 'HOLDEN', 'COLORADO')
        tucson = vin_context('TMAJ381ASLJ', 'HYUNDAI', 'TUCSON')
        self.assertEqual(colorado['facts'], {})
        self.assertEqual(tucson['facts'], {})
        self.assertIn('No reviewed actionable adapter', colorado['note'])
        self.assertIn('No reviewed actionable adapter', tucson['note'])

    def test_unknown_codes_and_leading_zeroes(self):
        result = decode_nz_vin("7ATZZZ99X22000001")
        self.assertIsNone(result.fields["make"])
        self.assertIsNone(result.fields["model"])
        self.assertEqual(result.fields["serial_component"], "000001")

    def test_normalization(self):
        self.assertEqual(decode_nz_vin(" 7at0dh1ex09123456\n").vin, "7AT0DH1EX09123456")

    def test_invalid_inputs(self):
        # Every one of these breaks something NZTA or ISO 3779 actually states:
        # the length, the excluded letters, or the always-X filler at position 9.
        for value in ("", "7AT0DH6LX22", "7AT0DH6LX221234567",
                      "7ATODH6LX22123456", "7AT0DH6L022123456",
                      "7AT0DH6LX22 23456", "7AT0DH6LX22_23456"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_nz_vin(value)
        with self.assertRaises(TypeError):
            decode_nz_vin(None)


if __name__ == "__main__":
    unittest.main()


class LayoutGrounding(unittest.TestCase):
    """The NZTA layouts are published as two pictures, and nothing else.

    The page's text states no character position, so every position meaning in
    the rules is a reading of an image. That makes the stored transcription the
    only thing a reviewer can check a claim against, and these tests keep the
    two in step: a redrawn diagram fails the checksum, and a quietly edited
    position fails the comparison.
    """

    TRANSCRIPTION = PROJECT_ROOT / 'docs/rule-sources/nz/nzta_vin_layouts.md'

    @staticmethod
    def _rows(heading: str) -> list[tuple[int, int, str]]:
        """(start, end, box text) for every row of one transcribed diagram."""
        text = LayoutGrounding.TRANSCRIPTION.read_text()
        section = text.split(heading, 1)[1].split('\n## ', 1)[0]
        rows = []
        for line in section.split('\n'):
            match = re.match(r'\|\s*(\d+)(?:[-\u2013](\d+))?\s*\|\s*`([^`]+)`', line)
            if match:
                start, end, box = match.groups()
                rows.append((int(start), int(end or start), box))
        return rows

    def test_the_official_source_is_pinned_like_every_other_official_source(self):
        """A citation to a picture is worth nothing without the picture pinned."""
        source = VIN_RULES['sources']['nzta']
        for field in ('title', 'url', 'scope', 'accessed', 'local_copy', 'sha256'):
            self.assertTrue(source.get(field), f'nzta source is missing {field}')

    def test_every_stored_copy_matches_its_checksum(self):
        for key, source in VIN_RULES['sources'].items():
            if 'local_copy' not in source:
                continue  # an OEM page this project may not redistribute
            with self.subTest(source=key):
                path = PROJECT_ROOT / source['local_copy']
                self.assertTrue(path.exists(), f'{key}: {path} is missing')
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source['sha256'],
                                 f'{key}: {path} no longer matches its recorded checksum')

    def test_the_recorded_positions_are_the_ones_the_diagrams_show(self):
        """Position boundaries, compared against the transcribed boxes."""
        for profile_id, heading in (('nzta_7A8', '## Diagram 1'), ('nzta_7AT', '## Diagram 2')):
            profile = next(p for p in VIN_RULES['profiles'] if p['id'] == profile_id)
            boxes = self._rows(heading)
            # The rules describe the 11-character prefix the register publishes;
            # the diagram's last box is the 12-17 serial, which no segment reads.
            self.assertEqual([(segment['start'], segment['end']) for segment in profile['segments']],
                             [(start, end) for start, end, _ in boxes if end <= 11],
                             f'{profile_id}: recorded positions differ from the diagram')

    def test_every_value_read_off_a_diagram_is_a_box_it_prints(self):
        """A code grounded on the picture must be one the picture actually shows.

        Only segments whose sole source is the diagram are held to this. A
        segment that cites a second source may record what that source states --
        checked against it in the next test -- which is how the vehicle type
        codes come from VIRM Table 2-2-1 rather than from the one example the
        diagram prints.
        """
        for profile_id, heading in (('nzta_7A8', '## Diagram 1'), ('nzta_7AT', '## Diagram 2')):
            profile = next(p for p in VIN_RULES['profiles'] if p['id'] == profile_id)
            boxes = {(start, end): box for start, end, box in self._rows(heading)}
            for segment in profile['segments']:
                if segment['source_ids'] != ['nzta']:
                    continue
                for code in segment.get('values', {}):
                    with self.subTest(profile=profile_id, segment=segment['key'], code=code):
                        self.assertEqual(code, boxes[(segment['start'], segment['end'])],
                                         'recorded code is not the one the diagram prints here')

    def test_the_vehicle_type_codes_match_the_stored_virm_table_verbatim(self):
        """Positions 8-9 carry a LANDATA code, and VIRM Table 2-2-1 publishes the list.

        Compared against the stored transcription rather than a written claim, so
        a typo or a quietly edited type name fails here instead of being
        discovered by whoever next checks a decoded VIN.
        """
        import re as regex

        source = VIN_RULES['sources']['nzta_virm_attributes']
        stored = (PROJECT_ROOT / source['local_copy']).read_text()
        section = stored.split('## Table 2-2-1.', 1)[1].split('\n## ', 1)[0]
        published = dict(regex.findall(r'\|\s*(\d{2})\s*\|\s*([^|]+?)\s*\|', section))
        self.assertEqual(len(published), 14, 'the stored table should hold 14 codes')
        profile = next(p for p in VIN_RULES['profiles'] if p['id'] == 'nzta_7A8')
        segment = next(s for s in profile['segments'] if s['key'] == 'vehicle_type_code')
        self.assertEqual(segment['values'], published)
        self.assertIn('nzta_virm_attributes', segment['source_ids'])
        self.assertEqual(published['07'], 'Passenger cars and vans')  # the diagram's own example

    def test_the_type_codes_agree_with_the_register_vocabulary(self):
        """Two files record the same LANDATA codes; neither may drift from the other.

        registries/nz.json keys its vehicle types by the wording the register
        emits and carries the code alongside; the VIN rules key by the code. The
        spellings differ by design -- the register writes PASSENGER CAR/VAN where
        VIRM writes Passenger cars and vans -- so only the codes are compared,
        which is the part that must not disagree.
        """
        registry = json.loads((RULES_DIR / 'registries/nz.json').read_text())[
            'registry_vehicle_types']
        profile = next(p for p in VIN_RULES['profiles'] if p['id'] == 'nzta_7A8')
        segment = next(s for s in profile['segments'] if s['key'] == 'vehicle_type_code')
        recorded = {entry['code'] for entry in registry['values'].values()}
        self.assertLessEqual(recorded, set(segment['values']),
                             'the register records a type code the VIN rules do not')
        # Code 23 is published by Table 2-2-1 and absent from Table 2-2-8, so the
        # register vocabulary has no wording for it. That asymmetry is expected;
        # what would not be is a code in neither direction.
        self.assertEqual(set(segment['values']) - recorded, {'23'})

    def test_no_rule_is_enforced_that_the_source_does_not_state(self):
        """NZTA states no format for the year code or the serial, so neither does this.

        Both were once rejected unless numeric, inferred from a single printed
        example each. Refusing a VIN the publisher never forbade is this
        project's judgement dressed as the register's rule, and it would refuse
        a row the register may legitimately carry. The fields are read as
        written instead; a code with no recorded meaning resolves to nothing,
        which is what an unknown is supposed to cost.
        """
        for profile in VIN_RULES['profiles']:
            if not profile['id'].startswith('nzta'):
                continue
            with self.subTest(profile=profile['id']):
                unconstrained = profile['unconstrained_fields']
                self.assertIn('vin_assignment_year_code', unconstrained)
                self.assertIn('serial_component', unconstrained)
        letters = decode_nz_vin('7AT0DH1EXA9123456')
        self.assertEqual(letters.fields['vin_assignment_year_code'], 'A9')
        self.assertIn(letters.status, ('structure_decoded', 'documented_prefix'))
        serial = decode_nz_vin('7AT0DH1EX0912345A')
        self.assertEqual(serial.fields['serial_component'], '12345A')
        # Still rejected, because the publisher does state this one.
        with self.assertRaises(ValueError):
            decode_nz_vin('7AT0DH1EY09123456')  # position 9 is not the stated X
