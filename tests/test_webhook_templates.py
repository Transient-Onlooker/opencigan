import unittest

from backend.webhook_templates import render_template


class WebhookTemplateTests(unittest.TestCase):
    def test_text_and_embed_disable_mentions_and_neutralize_links(self):
        values = {'school': '<users/all> https://example.test', 'period': 2}
        text = render_template('discord', '{school} {period}', values)
        self.assertEqual(text['allowed_mentions'], {'parse': []})
        self.assertNotIn('<users/all>', text['content'])
        self.assertNotIn('https://', text['content'])
        embed = render_template('discord', '{school}', values, discord_embed=True)
        self.assertEqual(embed['allowed_mentions'], {'parse': []})
        self.assertNotIn('<', embed['embeds'][0]['description'])
        chat = render_template('google-chat', '{school}', values)
        self.assertNotIn('<users/all>', chat['text'])
        self.assertNotIn('https://', chat['text'])
        unsafe = render_template('google-chat', 'www.example.test [link](javascript:alert)', {})['text']
        self.assertNotIn('www.', unsafe)
        self.assertNotIn('javascript:', unsafe)

    def test_neutralizes_common_and_malformed_url_forms(self):
        urls = [
            'https://example.com/path?q=1',
            'https ://example.com',
            'http://example.org',
            'ftp://files.example.net/archive',
            'www.example.com',
            'example.com/path',
            'javascript:alert(1)',
            'data:text/html,hello',
            'mailto:user@example.com',
            '[open](https://example.com)',
            '//example.com/path',
        ]
        for url in urls:
            with self.subTest(url=url):
                output = render_template('google-chat', '{school}', {'school': url})['text']
                self.assertNotIn('://', output)
                self.assertNotIn('www.', output)
                self.assertNotIn('example.com', output)
                self.assertNotIn('javascript:', output)
                self.assertNotIn('data:', output)
                self.assertNotIn('mailto:', output)

    def test_keeps_ordinary_sentence_punctuation_unchanged(self):
        sentence = 'Bring a notebook: math starts at 9:10. See you soon!'
        output = render_template('google-chat', '{school}', {'school': sentence})['text']
        self.assertEqual(output, sentence)

    def test_rejects_unknown_missing_complex_and_unbounded_templates(self):
        for template, values in [('{unknown}', {}), ('{school.__class__}', {'school': 'x'}),
                                 ('{school!r}', {'school': 'x'}), ('{school:>4}', {'school': 'x'}),
                                 ('{school}', {}), ('{', {}), ('x' * 1201, {}),
                                 ('{school}', {'school': 'x' * 1801})]:
            with self.subTest(template=template[:30]):
                with self.assertRaises(ValueError):
                    render_template('discord', template, values)
        with self.assertRaises(ValueError):
            render_template('google-chat', 'hi', {}, discord_embed=True)

    def test_braces_and_korean_text_remain_readable(self):
        result = render_template('google-chat', '{{공지}} {school} {period}교시', {'school': '예시학교', 'period': 3})
        self.assertEqual(result['text'], '{공지} 예시학교 3교시')


if __name__ == '__main__':
    unittest.main()
