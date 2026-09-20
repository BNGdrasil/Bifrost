# --------------------------------------------------------------------------
# Path normalisation shared by the proxy route, the proxy and the URL policy
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from typing import Iterable, List, Tuple
from urllib.parse import unquote

# Percent decoding is applied until the path stops changing, because this
# gateway is not the last hop: an upstream or an intermediate proxy may decode
# the request again and turn a surviving `%2e` back into a dot segment. The
# bound keeps that loop finite; a path still changing after this many rounds is
# refused by the caller instead of being decoded further.
MAX_PATH_DECODING_ROUNDS = 8

# Characters that end the path for a routing upstream. They can only appear
# after a decoding round, since the raw query string is split off earlier.
PATH_TERMINATORS = ("?", "#")

# Segments that walk up the tree once the upstream has normalised the path.
DOT_SEGMENTS = (".", "..")


def decoding_rounds(path: str) -> Tuple[Tuple[str, ...], bool]:
    """Return the path as written and after each further decoding round.

    The second element reports whether decoding reached a fixed point within
    ``MAX_PATH_DECODING_ROUNDS``. A caller that enforces a policy must refuse
    the path when it did not, because the rounds it has are then only a prefix
    of what a repeatedly decoding upstream would eventually see.
    """
    rounds: List[str] = [path]
    current = path
    for _ in range(MAX_PATH_DECODING_ROUNDS):
        decoded = unquote(current, errors="replace")
        if decoded == current:
            return tuple(rounds), True
        rounds.append(decoded)
        current = decoded
    return tuple(rounds), False


def path_segments(path: str) -> Tuple[str, ...]:
    """Split one spelling of a path into the segments an upstream routes on.

    Empty segments coming from a leading, trailing or doubled slash are
    dropped, the `;parameters` suffix of a segment is cut off, surrounding
    whitespace is removed and the result is lowercased.
    """
    trimmed = path
    for terminator in PATH_TERMINATORS:
        trimmed = trimmed.split(terminator, 1)[0]

    segments: List[str] = []
    for segment in trimmed.split("/"):
        head = segment.split(";", 1)[0].strip()
        if head:
            segments.append(head.lower())
    return tuple(segments)


def comparable_path_segments(path: str) -> Tuple[str, ...]:
    """Reduce a path to the segments of its fully decoded form.

    The comparison has to survive every spelling that still reaches the same
    upstream handler, including one that only becomes that spelling after the
    upstream has decoded the path a second time, so the path is decoded until
    it settles before it is split.
    """
    rounds, _ = decoding_rounds(path)
    return path_segments(rounds[-1])


def path_is_blocked(path: str, blocked_paths: Iterable[str]) -> bool:
    """Report whether a path is at or below one of the blocked paths.

    Every decoding round is compared, not only the last one, so a path is
    refused whether the upstream decodes it once or several times. An entry
    matches whole segments only, so `/metrics` blocks `/metrics`, `/metrics/`
    and `/metrics/anything` while leaving `/metricsfoo` and
    `/v1/metrics-report` alone.
    """
    prefixes = [comparable_path_segments(entry) for entry in blocked_paths]
    prefixes = [prefix for prefix in prefixes if prefix]
    if not prefixes:
        return False

    rounds, _ = decoding_rounds(path)
    for candidate in rounds:
        segments = path_segments(candidate)
        for prefix in prefixes:
            if segments[: len(prefix)] == prefix:
                return True
    return False


def has_dot_segment(path: str) -> bool:
    """Report whether any decoding round of a path contains a dot segment.

    A `;parameters` suffix does not hide one: a servlet style upstream strips
    the parameters of a segment before it normalises the path, so `..;` and
    `..;jsessionid=1` walk up the tree there just like `..` does.
    """
    rounds, settled = decoding_rounds(path)
    if not settled:
        return True
    for candidate in rounds:
        for segment in candidate.split("/"):
            if segment.split(";", 1)[0].strip() in DOT_SEGMENTS:
                return True
    return False


def has_disguised_dot_segment(path: str) -> bool:
    """Report a dot segment that URL building will not resolve on its own.

    httpx collapses a segment that is written exactly as `.` or `..`, and the
    containment check that follows judges the collapsed result, so a literal
    dot segment needs no separate answer here. A segment that only becomes a
    dot segment once an upstream strips its `;parameters` or decodes the path
    again survives that collapsing untouched, which is what this reports.
    """
    rounds, settled = decoding_rounds(path)
    if not settled:
        return True
    for index, candidate in enumerate(rounds):
        for segment in candidate.split("/"):
            head = segment.split(";", 1)[0].strip()
            if head in DOT_SEGMENTS and (index > 0 or segment != head):
                return True
    return False
