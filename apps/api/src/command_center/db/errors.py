"""Domain failures translated into HTTP responses at the application boundary."""


class RecordConflict(ValueError):
    pass


class RecordNotFound(LookupError):
    pass
