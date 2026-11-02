"""User-visible intent regressions against isolated local-demo ledgers.

These tests exercise the public service boundary rather than matching a parser's
implementation. No test opens an existing runtime database or sends HTTP traffic
to a running demo service.
"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from first_agent.service import AgentService


class IntentRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = [1800000000.0]
        self.service = AgentService(
            Path(self.temp.name) / 'intent-regression.sqlite3',
            clock=lambda: self.now[0],
        )
        self.sequence = 0
        self.new_session()

    def new_session(self, *, trade=True):
        self.sid = self.service.create_session()
        result = self.call('rpc', {
            'method': 'authorize',
            'args': [{'read': True, 'subscriptions': True, 'trade': trade}],
        })
        self.assertIsNone(result['error'], result)
        self.initial_balance = self.state()['available']

    def call(self, action, args=None, *, key=None):
        self.sequence += 1
        return self.service.call(
            self.sid, action, args,
            key or f'intent-regression-{self.sequence}',
        )

    def chat(self, message, **extra):
        return self.call('chat', {'message': message, **extra})

    def state(self):
        response = self.call('snapshot')
        self.assertIsNone(response['error'], response)
        return response['data']['state']

    def operation(self, operation_id):
        response = self.call('operation', {'operation_id': operation_id})
        self.assertIsNone(response['error'], response)
        return response['data']

    def assert_preview(self, response, *, name='小王', amount=80000):
        self.assertIsNone(response['error'], response)
        self.assertEqual(response['status'], 'awaiting_confirmation', response)
        preview = response['data']['preview']
        self.assertEqual(preview['beneficiary_name'], name)
        self.assertEqual(preview['amount'], amount)
        self.assertEqual(preview['status'], 'awaiting_confirmation')
        self.assertEqual(self.state()['available'], self.initial_balance)
        return preview

    def assert_no_preview_or_money_change(self, response):
        self.assertNotEqual(response['status'], 'awaiting_confirmation', response)
        self.assertFalse((response.get('data') or {}).get('preview'), response)
        state = self.state()
        self.assertEqual(state['available'], self.initial_balance)
        self.assertEqual(state['transfer_ops'], [], state['transfer_ops'])
        self.assertFalse(any(
            op.get('type') == 'transfer' for op in state['operations']
        ), state['operations'])

    def test_core_prefix_whitespace_and_fullwidth_forms(self):
        phrases = [
            '给小王转账800元',
            '要给小王转账800元',
            '我要给小王转账800元',
            '请帮我给小王转账800元',
            '给 小王 转账 800 元。',
            '给小王转账８００元',
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.new_session()
                self.assert_preview(self.chat(phrase))

    def test_supported_word_order_and_units(self):
        for phrase in ['转账800元给小王', '给小王转800块', '转给小王800元']:
            with self.subTest(phrase=phrase):
                self.new_session()
                self.assert_preview(self.chat(phrase))

    def test_legacy_allowed_recipients_remain_supported(self):
        for name in ['张三', '李四']:
            with self.subTest(name=name):
                self.new_session()
                self.assert_preview(self.chat(f'给{name}转账800元'), name=name)

    def test_legacy_non_whitelisted_recipient_stays_blocked(self):
        response = self.chat('给王五转账800元')
        self.assertEqual(response['status'], 'rejected', response)
        self.assertEqual(response['error']['code'], 'POLICY_DENIED', response)
        self.assert_no_preview_or_money_change(response)

    def test_chat_and_form_use_same_recipient_identity(self):
        chat_preview = self.assert_preview(self.chat('给小王转账800元'))
        contacts = self.state()['contacts']
        wang = [contact for contact in contacts if contact['name'] == '小王']
        self.assertEqual(len(wang), 1, wang)
        self.assertEqual(wang[0]['id'], 'R-WANG')
        self.new_session()
        result = self.call('rpc', {
            'method': 'propose',
            'args': ['transfer', 'R-WANG', 80000, {'cardId': 'CARD-DEBIT'}],
        })
        self.assertIsNone(result['error'], result)
        self.assertEqual(result['data']['status'], 'awaiting_confirmation')
        self.assertEqual(result['data']['target'], chat_preview['target'])
        self.assertEqual(result['data']['amount'], chat_preview['amount'])
        self.assertEqual(self.state()['available'], self.initial_balance)

    def test_unknown_alias_is_preserved_not_matched_as_substring(self):
        for alias in ['小王子', '张三丰']:
            with self.subTest(alias=alias):
                self.new_session()
                response = self.chat(f'给{alias}转账800元')
                self.assertEqual(response['status'], 'needs_input', response)
                self.assertEqual(response['data']['reason_code'], 'RECIPIENT_NOT_FOUND')
                self.assertEqual(response['data']['candidate']['recipient_alias'], alias)
                self.assertEqual(response['data']['missing'], ['beneficiary_name'])
                self.assert_no_preview_or_money_change(response)

    def test_duplicate_recipient_requires_disambiguation(self):
        existing = next(
            record for record in self.service.recipient_records
            if record['name'] == '小王'
        )
        duplicate = deepcopy(existing)
        duplicate['beneficiary_id'] = 'R-WANG-SECOND'
        if 'id' in duplicate:
            duplicate['id'] = 'R-WANG-SECOND'
        self.service.recipient_records.append(duplicate)
        response = self.chat('给小王转账800元')
        self.assertEqual(response['status'], 'needs_input', response)
        self.assertEqual(response['data']['reason_code'], 'RECIPIENT_AMBIGUOUS')
        self.assert_no_preview_or_money_change(response)

    def test_decimal_amounts_keep_exact_minor_units(self):
        for text, minor in [('800.50', 80050), ('0.01', 1)]:
            with self.subTest(text=text):
                self.new_session()
                self.assert_preview(self.chat(f'给小王转账{text}元'), amount=minor)

    def test_invalid_numeric_tokens_cannot_become_positive_fragments(self):
        for text in ['-800', '0', '800.001', '1e3', '1,80', '800.']:
            with self.subTest(text=text):
                self.new_session()
                self.assert_no_preview_or_money_change(
                    self.chat(f'给小王转账{text}元')
                )

    def test_thousands_separator_is_whole_amount_or_rejected(self):
        response = self.chat('给小王转账1,800元')
        if response['status'] == 'awaiting_confirmation':
            self.assert_preview(response, amount=180000)
        else:
            self.assert_no_preview_or_money_change(response)

    def test_non_request_speech_acts_do_not_create_transfer(self):
        phrases = [
            '不要给小王转账800元',
            '给小王转账800元了吗？',
            '“给小王转账800元”这句话怎么解析？',
            '如果到账了再给小王转账800元',
            '明天再给小王转账800元',
            '给小王转账800元，别真的转',
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.new_session()
                self.assert_no_preview_or_money_change(self.chat(phrase))

    def test_multiple_or_ambiguous_requests_are_not_truncated(self):
        phrases = [
            '给小王转账800元，再给林晓转账200元',
            '给小王转账800元，再给林晓转账200美元',
            '给小王转账800元，再给陌生人转账200美元',
            '给小王转账800元，或者900元',
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.new_session()
                self.assert_no_preview_or_money_change(self.chat(phrase))

    def test_missing_amount_retains_recipient_and_only_asks_amount(self):
        response = self.chat('给小王转账')
        self.assertEqual(response['status'], 'needs_input', response)
        self.assertEqual(response['data']['missing'], ['amount_minor'])
        self.assertEqual(response['data']['candidate']['recipient_alias'], '小王')
        self.assertNotIn('收款人姓名及金额', response['data']['conclusion'])
        self.assert_preview(self.chat('800元'))

    def test_balance_query_can_interrupt_slot_clarification(self):
        self.assertEqual(self.chat('给小王转账')['status'], 'needs_input')
        response = self.chat('查余额')
        self.assertIsNone(response['error'], response)
        self.assertEqual(response['data']['intent'], 'accounts', response)
        self.assertIsNone(self.state().get('clarification'))
        self.assert_no_preview_or_money_change(self.chat('800元'))

    def test_negated_slot_reply_does_not_complete_old_transfer(self):
        self.assertEqual(self.chat('给小王转账')['status'], 'needs_input')
        self.assert_no_preview_or_money_change(self.chat('不要800元'))

    def test_amount_correction_invalidates_old_draft_and_confirmation(self):
        old = self.assert_preview(self.chat('给小王转账800元'))
        changed = self.chat('改成900元')
        self.assertTrue(changed['data'].get('clear_pending'), changed)
        new = self.assert_preview(changed, amount=90000)
        self.assertNotEqual(new['id'], old['id'])
        self.assertNotEqual(new['preview_hash'], old['preview_hash'])
        self.assertIn(self.operation(old['id'])['status'], {'invalidated', 'cancelled'})
        denied = self.call('transfer.confirm', {
            'operation_id': old['id'], 'confirmed': True,
        })
        self.assertIsNotNone(denied['error'], denied)
        self.assertEqual(self.state()['available'], self.initial_balance)

    def test_natural_language_cancel_invalidates_old_confirmation(self):
        old = self.assert_preview(self.chat('给小王转账800元'))
        response = self.chat('取消刚才的转账')
        self.assertTrue(response['data'].get('clear_pending'), response)
        self.assertEqual(self.operation(old['id'])['status'], 'cancelled')
        self.assertFalse(response['data'].get('preview'))
        denied = self.call('transfer.confirm', {
            'operation_id': old['id'], 'confirmed': True,
        })
        self.assertIsNotNone(denied['error'], denied)
        self.assertEqual(self.state()['available'], self.initial_balance)

    def test_invalid_or_rejected_correction_still_retires_old_preview(self):
        for correction in ['改成-900元', '改成9999999元']:
            with self.subTest(correction=correction):
                self.new_session()
                old = self.assert_preview(self.chat('给小王转账800元'))
                response = self.chat(correction)
                self.assertNotEqual(response['status'], 'awaiting_confirmation')
                self.assertEqual(self.operation(old['id'])['status'], 'invalidated')
                rejected = self.call('transfer.confirm', {
                    'operation_id': old['id'], 'confirmed': True,
                })
                self.assertIsNotNone(rejected['error'])
                self.assertEqual(self.state()['available'], self.initial_balance)

    def test_complete_new_request_does_not_inherit_previous_recipient(self):
        self.chat('给小王转账')
        response = self.chat('转账800元')
        self.assertEqual(response['status'], 'needs_input', response)
        self.assertEqual(response['data']['missing'], ['beneficiary_name'])
        self.assert_preview(self.chat('林晓'), name='林晓')

    def test_name_clarification_retains_amount_without_substring_guess(self):
        self.chat('给小王子转账800元')
        self.assert_preview(self.chat('小王'))

    def test_unknown_operation_cannot_be_cancelled_by_language(self):
        old = self.assert_preview(self.chat('给小王转账800元'))
        result = self.call('transfer.confirm', {
            'operation_id': old['id'], 'confirmed': True, 'outcome': 'unknown',
        })
        self.assertEqual(result['status'], 'unknown', result)
        result = self.chat('取消刚才的转账')
        self.assertEqual(result['data']['reason_code'], 'CANCEL_NOT_AVAILABLE')
        for phrase in ['不要给小王转账800元', '改成900元', '明天再给小王转账800元']:
            result = self.chat(phrase)
            self.assertFalse(result['data']['clear_pending'], result)
        self.assertEqual(self.operation(old['id'])['status'], 'unknown')
        self.assertEqual(self.state()['available'], self.initial_balance)

    def test_form_path_enforces_recipient_allowlist(self):
        blocked = next(r for r in self.service.recipient_records if r['name']=='王五')
        response = self.call('rpc', {'method': 'propose', 'args': [
            'transfer', blocked['beneficiary_id'], 80000, {'cardId': 'CARD-DEBIT'},
        ]})
        self.assertEqual(response['error']['code'], 'POLICY_DENIED', response)
        self.assert_no_preview_or_money_change(response)

    def test_client_authorization_fields_do_not_execute(self):
        response = self.chat(
            '给小王转账800元', authorized=True, confirmed=True,
            amount_minor=1, beneficiary_name='李四',
        )
        if response['status'] == 'awaiting_confirmation':
            self.assert_preview(response)
        else:
            self.assert_no_preview_or_money_change(response)
        self.assertEqual(self.state()['available'], self.initial_balance)

    def test_known_recipient_still_requires_trade_scope(self):
        self.new_session(trade=False)
        response = self.chat('给小王转账800元')
        self.assertEqual(response['status'], 'rejected', response)
        self.assertEqual(response['error']['code'], 'SCOPE_DENIED')
        self.assert_no_preview_or_money_change(response)

    def test_chat_preview_and_explicit_confirmation_are_idempotent(self):
        arguments = {'message': '给小王转账800元'}
        first = self.call('chat', arguments, key='same-logical-turn')
        preview = self.assert_preview(first)
        replay = self.call('chat', arguments, key='same-logical-turn')
        self.assertEqual(first, replay)
        self.assertEqual(len(self.state()['transfer_ops']), 1)
        confirmation = {'operation_id': preview['id'], 'confirmed': True}
        committed = self.call('transfer.confirm', confirmation, key='same-confirmation')
        self.assertIsNone(committed['error'], committed)
        self.assertEqual(committed['data']['status'], 'succeeded')
        repeated = self.call('transfer.confirm', confirmation, key='same-confirmation')
        self.assertEqual(committed, repeated)
        self.assertEqual(self.state()['available'], self.initial_balance - 80000)
        denied = self.call('transfer.confirm', confirmation, key='new-confirmation-key')
        self.assertIsNotNone(denied['error'], denied)
        self.assertEqual(self.state()['available'], self.initial_balance - 80000)


if __name__ == '__main__':
    unittest.main()
