"""Unit tests for the spoken punctuation, layout and edit commands.

    python scripts/test_commands.py

Imports the command layer out of `sttlocal.py` by hand so the test needs no
audio stack (sounddevice/pynput are not importable on a build machine, and
this logic is pure text).
"""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load_command_layer():
    source = open(os.path.join(ROOT, "sttlocal.py"), encoding="utf-8").read()
    start = source.index("# Spoken commands")
    end = source.index("def clean_transcript")
    namespace = {"re": re}
    exec(compile(source[start:end], "sttlocal.py", "exec"), namespace)
    return namespace["apply_spoken_commands"]


apply_spoken_commands = _load_command_layer()


class TestPunctuation(unittest.TestCase):
    def test_basic_marks(self):
        self.assertEqual(
            apply_spoken_commands("bonjour Marc virgule comment vas-tu point"),
            "Bonjour Marc, comment vas-tu.",
        )

    def test_french_spacing_on_high_punctuation(self):
        """: ; ! ? take a space before them in French; , and . do not."""
        self.assertEqual(
            apply_spoken_commands("objet deux points relance point"),
            "Objet : relance.",
        )
        self.assertEqual(
            apply_spoken_commands("vraiment point d'exclamation"), "Vraiment !"
        )

    def test_longer_phrases_win_over_their_prefix(self):
        """"points de suspension" must not be eaten by "point"."""
        self.assertEqual(
            apply_spoken_commands("attends points de suspension bon point"),
            "Attends… Bon.",
        )
        self.assertEqual(
            apply_spoken_commands("un point virgule deux point"), "Un ; deux."
        )

    def test_quotes_and_parentheses(self):
        self.assertEqual(
            apply_spoken_commands(
                "il a dit ouvrez les guillemets parfait fermez les guillemets point"),
            "Il a dit « parfait ».",
        )
        self.assertEqual(
            apply_spoken_commands(
                "le total ouvrez la parenthese hors taxe fermez la parenthese point"),
            "Le total (hors taxe).",
        )

    def test_plain_words_are_not_commands(self):
        """"points" is not "point": a plural must survive untouched."""
        self.assertIn("points suivants", apply_spoken_commands("les points suivants"))


class TestLayout(unittest.TestCase):
    def test_line_and_paragraph(self):
        # A simple line break does not force a capital: "à la ligne" is used
        # mid-sentence (addresses, lists), where capitalising would be wrong.
        # A new *paragraph* does, per the product spec.
        self.assertEqual(
            apply_spoken_commands("première ligne à la ligne deuxième ligne"),
            "Première ligne\ndeuxième ligne",
        )
        self.assertEqual(
            apply_spoken_commands("intro point nouveau paragraphe suite point"),
            "Intro.\n\nSuite.",
        )

    def test_bullets(self):
        self.assertEqual(
            apply_spoken_commands("liste deux points tiret premier tiret second"),
            "Liste :\n- Premier\n- Second",
        )

    def test_sentences_are_capitalised(self):
        self.assertEqual(
            apply_spoken_commands("un point deux point trois point"),
            "Un. Deux. Trois.",
        )


class TestEditing(unittest.TestCase):
    def test_delete_last_word(self):
        self.assertEqual(
            apply_spoken_commands("je disais bonjour effacer bonsoir Marc point"),
            "Je disais bonsoir Marc.",
        )

    def test_delete_last_word_explicit_phrase(self):
        self.assertEqual(
            apply_spoken_commands("un deux trois effacer le dernier mot point"),
            "Un deux.",
        )

    def test_clear_everything(self):
        self.assertEqual(
            apply_spoken_commands("brouillon inutile tout effacer le vrai texte point"),
            "Le vrai texte.",
        )

    def test_delete_on_empty_text_is_harmless(self):
        self.assertEqual(apply_spoken_commands("effacer"), "")
        self.assertEqual(apply_spoken_commands("annuler"), "")


class TestIdempotenceAndSafety(unittest.TestCase):
    def test_plain_text_survives(self):
        text = "Bonjour Marc, comment vas-tu ?"
        self.assertEqual(apply_spoken_commands(text), text)

    def test_empty_input(self):
        self.assertEqual(apply_spoken_commands(""), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
