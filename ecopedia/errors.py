class AppError(Exception):
    """화면에 그대로 표시해도 되는 오류만 이 유형으로 전달한다."""


class ConfigurationError(AppError):
    pass


class SourceError(AppError):
    pass
