def unwrap_as[T](typ: type[T], value: object | None) -> T:
    if value is None:
        raise ValueError('Value is unexpectedly None')
    if isinstance(value, typ):
        return value
    raise ValueError('Value is not of expected type')
