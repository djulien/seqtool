"""Small argparse helpers (0.20.8)."""
from __future__ import annotations

import re
import sys


def dash_words(ap, argv=None) -> list[str]:
    """argv with '--' put before a word that starts with '-' but is no option of `ap` - a
    pattern such as '-all$' or a name such as '-tree' (argparse would call it an unknown
    option). Only when every later word is not an option either, so it stays positional."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" in argv:
        return argv
    opts = {s for act in ap._actions for s in act.option_strings}

    def is_opt(w):
        return w in opts or w.split("=", 1)[0] in opts or (w.startswith("--") and any(o.startswith(w) for o in opts))
    for i, w in enumerate(argv):
        if w.startswith("-") and len(w) > 1 and not is_opt(w) and not re.fullmatch(r"-\d+(\.\d+)?", w):
            if not any(is_opt(x) for x in argv[i + 1:]):
                return argv[:i] + ["--"] + argv[i:]
            rest = argv[i + 1:]                          # options after it: it goes last ('-all$ --all')
            if not any(x.startswith("-") and not is_opt(x) for x in rest) and \
                    not any(not x.startswith("-") for x in rest if not is_opt(x)):
                return argv[:i] + rest + ["--", w]
            break
    return argv


class Literal(str):
    """A word that was quoted on a seqtool line (0.24.34): '"--fast"' is text, not an option -
    argparse takes it as a positional word (see _parse_optional below)."""


def split_line(line: str) -> list[str]:
    """shlex.split for a seqtool line (the prompt, the GUI console, batch, start commands),
    marking quoted words that start with '-' as Literal."""
    import shlex
    lex = shlex.shlex(line, posix=True)
    lex.whitespace_split = True
    lex.commenters = ""
    out = []
    while True:
        start = lex.instream.tell() if hasattr(lex.instream, "tell") else 0
        tok = lex.get_token()
        if tok is None or tok == lex.eof:
            break
        raw = line[start:lex.instream.tell()].strip() if hasattr(lex.instream, "tell") else tok
        quoted = '"' in raw or "'" in raw
        out.append(Literal(tok) if quoted and tok.startswith("-") else tok)
    return out


def _patch_argparse() -> None:
    import argparse
    if getattr(argparse.ArgumentParser, "_seqtool_literal", False):
        return
    orig = argparse.ArgumentParser._parse_optional

    def _parse_optional(self, arg_string):
        if isinstance(arg_string, Literal):
            return None                               # a quoted word: positional, whatever it starts with
        return orig(self, arg_string)
    argparse.ArgumentParser._parse_optional = _parse_optional
    argparse.ArgumentParser._seqtool_literal = True
    orig_parse = argparse.ArgumentParser.parse_args

    def parse_args(self, args=None, namespace=None):
        """0.24.36: words after an option ('pin X @2 --only twinkle') are taken too - when the
        plain parse leaves words over that aren't options, the words and options may mix."""
        ns, extra = self.parse_known_args(args, namespace)
        if extra and not any(isinstance(w, str) and w.startswith("-") and not isinstance(w, Literal) for w in extra):
            try:
                import contextlib
                import io
                with contextlib.redirect_stderr(io.StringIO()):
                    return self.parse_intermixed_args(args, namespace)
            except (SystemExit, TypeError, ValueError, AttributeError):
                pass
        return orig_parse(self, args, namespace)
    argparse.ArgumentParser.parse_args = parse_args


_patch_argparse()
