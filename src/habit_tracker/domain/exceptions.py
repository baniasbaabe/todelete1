class HabitTrackerError(Exception):
    pass


class UserNotFoundError(HabitTrackerError):
    pass


class HabitNotFoundError(HabitTrackerError):
    pass


class CompletionNotFoundError(HabitTrackerError):
    pass


class HabitAlreadyExistsError(HabitTrackerError):
    pass


class HabitLimitExceededError(HabitTrackerError):
    pass


class InvalidProofTypeError(HabitTrackerError):
    pass


class ConfigurationError(HabitTrackerError):
    pass
