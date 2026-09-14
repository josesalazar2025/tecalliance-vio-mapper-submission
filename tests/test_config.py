"""Policy and rule tables: an unusable setting must fail before any row is read."""
import unittest

from vio_mapper.config import (VERSION_CRITERIA, Policy, core_conflict, registry_file, score_rules,
                               submodel_rules, vocabularies)


class PolicyValidationTests(unittest.TestCase):
    def test_a_valid_policy_passes(self):
        Policy().validate()

    def test_each_unusable_setting_names_itself(self):
        cases = [
            ({'power_tolerance_pct': float('nan')}, 'Power tolerance'),
            ({'power_tolerance_pct': -1}, 'Power tolerance'),
            ({'power_tolerance_pct': 101}, 'Power tolerance'),
            ({'accept_score': 101}, 'accept_score'),
            ({'min_margin': float('inf')}, 'min_margin'),
            ({'year_mode': 'strict'}, 'year_mode'),
            ({'evidence': 'some'}, 'evidence retention'),
            ({'year_weight': 6}, 'year_weight'),
        ]
        for overrides, message in cases:
            with self.subTest(**overrides), self.assertRaisesRegex(ValueError, message):
                Policy(**overrides).validate()

    def test_the_year_weight_ceiling_comes_from_the_rule_file(self):
        Policy(year_weight=score_rules()['group_caps']['temporal']).validate()


class RuleTableTests(unittest.TestCase):
    def test_tables_are_loaded_once_and_shared(self):
        """The matcher reads these per candidate; re-reading the file per call would dominate."""
        self.assertIs(vocabularies(), vocabularies())
        self.assertIs(score_rules(), score_rules())

    def test_fuel_and_drive_vocabularies_cover_both_catalogues(self):
        """One map per catalogue, both landing in the same neutral categories."""
        registry = vocabularies()['registry_fuel']
        catalogue = vocabularies()['catalogue_fuel']
        self.assertEqual(registry['PETROL'], 'petrol')
        self.assertEqual(catalogue['PETROL'], 'petrol')
        self.assertEqual(catalogue['PETROL/ELECTRIC'], 'petrol_hybrid')
        self.assertEqual(registry['PETROL HYBRID'], 'petrol_hybrid')
        # Gas blends stay distinct from the reference's combined Petrol/LPG.
        self.assertNotEqual(registry['LPG'],
                            catalogue['PETROL/LIQUIFIED PETROLEUM GAS (LPG)'])
        # Neither side names the other's labels.
        self.assertNotIn('PETROL/ELECTRIC', registry)
        self.assertNotIn('PETROL HYBRID', catalogue)
        self.assertEqual(set(vocabularies()['reference_drive_system'].values()),
                         {'awd', 'fwd', 'rwd'})

    def test_cab_wording_carries_no_body_restriction(self):
        """Cab tokens are parsed for the audit trail and decide nothing.

        The exclusion they used to carry (a single cab cannot be a PICKUP) rested
        on a Holden model-lineup specification that is not an NZTA, TecAlliance or
        RDM source, and the RDM has no cab column to reground it against.
        """
        self.assertNotIn('cab_bodies', vocabularies())
        self.assertNotIn('permitted_bodies', registry_file()['cab_configurations'])

    def test_every_submodel_profile_is_keyed_by_make_and_model(self):
        for key, (identifier, trims) in submodel_rules()['profiles'].items():
            self.assertEqual(len(key), 2)
            self.assertTrue(identifier.islower())
            self.assertIsInstance(trims, set)

    def test_score_weights_and_caps_are_consistent(self):
        rules = score_rules()
        for group, members in rules['group_members'].items():
            total = sum(rules['field_weights'][field] for field in members)
            self.assertGreaterEqual(total, rules['group_caps'][group],
                                    f'{group} cap can never be reached')
        # The caps define the scale; there is no nominal 100. Policy.validate
        # bounds the thresholds by this sum, so the two must agree.
        self.assertEqual(sum(rules['group_caps'].values()), 75)

    def test_no_gate_field_is_scored(self):
        """A prerequisite cannot distinguish candidates that all satisfy it."""
        rules = score_rules()
        gates = set(rules['gate_fields'])
        self.assertEqual(gates & set(rules['field_weights']), set())
        for group, members in rules['group_members'].items():
            self.assertEqual(gates & set(members), set(), f'{group} contains a gate field')

    def test_no_scored_field_is_available_to_only_some_makes(self):
        """A scoring field earnable by one badge and not another is not a rule.

        `variant` was exactly that: evidence.candidate_evidence returns
        'not comparable' for every make but MERCEDES-BENZ, so four of the five
        makes in the supplied data could never earn its 10 points however well
        evidenced they were. It is compared and vetoed like any specification;
        it simply earns nothing.
        """
        from vio_mapper.config import COMPARED_FIELDS
        rules = score_rules()
        unscored = set(COMPARED_FIELDS) - set(rules['field_weights'])
        self.assertIn('variant', unscored)
        self.assertEqual(unscored, set(rules['gate_fields']) | {'variant'})

    def test_no_cap_discards_evidence_from_any_group(self):
        """Every cap must equal its members' sum, so no cap can discard evidence.

        A cap below the sum says the observations are related and must not
        accumulate. That claim has to be true of every member. It was asserted of
        drive, body and variant as "three readings of one configuration" and was
        wrong on the sources: Regulation (EU) 2018/858 Annex I 1.2.1 makes
        bodywork (a) and powered axles (d) separate variant criteria, so drive and
        body are independent. The genuinely redundant member, the Mercedes type
        designation, is unscored instead, which leaves every cap exact.
        """
        rules = score_rules()
        for group, members in rules['group_members'].items():
            with self.subTest(group=group):
                self.assertEqual(rules['group_caps'][group],
                                 sum(rules['field_weights'][f] for f in members))

    def test_every_scored_field_declares_an_annex_i_tier(self):
        """A weight with no declared tier cannot be checked against the ordering."""
        tiers = score_rules()['criterion_tier']
        for field in score_rules()['field_weights']:
            with self.subTest(field=field):
                self.assertIn(field, tiers)
                self.assertIn(tiers[field], ('version', 'variant'))

    def test_no_variant_criterion_outweighs_a_version_criterion(self):
        """The one ordering the sources settle, now actually enforced.

        Regulation (EU) 2018/858 Annex I makes a version criterion the finer
        discriminator: it separates two vehicles a variant criterion would group
        together. Nothing ranks the criteria within a tier, and nothing licenses
        adding them at all, so this is the only constraint the Regulation puts on
        the weights -- and `scoring.json` claimed it was "enforced by
        tests/test_config.py" while no test read `criterion_tier` at all. `drive`
        carried 15, equal to `power`, until that was corrected by lowering drive.
        """
        rules = score_rules()
        tiers, weights = rules['criterion_tier'], rules['field_weights']
        version = [weights[f] for f in weights if tiers[f] == 'version']
        variant = [weights[f] for f in weights if tiers[f] == 'variant']
        self.assertTrue(version and variant, 'both tiers must carry a scored field')
        self.assertLessEqual(max(variant), min(version))

    def test_the_version_criteria_constant_matches_the_tier_table(self):
        """One source for the tier split, so the constant cannot drift from it.

        `complete_version_evidence` reads the table for the variant tier and the
        constant for the version tier; if they disagreed, the uniqueness route
        would demand one set and credit another.
        """
        tiers = score_rules()['criterion_tier']
        self.assertEqual(set(VERSION_CRITERIA),
                         {field for field, tier in tiers.items() if tier == 'version'})

    def test_the_unscored_gates_are_declared_version_criteria(self):
        """They are unscored because the floor already requires them, not
        because they individuate nothing: Annex I 1.3.1(b) and (d)."""
        tiers = score_rules()['criterion_tier']
        for gate in score_rules()['gate_fields']:
            with self.subTest(gate=gate):
                self.assertEqual(tiers.get(gate), 'version')

    def test_related_observations_collapse_onto_one_specification(self):
        self.assertEqual(core_conflict('submodel_capacity'), 'capacity')
        self.assertEqual(core_conflict('vin_drive'), 'drive')
        # An unlisted field reports under its own name rather than vanishing.
        self.assertEqual(core_conflict('something_new'), 'something_new')


if __name__ == '__main__':
    unittest.main()


class KeywordOnlyConstructionTests(unittest.TestCase):
    """Optional dataclass tails must be keyword-only.

    Appending a field to a dataclass whose tail is positional silently changes
    what an existing positional argument means. That happened here: inserting a
    scope field before `proposal` made two call sites pass a dict as the scope,
    and it surfaced far away as an unhashable-type error in a groupby rather
    than at the call site. These tests keep the tails closed.
    """

    def test_policy_accepts_no_positional_arguments(self):
        from vio_mapper.config import Policy
        with self.assertRaises(TypeError):
            Policy(2.0)
        Policy(power_tolerance_pct=2.0)  # the keyword form still works

    def test_outcome_keeps_its_optional_tail_keyword_only(self):
        from vio_mapper.config import CONFLICT, SELF_CONTRADICTION
        from vio_mapper.decision import Outcome
        # The four leading fields stay positional: every branch supplies them.
        outcome = Outcome(CONFLICT, None, 'reason', SELF_CONTRADICTION)
        self.assertEqual((outcome.fields, outcome.fields_scope, outcome.proposal), ('', '', None))
        with self.assertRaises(TypeError):
            Outcome(CONFLICT, None, 'reason', SELF_CONTRADICTION, 'drive')
        self.assertEqual(Outcome(CONFLICT, None, 'reason', SELF_CONTRADICTION,
                                 fields='drive').fields, 'drive')

    def test_anchor_state_accepts_no_positional_arguments(self):
        from vio_mapper.decision import AnchorState
        with self.assertRaises(TypeError):
            AnchorState({})
        self.assertFalse(AnchorState().has_identifiers)

    def test_vin_decode_keeps_its_decoded_tail_keyword_only(self):
        from vio_mapper.vin_decoder import VinDecode
        decoded = VinDecode('JN1JBAT32A0', True, 'manufacturer', 'structure_decoded', {}, ())
        self.assertIsNone(decoded.profile)
        with self.assertRaises(TypeError):
            VinDecode('JN1JBAT32A0', True, 'manufacturer', 'structure_decoded', {}, (), 'url')
