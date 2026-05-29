import re as _re
from importlib import metadata as _metadata

try:
    version = _metadata.version('imbi-slackbot')
except _metadata.PackageNotFoundError:
    version = '0.0.0'

version_info: list[int | str] = []
for _part in version.split('.'):
    _match = _re.fullmatch(r'(\d+)(.*)', _part)
    if _match is None:
        version_info.append(_part)
    else:
        version_info.append(int(_match.group(1)))
        if _match.group(2):
            version_info.append(_match.group(2))
del _metadata, _re
