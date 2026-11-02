"""A tiny generative grammar for chat lines (talk/lang/<code>.json acts).

  (a|b|c)   one of the alternatives (nested freely)
  [x]       optional part
  {slot}    a field (map, ship, name ...); a pattern whose field is missing or empty is not used
  <class>   a word of the lexicon class, by the bot's own stable preference (persona.pick)
  @act      another act of the same language (a shared sub-grammar)
  //        a split point: the bot may send the two halves as two messages

expand() returns the text or None. Parsing is cached per pattern.
"""
import re

_TOKEN = re.compile(r'\(|\)|\[|\]|\||\{[a-z_0-9]+\}|<[a-z_0-9]+>|@[a-z_0-9]+|//|[^()\[\]|{<@/]+|[{<@/]')
_cache = {}


class Missing(Exception):
    pass


def parse(pattern):
    tree = _cache.get(pattern)
    if tree is None:
        tokens = _TOKEN.findall(pattern)
        tree, i = _seq(tokens, 0, ())
        _cache[pattern] = tree
    return tree


def _seq(tokens, i, stop):
    """-> ([alternative, ...], index) where an alternative is a list of nodes."""
    alts, cur = [], []
    while i < len(tokens):
        t = tokens[i]
        if t in stop:
            break
        if t == '|':
            alts.append(cur)
            cur = []
            i += 1
            continue
        if t == '(':
            sub, i = _seq(tokens, i + 1, (')',))
            cur.append(('alt', sub))
            i += 1
            continue
        if t == '[':
            sub, i = _seq(tokens, i + 1, (']',))
            cur.append(('opt', sub))
            i += 1
            continue
        if t == '//':
            cur.append(('split',))
        elif t.startswith('{') and t.endswith('}') and len(t) > 2:
            cur.append(('slot', t[1:-1]))
        elif t.startswith('<') and t.endswith('>') and len(t) > 2:
            cur.append(('lex', t[1:-1]))
        elif t.startswith('@') and len(t) > 1:
            cur.append(('act', t[1:]))
        else:
            cur.append(('text', t))
        i += 1
    alts.append(cur)
    return alts, i


class Expander:
    """slots: dict; lex(cls) -> word; act(name) -> pattern or None; r: random.Random; opt: optional part chance."""

    def __init__(self, slots, lex, act, r, opt=0.5):
        self.slots, self.lex, self.act, self.r, self.opt, self.depth = slots, lex, act, r, opt, 0

    def run(self, pattern):
        try:
            return self._alts(parse(pattern))
        except Missing:
            return None

    def _alts(self, alts):
        return self._nodes(self.r.choice(alts))

    def _nodes(self, nodes):
        out = []
        for n in nodes:
            k = n[0]
            if k == 'text':
                out.append(n[1])
            elif k == 'alt':
                out.append(self._alts(n[1]))
            elif k == 'opt':
                if self.r.random() < self.opt:
                    try:
                        out.append(self._alts(n[1]))
                    except Missing:
                        pass                               # an optional part with a missing field is just left out
            elif k == 'split':
                out.append(' // ')
            elif k == 'slot':
                v = self.slots.get(n[1])
                if v is None or v == '':
                    raise Missing(n[1])
                out.append(str(v))
            elif k == 'lex':
                w = self.lex(n[1])
                if w is None:
                    raise Missing(n[1])
                out.append(w)
            elif k == 'act':
                p = self.act(n[1])
                if p is None or self.depth > 6:
                    raise Missing(n[1])
                self.depth += 1
                out.append(self._alts(parse(p)))
                self.depth -= 1
        return ''.join(out)


def tidy(text):
    """Spaces and punctuation of an expanded line."""
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' +([,!?.;])(?=\s|$)', r'\1', text)          # "ne ?" -> "ne?", but ":/" and ":D" keep their space
    text = re.sub(r'([,])(?=\S)', r'\1 ', text)
    text = re.sub(r',\s*,', ',', text)
    text = re.sub(r'([?!])\s*,', r'\1', text)
    text = re.sub(r'(?i)\b(lol|xd|haha|kek|lmao|jaja|kkk)\b(\s+\1\b)+', r'\1', text)      # "lol lol"                  # "aegis nasıl?, alan var mı" -> "aegis nasıl? alan var mı"
    text = re.sub(r'^\s*[,]\s*', '', text)
    text = re.sub(r'\s*//\s*', ' // ', text).strip()
    text = re.sub(r'^(//\s*)+|(\s*//)+$', '', text).strip()
    text = re.sub(r'(//\s*){2,}', '// ', text)
    return text.strip(' ,')
