"""User-visible wording checks for the deterministic English caption filter."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from neutral_language import neutralize_gender
from storage import CHARACTER_REFERENCE_GUIDANCE, format_caption


class NeutralLanguageTests(unittest.TestCase):
    def test_pronouns_possessives_and_whole_sentences(self):
        cases = {
            "She is wearing her jacket beside him.": "They are wearing their jacket beside them.",
            "He has his hand on her shoulder. The bag is his and the coat is hers.":
                "They have their hand on their shoulder. The bag is theirs and the coat is theirs.",
            "A wall behind her is white. Her hair frames her face.":
                "A wall behind them is white. Their hair frames their face.",
            "She looks at herself while he watches himself.":
                "They look at themselves while they watch themselves.",
            "We see her standing. Her smile is gentle. Watch her smile.":
                "We see them standing. Their smile is gentle. Watch them smile.",
            "The photographer admires her red coat and his blue jacket.":
                "The photographer admires their red coat and their blue jacket.",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(neutralize_gender(source), expected)

    def test_verb_agreement_and_unrelated_clause(self):
        cases = {
            "She stands, smiles and carries a bag that hangs from a hook.":
                "They stand, smile and carry a bag that hangs from a hook.",
            "He gently rests his hands and slightly tilts his head.":
                "They gently rest their hands and slightly tilt their head.",
            "She pairs her blouse with jeans and accessorizes with a necklace.":
                "They pair their blouse with jeans and accessorize with a necklace.",
            "She wears a coat and her friend wears a hat.":
                "They wear a coat and their friend wears a hat.",
            "The woman is seated. The man has a scarf.":
                "The person is seated. The person has a scarf.",
            "Is she standing? Does he wear a hat? She does not smile. He wasn't seated.":
                "Are they standing? Do they wear a hat? They do not smile. They weren't seated.",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(neutralize_gender(source), expected)

    def test_contractions_case_and_pronoun_pairs(self):
        cases = {
            "She's wearing a coat. He's been standing. She'll sit. He'd smile.":
                "They're wearing a coat. They've been standing. They'll sit. They'd smile.",
            "SHE IS HERE. HER COAT IS RED. HE HAS A HAT.": "THEY ARE HERE. THEIR COAT IS RED. THEY HAVE A HAT.",
            "A SPORTSWOMAN AND AN ACTRESS.": "AN ATHLETE AND A PERFORMER.",
            "She’s already been here. He isn’t smiling. He’s dressed in black.":
                "They’ve already been here. They aren’t smiling. They’re dressed in black.",
            "He or she is holding his or her coat. She/her; he/him/his.":
                "They are holding their coat. They/them; they/them/theirs.",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(neutralize_gender(source), expected)

    def test_people_roles_possessives_and_articles(self):
        cases = {
            "An actress, a businessman and a policewoman stand with two girls and three men.":
                "A performer, a businessperson and a police officer stand with two children and three people.",
            "The woman's coat has a flower. The ladies' hands rest on the boys’ shoulders.":
                "The person's coat has a flower. The people's hands rest on the children’s shoulders.",
            "A mother and father stand beside their son and daughter.":
                "A parent and parent stand beside their child and child.",
            "The bride and the groom wear formal outfits. A sportswoman is seated.":
                "The wedding participant and the wedding participant wear formal outfits. An athlete is seated.",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(neutralize_gender(source), expected)

    def test_gender_modifiers_and_apparel_labels(self):
        cases = {
            "A female model wears a women's jacket. A male police officer holds a men's coat.":
                "A model wears a jacket. A police officer holds a coat.",
            "A female professional athlete with a masculine build and feminine facial features.":
                "A professional athlete with a build and distinctive facial features.",
            "The subject is female. A male stands beside a female.":
                "The subject is a person. A person stands beside a person.",
            "Female models pose near male models.": "Models pose near models.",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(neutralize_gender(source), expected)

    def test_clothing_anatomy_and_substrings_preserved(self):
        source = "A human mannequin wears sheer fabric with an embroidered hem and leather shoes. A camera and shelves stand nearby. A beard, dress, skirt, broad shoulders and curved hips are visible."
        self.assertEqual(neutralize_gender(source), source)
        self.assertEqual(neutralize_gender("Mother-of-pearl buttons on a shirt."), "Nacre buttons on a shirt.")

    def test_idempotence_and_independent_toggle_defaults(self):
        original = "She has her coat. A woman beside him stands under the light."
        self.assertEqual(format_caption(original, {}), original)
        self.assertEqual(format_caption(original, {"gender_neutral": False}), original)
        enabled = format_caption(original, {"gender_neutral": True, "character_reference": True})
        self.assertTrue(enabled.endswith(CHARACTER_REFERENCE_GUIDANCE))
        self.assertTrue(enabled.startswith("They have their coat. A person beside them stands"))
        self.assertEqual(neutralize_gender(enabled), enabled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
