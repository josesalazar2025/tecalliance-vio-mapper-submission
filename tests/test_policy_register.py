"""Every setting that can change an acceptance must be declared, with its owner.

The register exists because the project applied a principle unevenly. A power
tolerance was held to be the data owner's call and given a documented rationale,
a CLI flag and a per-row flag in `assumptions_used`; the acceptance threshold,
which refused twenty vehicles on a value with no derivation behind it at all,
sat in the dataclass as a bare `65.0`.

These tests make that asymmetry impossible to reintroduce. A new Policy field is
a test failure until it is declared, and a declared default that drifts from the
real one is a test failure too -- the register documents the running system or it
documents nothing.
"""
from __future__ import annotations

import dataclasses
import unittest

from vio_mapper.config import Policy, owner_decisions, policy_decisions, score_rules

VALID_OWNERS = {'data_owner', 'engineering'}
VALID_BASES = {'derived', 'judgement', 'unfitted'}
# Declared but not a Policy field: the weights live in scoring.json.
NOT_A_POLICY_FIELD = {'field_weights'}


class PolicyRegister(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.register = policy_decisions()
        cls.fields = {field.name: field for field in dataclasses.fields(Policy)}

    def test_every_policy_field_is_declared(self):
        """The guard: a new tunable cannot arrive as an undocumented default."""
        undeclared = set(self.fields) - set(self.register)
        self.assertEqual(undeclared, set(), f'undeclared Policy fields: {sorted(undeclared)}')

    def test_nothing_is_declared_that_does_not_exist(self):
        unknown = set(self.register) - set(self.fields) - NOT_A_POLICY_FIELD
        self.assertEqual(unknown, set(), f'declared but not a setting: {sorted(unknown)}')

    def test_declared_defaults_match_the_running_defaults(self):
        """A register that documents values the code does not use documents nothing."""
        for name, entry in self.register.items():
            if name in NOT_A_POLICY_FIELD:
                continue
            with self.subTest(setting=name):
                self.assertEqual(entry['default'], self.fields[name].default)

    def test_the_weights_entry_points_at_the_file_that_holds_them(self):
        entry = self.register['field_weights']
        self.assertEqual(entry['default'], 'vio_mapper/rules/scoring.json')
        self.assertTrue(score_rules()['field_weights'])

    def test_every_entry_declares_an_owner_a_basis_and_a_rationale(self):
        for name, entry in self.register.items():
            with self.subTest(setting=name):
                self.assertIn(entry['decided_by'], VALID_OWNERS)
                self.assertIn(entry['basis'], VALID_BASES)
                self.assertIsInstance(entry['affects_acceptance'], bool)
                self.assertGreater(len(entry['rationale']), 80,
                                   'a rationale a reviewer cannot act on is not a rationale')

    def test_the_settings_that_are_the_owners_call_are_the_expected_ones(self):
        """Pinned deliberately: moving a setting between owners is a policy change.

        It should be a visible diff in this test and in the register, never a
        quiet edit to one JSON field.
        """
        self.assertEqual(set(owner_decisions()),
                         {'power_tolerance_pct', 'accept_score', 'min_margin',
                          'year_mode', 'year_weight', 'field_weights', 'selection'})

    def test_a_setting_that_cannot_change_an_acceptance_says_so(self):
        for name in ('power_triage_kw', 'evidence', 'reuse_identical_rows'):
            with self.subTest(setting=name):
                self.assertFalse(self.register[name]['affects_acceptance'])

    def test_declaring_a_setting_changes_no_outcome(self):
        """The register is documentation. It must not be reachable from a decision."""
        import vio_mapper.decision as decision
        import vio_mapper.evidence as evidence
        import vio_mapper.scoring as scoring
        for module in (decision, evidence, scoring):
            with self.subTest(module=module.__name__):
                self.assertNotIn('policy_decisions', dir(module))

    def test_every_advertised_cli_flag_exists(self):
        from vio_mapper.cli import build_parser
        option_strings = {option for action in build_parser()._actions
                          for option in action.option_strings}
        advertised = {entry['cli_flag'] for entry in self.register.values()
                      if entry['cli_flag'] is not None}
        self.assertLessEqual(advertised, option_strings)


if __name__ == '__main__':
    unittest.main()
