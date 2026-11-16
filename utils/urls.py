import re


# Removes the language prefix right after the domain:
#   "https://kyiv.karabas.com/uk/some-event/" -> "https://kyiv.karabas.com/some-event/"
# Only the segment right after the domain is touched, "/ukraine-tour/" is kept as is.
#
# Use it only for sites where the prefixed URL does not work:
#   karabas.com  - "/uk/..." is 404, Ukrainian pages have no prefix -> strip
#   concert.ua   - "/uk/..." is the canonical URL (without it 301 back to /uk/) -> do NOT strip
def strip_language_prefix(url: str, language: str = "uk") -> str:
    return re.sub(rf"^(https?://[^/]+)/{re.escape(language)}/", r"\1/", url)
