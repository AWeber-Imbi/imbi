import typing as t

import pydantic
import pydantic_settings


def settings_from_environment[S: pydantic_settings.BaseSettings](
    typ: type[S],
    **defaults: t.Any,  # noqa: ANN401
) -> S:
    """Load Pydantic settings from environment variables.

    Instantiates a Pydantic settings class from environment variables,
    providing enhanced error messages when required variables are missing.
    Unlike the default Pydantic behavior, this function translates validation
    errors for missing fields into clear SettingsError messages that include
    the exact environment variable names (with env_prefix) that need to be
    set.

    Args:
        typ: Pydantic BaseSettings class to instantiate
        **defaults: Default values to pass to the settings constructor,
            overriding environment variables if provided

    Returns:
        Instantiated settings object of type S

    Raises:
        TypeError: If typ is not a subclass of BaseSettings
        pydantic_settings.SettingsError: When required environment variables
            are missing, with a message listing the missing variable names
        pydantic.ValidationError: For other validation errors (type mismatches,
            constraints violations, etc.)

    """
    if not issubclass(typ, pydantic_settings.BaseSettings):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f'{typ.__name__} is not a subclass of '
            'pydantic_settings.BaseSettings'
        )
    try:
        return typ(**defaults)
    except pydantic.ValidationError as exc:
        missing_vars = ', '.join(
            typ.model_config.get('env_prefix', '')
            + '__'.join(str(loc) for loc in error['loc']).upper()
            for error in exc.errors()
            if error['type'] == 'missing'
        )
        if missing_vars:
            raise pydantic_settings.SettingsError(
                f'Missing environment variable(s): {missing_vars}'
            ) from None
        raise
