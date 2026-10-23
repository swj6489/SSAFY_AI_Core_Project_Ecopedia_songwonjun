import unittest

from ecopedia.ui import CSS, PALETTES, theme_variables


def luminance(color):
    values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


class ThemeTests(unittest.TestCase):
    def test_status_summary_and_plain_source_text_are_themed(self):
        self.assertIn('[data-testid="stExpander"] summary {', CSS)
        self.assertIn('[data-testid="stExpander"] summary:hover', CSS)
        self.assertIn('[data-testid="stExpanderDetails"]', CSS)
        self.assertIn('[data-testid="stText"] span {', CSS)
        self.assertIn('[data-testid="stSpinner"] p', CSS)

    def test_chat_input_inner_surface_and_webkit_text_are_themed(self):
        self.assertIn('[data-testid="stChatInput"] > div {', CSS)
        self.assertIn('[data-testid="stChatInputTextArea"] {', CSS)
        self.assertIn('[data-testid="stChatInputTextArea"]::placeholder {', CSS)
        self.assertIn('#stChatInputInstructions', CSS)
        self.assertIn('-webkit-text-fill-color:var(--eco-ink) !important', CSS)
        self.assertIn('-webkit-text-fill-color:var(--eco-muted) !important', CSS)

    def test_tooltip_surface_and_nested_text_use_the_same_palette(self):
        self.assertIn('[data-testid="stTooltipContent"]', CSS)
        self.assertIn('[data-testid="stTooltipErrorContent"]', CSS)
        self.assertIn('[data-testid="stTooltipContent"] *', CSS)
        self.assertIn('background-color:var(--eco-panel) !important', CSS)
        self.assertIn('-webkit-text-fill-color:var(--eco-ink) !important', CSS)
        self.assertIn(':root', theme_variables('다크'))

    def test_text_palette_contrast(self):
        for mode, palette in PALETTES.items():
            for foreground, background in (('ink', 'bg'), ('ink', 'panel'), ('muted', 'sidebar'),
                                           ('muted', 'bg'), ('muted', 'panel'), ('link', 'panel'), ('button-text', 'button')):
                with self.subTest(mode=mode, pair=(foreground, background)):
                    high, low = sorted((luminance(palette[foreground]), luminance(palette[background])), reverse=True)
                    self.assertGreaterEqual((high + 0.05) / (low + 0.05), 4.5)

    def test_complete_palettes_and_safe_mode_fallback(self):
        self.assertEqual(set(PALETTES['라이트']), set(PALETTES['다크']))
        self.assertEqual(theme_variables('<script>'), theme_variables('라이트'))
        self.assertNotEqual(theme_variables('다크'), theme_variables('라이트'))

    def test_react_aria_controls_have_explicit_surface_and_text_colors(self):
        self.assertIn('[data-testid="stTextInputRootElement"]', CSS)
        self.assertIn('[data-testid="stSelectbox"] div:has(> input[role="combobox"])', CSS)
        self.assertIn('[data-testid="stSelectboxVirtualDropdown"]', CSS)
        self.assertIn('background-color:var(--eco-panel) !important', CSS)
        self.assertIn('-webkit-text-fill-color:var(--eco-ink) !important', CSS)
        self.assertIn('-webkit-text-fill-color:var(--eco-muted) !important', CSS)


if __name__ == '__main__':
    unittest.main()
