"""The one error type the API answers with: an HTTP status, a code for programs and a message for
people."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def bad_request(message: str, code: str = "bad_request") -> ApiError:
    return ApiError(400, code, message)


def not_found(message: str, code: str = "not_found") -> ApiError:
    return ApiError(404, code, message)


def conflict(message: str, code: str = "conflict") -> ApiError:
    return ApiError(409, code, message)
