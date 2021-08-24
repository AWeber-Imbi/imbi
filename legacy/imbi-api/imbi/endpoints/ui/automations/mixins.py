from imbi import errors


class PrepareFailureMixin:

    @staticmethod
    def handle_prepare_failures(action: str, failures: list) -> Exception:
        action = action.title()
        if len(failures) == 1:
            return errors.BadRequest(
                '%s failed: %s',
                action, failures[0],
                title=f'{action} failure', failures=failures)
        return errors.BadRequest(
            '%s failed with %s errors',
            action, len(failures),
            title=f'{action} failure', failures=failures)
