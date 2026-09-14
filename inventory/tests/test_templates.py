"""Template hygiene, checked mechanically rather than by noticing.

Where this came from: a multi-line `{# ... #}` comment in `base.html` rendered as literal
text inside the More menu, so the app showed the author's note, braces and all, to anyone
who opened it. Django's `{# #}` form is **single-line only** — across lines the template
engine never sees a comment at all, it sees text. Nothing else in the suite could catch it:
the page still rendered, still returned 200, and simply had a sentence of source code in the
middle of it.

So the check is mechanical, and it covers every template rather than the two that were
wrong. The second test is there for the same reason: a syntax error in a template is
invisible until somebody happens to visit that page, which in a personal app could be
months.
"""
from pathlib import Path

from django.conf import settings
from django.template import Template
from django.test import SimpleTestCase

TEMPLATE_ROOT = Path(settings.BASE_DIR) / "inventory" / "templates"


def template_paths():
    return sorted(TEMPLATE_ROOT.rglob("*.html"))


class TemplateCommentTests(SimpleTestCase):
    def test_no_comment_spans_more_than_one_line(self):
        """`{#` has to close with `#}` on the same line, or it is not a comment.

        Use `{% comment %}...{% endcomment %}` for anything longer.
        """
        offenders = []
        for path in template_paths():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "{#" not in line:
                    continue
                if "#}" not in line.split("{#", 1)[1]:
                    offenders.append(f"{path.relative_to(settings.BASE_DIR)}:{number}")
        self.assertEqual(
            offenders,
            [],
            "these multi-line {# #} comments render as visible text on the page: "
            + ", ".join(offenders),
        )

    def test_every_template_compiles(self):
        """A tag with a typo is a 500 on whichever page uses it, whenever it is next
        visited — which for a rarely-opened page is the worst possible time to find out."""
        for path in template_paths():
            with self.subTest(template=str(path.relative_to(settings.BASE_DIR))):
                Template(path.read_text(encoding="utf-8"))
