import copy
import math
import unittest
import xml.etree.ElementTree as ET
from mandermaid import layout, render_svg
from semantic_map_parser import parse

class LayoutTests(unittest.TestCase):
    def model(self, constraints, focus='a'):
        return parse('semanticMap\nnode a "A"\nnode b "B"\nnode c "C"\n' + constraints + '\nfocus ' + focus)

    def test_distances_and_diagonal_are_radial(self):
        model = self.model('around a { east b at 1 }\naround a { northwest c at 2 }')
        result = layout(model)
        a, b, c = (result['positions'][key] for key in ('a', 'b', 'c'))
        self.assertAlmostEqual(b['x'] - a['x'], 180)
        self.assertAlmostEqual(math.hypot(c['x'] - a['x'], c['y'] - a['y']), 360)
        self.assertFalse(result['warnings'])

    def test_focus_and_statement_order_do_not_change_geometry(self):
        first = self.model('around a { east b }\naround b { north c }')
        second = self.model('around b { north c }\naround a { east b }', 'c')
        self.assertEqual(layout(first)['positions'], layout(second)['positions'])
        original = copy.deepcopy(first)
        svg = render_svg(first, layout(first), 'c')
        self.assertEqual(first, original)
        ET.fromstring(svg)

    def test_inconsistent_cycle_reports_error(self):
        model = self.model('around a { east b }\naround b { east c }\naround c { east a }')
        result = layout(model)
        self.assertTrue(any('offset error' in warning for warning in result['warnings']))
        self.assertTrue(all(math.isfinite(p['x']) and math.isfinite(p['y']) for p in result['positions'].values()))

    def test_directionless_uses_free_direction(self):
        model = self.model('around a { north b }\naround a { c at 2 }')
        before = copy.deepcopy(model)
        result = layout(model)
        auto = next(p for p in result['placements'] if p['target'] == 'c')
        self.assertEqual(auto['resolved_direction'], 'northeast')
        self.assertEqual(model, before)

    def test_isolated_nodes_and_empty_input(self):
        result = layout(self.model(''))
        self.assertEqual(len(result['positions']), 3)
        self.assertFalse(result['warnings'])
        empty = parse('semanticMap')
        ET.fromstring(render_svg(empty, layout(empty)))

    def test_labels_are_escaped(self):
        model = parse('semanticMap\nnode a "<script>alert(1)</script> &"\nfocus a')
        svg = render_svg(model, layout(model))
        ET.fromstring(svg)
        self.assertNotIn('<script>', svg)

if __name__ == '__main__':
    unittest.main()
