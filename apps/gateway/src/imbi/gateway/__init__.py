from importlib import metadata

version = metadata.version('imbi-gateway')
version_info: list[int | str] = [int(c) for c in version.split('.')[:3]]
version_info.extend(version.split('.')[3:])
del metadata
