"""Deterministic English caption normalization; no model or download required.

Mappings deliberately target language about people, not clothing, anatomy or
substrings (for example, 'sheer', 'hem' and 'mannequin' are left alone).
"""
import re


PERSON_TERMS = {
    "man": "person", "woman": "person", "men": "people", "women": "people",
    "gentleman": "person", "lady": "person", "gentlemen": "people", "ladies": "people",
    "boy": "child", "girl": "child", "boys": "children", "girls": "children",
    "guy": "person", "gal": "person", "guys": "people", "gals": "people",
    "lad": "person", "lass": "person", "lads": "people", "lasses": "people",
    "male": "person", "female": "person", "males": "people", "females": "people",
    "boyfriend": "partner", "girlfriend": "partner", "boyfriends": "partners", "girlfriends": "partners",
    "husband": "spouse", "wife": "spouse", "husbands": "spouses", "wives": "spouses",
    "mother": "parent", "father": "parent", "mothers": "parents", "fathers": "parents",
    "mom": "parent", "mum": "parent", "dad": "parent", "moms": "parents", "mums": "parents", "dads": "parents",
    "mommy": "parent", "daddy": "parent", "mama": "parent", "papa": "parent",
    "son": "child", "daughter": "child", "sons": "children", "daughters": "children",
    "brother": "sibling", "sister": "sibling", "brothers": "siblings", "sisters": "siblings",
    "grandmother": "grandparent", "grandfather": "grandparent", "grandma": "grandparent", "grandpa": "grandparent",
    "grandmothers": "grandparents", "grandfathers": "grandparents", "grandmas": "grandparents", "grandpas": "grandparents",
    "grandson": "grandchild", "granddaughter": "grandchild", "grandsons": "grandchildren", "granddaughters": "grandchildren",
    "aunt": "relative", "uncle": "relative", "niece": "relative", "nephew": "relative",
    "aunts": "relatives", "uncles": "relatives", "nieces": "relatives", "nephews": "relatives",
    "bride": "wedding participant", "brides": "wedding participants", "bridegroom": "wedding participant",
    "bridegrooms": "wedding participants", "bridesmaid": "wedding attendant", "groomsman": "wedding attendant",
    "bridesmaids": "wedding attendants", "groomsmen": "wedding attendants",
    "actor": "performer", "actress": "performer", "actors": "performers", "actresses": "performers",
    "waiter": "server", "waitress": "server", "waiters": "servers", "waitresses": "servers",
    "businessman": "businessperson", "businesswoman": "businessperson", "businessmen": "businesspeople", "businesswomen": "businesspeople",
    "policeman": "police officer", "policewoman": "police officer", "policemen": "police officers", "policewomen": "police officers",
    "fireman": "firefighter", "firewoman": "firefighter", "firemen": "firefighters", "firewomen": "firefighters",
    "chairman": "chairperson", "chairwoman": "chairperson", "chairmen": "chairpeople", "chairwomen": "chairpeople",
    "spokesman": "spokesperson", "spokeswoman": "spokesperson", "spokesmen": "spokespeople", "spokeswomen": "spokespeople",
    "salesman": "salesperson", "saleswoman": "salesperson", "salesmen": "salespeople", "saleswomen": "salespeople",
    "sportsman": "athlete", "sportswoman": "athlete", "sportsmen": "athletes", "sportswomen": "athletes",
    "fisherman": "fisher", "fisherwoman": "fisher", "fishermen": "fishers", "fisherwomen": "fishers",
    "cameraman": "camera operator", "camerawoman": "camera operator", "cameramen": "camera operators", "camerawomen": "camera operators",
    "steward": "flight attendant", "stewardess": "flight attendant", "stewards": "flight attendants", "stewardesses": "flight attendants",
    "hostess": "host", "hostesses": "hosts",
    "king": "monarch", "queen": "monarch", "kings": "monarchs", "queens": "monarchs",
    "prince": "royal", "princess": "royal", "princes": "royals", "princesses": "royals",
    "duke": "noble", "duchess": "noble", "dukes": "nobles", "duchesses": "nobles",
    "emperor": "ruler", "empress": "ruler", "emperors": "rulers", "empresses": "rulers",
    "hero": "protagonist", "heroine": "protagonist", "heroes": "protagonists", "heroines": "protagonists",
    "schoolboy": "student", "schoolgirl": "student", "schoolboys": "students", "schoolgirls": "students",
    "headmaster": "headteacher", "headmistress": "headteacher", "headmasters": "headteachers", "headmistresses": "headteachers",
    "landlord": "property owner", "landlady": "property owner", "landlords": "property owners", "landladies": "property owners",
    "maid": "attendant", "maids": "attendants", "maiden": "person", "maidens": "people",
    "sir": "person", "madam": "person", "ma'am": "person",
    "feminine": "distinctive", "masculine": "distinctive", "womanly": "distinctive", "manly": "distinctive",
    "effeminate": "distinctive", "mannish": "distinctive", "girlish": "youthful", "boyish": "youthful",
    "ladylike": "refined", "gentlemanly": "refined", "femininity": "individuality", "masculinity": "individuality",
    "motherly": "parental", "fatherly": "parental", "maternal": "parental", "paternal": "parental",
    "manhood": "adulthood", "womanhood": "adulthood", "mankind": "humankind", "manpower": "workforce",
    "man-made": "human-made", "manmade": "human-made",
    "male-presenting": "distinctive", "female-presenting": "distinctive",
}

VERBS = dict(zip(
    "is was has does stands sits wears looks gazes holds leans rests faces walks smiles appears seems poses carries places keeps turns tilts bends extends raises lowers clasps touches crosses uncrosses sweeps shows displays exhibits maintains uses emphasizes emphasises exudes conveys presents occupies interacts sports models stares peers focuses focusses watches glances laughs frowns squints blinks grins gestures points adjusts tucks balances steps runs dances jumps kneels reclines lies continues combines contrasts creates reads reaches drinks eats speaks pauses works writes sees feels tries studies stretches catches embraces relaxes features takes makes goes comes brings drapes hangs frames sits".split(),
    "are were have do stand sit wear look gaze hold lean rest face walk smile appear seem pose carry place keep turn tilt bend extend raise lower clasp touch cross uncross sweep show display exhibit maintain use emphasize emphasise exude convey present occupy interact sport model stare peer focus focus watch glance laugh frown squint blink grin gesture point adjust tuck balance step run dance jump kneel recline lie continue combine contrast create read reach drink eat speak pause work write see feel try study stretch catch embrace relax feature take make go come bring drape hang frame sit".split()
))
VERBS.update({"isn't": "aren't", "wasn't": "weren't", "hasn't": "haven't", "doesn't": "don't"})
VERBS.update({"pairs": "pair", "accessorizes": "accessorize", "accessorises": "accessorise",
              "completes": "complete", "complements": "complement", "enhances": "enhance",
              "grips": "grip", "supports": "support", "beams": "beam", "enjoys": "enjoy"})
ADVERBS = {"not", "also", "always", "never", "often", "sometimes", "still", "just", "only", "even", "almost", "already", "now", "then", "here", "there", "usually"}
OBJECT_FOLLOWERS = set("and or but with without in into on onto at by near beside behind between around against towards toward from underneath under above below before after as than to for whose who which that while when where if although because wearing standing sitting seated smiling looking leaning posing walking running holding dressed framed illuminated lit".split())
POSSESSIVE_NOUNS = set("face hand hands look looks pose poses smile smiles dress dresses walk walks gaze gazes watch watches back front left right side sides head hair eye eyes arm arms leg legs body shoulder shoulders figure silhouette outfit clothing coat jacket shirt skirt trousers pants jeans shoes expression appearance own".split())
PERCEPTION_VERBS = set("see sees saw seen watch watches watched watching seeing observe observes observed observing hear hears heard hearing".split())
PARTICIPLES = set("been got had seen done taken worn gone become begun chosen made found left come brought kept put stood sat held lost won eaten drunk written read arrived returned finished completed crossed raised lowered placed tucked turned".split())
WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?|[^\w\s]", re.UNICODE)
TERM_PATTERN = re.compile(r"(?<!\w)(" + "|".join(re.escape(term).replace("'", "['’]") for term in sorted(PERSON_TERMS, key=len, reverse=True)) + r")(['’]s|['’](?!\w))?(?!\w)", re.IGNORECASE)


def _case(source, replacement):
    if source.isupper() and len(source) > 1:
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _word(value):
    return value.lower().replace("’", "'")


def _possessive(tokens, index, pronoun):
    """Resolve the common determiner/object ambiguity of her and his in captions."""
    following = _word(tokens[index + 1].group()) if index + 1 < len(tokens) else ""
    previous = _word(tokens[index - 1].group()) if index else ""
    if not following or not following[0].isalpha():
        return False
    if following in POSSESSIVE_NOUNS:
        return not (pronoun == "her" and previous in PERCEPTION_VERBS and following in {"smile", "pose", "walk", "dress", "watch"})
    if following in OBJECT_FOLLOWERS or following in VERBS or following in VERBS.values():
        return False
    return True


def _pronouns(text):
    tokens = list(WORD.finditer(text))
    changes = {}
    for i, token in enumerate(tokens):
        value = _word(token.group())
        if value in {"he", "she", "they"}:
            if value != "they":
                changes[i] = _case(token.group(), "they")
            # Verb agreement changes only for a pronoun subject, not nearby nouns.
            j = i + 1
            while j < len(tokens) and (_word(tokens[j].group()) in ADVERBS or tokens[j].group().lower().endswith("ly")):
                j += 1
            if j < len(tokens) and _word(tokens[j].group()) in VERBS:
                changes[j] = _case(tokens[j].group(), VERBS[_word(tokens[j].group())]).replace("'", "’" if "’" in tokens[j].group() else "'")
                # Coordinated predicates: "she stands, smiles and holds a bag".
                for k in range(j + 1, len(tokens)):
                    part = _word(tokens[k].group())
                    if part in {".", "!", "?", ";", ":", "who", "which", "that", "while", "where", "when", "because", "although", "if"}:
                        break
                    if part in {"and", "or", "but", ","}:
                        n = k + 1
                        while n < len(tokens) and (_word(tokens[n].group()) in ADVERBS or tokens[n].group().lower().endswith("ly")):
                            n += 1
                        if n < len(tokens) and _word(tokens[n].group()) in VERBS:
                            changes[n] = _case(tokens[n].group(), VERBS[_word(tokens[n].group())])
                        elif part != "," or (n < len(tokens) and _word(tokens[n].group()) not in {"and", "or", "but"}):
                            break
            # Inverted clauses: "Is she looking at the camera?"
            if i and _word(tokens[i - 1].group()) in {"is", "was", "has", "does", "isn't", "wasn't", "hasn't", "doesn't"}:
                before = tokens[i - 1].group()
                changes[i - 1] = _case(before, VERBS[_word(before)]).replace("'", "’" if "’" in before else "'")
        elif value in {"he's", "she's", "he'd", "she'd", "he'll", "she'll"}:
            ending = value.split("'")[1]
            n = i + 1
            while n < len(tokens) and (_word(tokens[n].group()) in ADVERBS or tokens[n].group().lower().endswith("ly")):
                n += 1
            next_word = _word(tokens[n].group()) if n < len(tokens) else ""
            replacement = "they'" + ({"d": "d", "ll": "ll"}.get(ending) or ("ve" if next_word in PARTICIPLES else "re"))
            changes[i] = _case(token.group(), replacement).replace("'", "’" if "’" in token.group() else "'")
        elif value in {"him", "hers", "himself", "herself"}:
            changes[i] = _case(token.group(), {"him": "them", "hers": "theirs", "himself": "themselves", "herself": "themselves"}[value])
        elif value in {"her", "his"}:
            changes[i] = _case(token.group(), "their" if _possessive(tokens, i, value) else ("them" if value == "her" else "theirs"))
    for index in sorted(changes, reverse=True):
        token = tokens[index]
        text = text[:token.start()] + changes[index] + text[token.end():]
    return text


def neutralize_gender(text):
    """Return English caption text with mapped gender terms and pronouns neutralized."""
    text = re.sub(r"\bmother[- ]of[- ]pearl\b", lambda m: _case(m.group(), "nacre"), text, flags=re.IGNORECASE)
    text = re.sub(r"\b(she/her|he/him)(/(hers|his))?\b", lambda m: _case(m.group(), "they/them" + ("/theirs" if m.group(2) else "")), text, flags=re.IGNORECASE)
    text = re.sub(r"\b(is|was)\s+(male|female)\b(?!\s+(?:model|person|figure|character)\b)", lambda m: m.group(1) + " a person", text, flags=re.IGNORECASE)
    # Treat combined forms as a single pronoun before grammatical agreement.
    pairs = [(r"(?:he\s*(?:/|or|and)\s*she|she\s*(?:/|or|and)\s*he|s/he)", "they"),
             (r"(?:his\s*(?:/|or|and)\s*her|her\s*(?:/|or|and)\s*his)", "their"),
             (r"(?:him\s*(?:/|or|and)\s*her|her\s*(?:/|or|and)\s*him)", "them")]
    for pattern, replacement in pairs:
        text = re.sub(r"\b" + pattern + r"\b", lambda m: _case(m.group(), replacement), text, flags=re.IGNORECASE)
    text = _pronouns(text)

    # Gender used as a modifier can be removed without creating "person model".
    modifiers = r"(?:male|female|masculine|feminine|male-presenting|female-presenting)"
    heads = r"(?:model|person|figure|subject|character|face|features|appearance|build|body|physique|silhouette|fashion|clothing|attire|outfit|style|portrait|profile|form|voice|expression|pose|energy|aesthetic|beauty|adult|teenager|child)s?"
    people = "|".join(re.escape(term) for term in sorted(set(PERSON_TERMS) | set(PERSON_TERMS.values()), key=len, reverse=True))
    adjectives = r"(?:(?:young|old|older|elderly|adult|tall|short|slender|slim|athletic|professional|fashion|runway|middle-aged|dark-haired|long-haired)\s+){0,4}"
    text = re.sub(r"\b(" + modifiers + r")\s+(" + adjectives + "(?:" + heads + "|" + people + r"))\b", lambda m: _case(m.group(1), m.group(2)), text, flags=re.IGNORECASE)
    # Apparel labels should not imply the reference character's gender.
    clothes = r"(?:jacket|coat|shirt|blouse|dress|skirt|suit|trousers|pants|jeans|shorts|shoe|boot|sneaker|sandal|hat|cap|underwear|swimwear|clothing|attire|outfit|fashion|wear)s?"
    text = re.sub(r"\b(?:men|women|ladies|boys|girls)['’]s?\s+(?=" + clothes + r"\b)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:male|female)[- ]pattern baldness\b", "hair loss", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(a|an|the)\s+groom\b", lambda m: m.group(1) + " wedding participant", text, flags=re.IGNORECASE)

    def term(match):
        source, possessive = match.groups()
        replacement = _case(source, PERSON_TERMS[_word(source)])
        if possessive:
            # Irregular plurals: ladies' -> people's, girls' -> children's.
            replacement += possessive if len(possessive) > 1 or replacement.lower().endswith("s") else possessive + "s"
        return replacement

    text = TERM_PATTERN.sub(term, text)
    # Correct the article when a replacement changes the initial sound.
    starts = {value.split()[0] for value in PERSON_TERMS.values()}
    pattern = r"\b(a|an)(\s+)(" + "|".join(re.escape(word) for word in sorted(starts, key=len, reverse=True)) + r")\b"
    def article(match):
        replacement = "an" if match.group(3)[0].lower() in "aeiou" else "a"
        replacement = replacement.upper() if match.group(1).isupper() and match.group(3).isupper() else _case(match.group(1), replacement)
        return replacement + match.group(2) + match.group(3)
    text = re.sub(pattern, article, text, flags=re.IGNORECASE)
    return text
