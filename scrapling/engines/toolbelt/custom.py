"""
Functions related to custom types or type checking
"""
import inspect
from email.message import Message

from scrapling.core._types import (Any, Callable, Dict, List, Optional, Tuple,
                                   Type, Union)
from scrapling.core.custom_types import MappingProxyType
from scrapling.core.utils import log, lru_cache
from scrapling.parser import Adaptor, SQLiteStorageSystem


class ResponseEncoding:
    __DEFAULT_ENCODING = "utf-8"
    __ISO_8859_1_CONTENT_TYPES = {"text/plain", "text/html", "text/css", "text/javascript"}

    @classmethod
    @lru_cache(maxsize=128)
    def __parse_content_type(cls, header_value: str) -> Tuple[str, Dict[str, str]]:
        """Parse content type and parameters from a content-type header value.

            Uses `email.message.Message` for robust header parsing according to RFC 2045.

        :param header_value: Raw content-type header string
        :return: Tuple of (content_type, parameters_dict)
        """
        # Create a Message object and set the Content-Type header then get the content type and parameters
        msg = Message()
        msg['content-type'] = header_value

        content_type = msg.get_content_type()
        params = dict(msg.get_params(failobj=[]))

        # Remove the content-type from params if present somehow
        params.pop('content-type', None)

        return content_type, params

    @classmethod
    @lru_cache(maxsize=128)
    def get_value(cls, content_type: Optional[str], text: Optional[str] = 'test') -> str:
        """Determine the appropriate character encoding from a content-type header.

        The encoding is determined by these rules in order:
            1. If no content-type is provided, use UTF-8
            2. If charset parameter is present, use that encoding
            3. If content-type is `text/*`, use ISO-8859-1 per HTTP/1.1 spec
            4. If content-type is application/json, use UTF-8 per RFC 4627
            5. Default to UTF-8 if nothing else matches

        :param content_type: Content-Type header value or None
        :param text: A text to test the encoding on it
        :return: String naming the character encoding
        """
        if not content_type:
            return cls.__DEFAULT_ENCODING

        try:
            encoding = None
            content_type, params = cls.__parse_content_type(content_type)

            # First check for explicit charset parameter
            if "charset" in params:
                encoding = params["charset"].strip("'\"")

            # Apply content-type specific rules
            elif content_type in cls.__ISO_8859_1_CONTENT_TYPES:
                encoding = "ISO-8859-1"

            elif content_type == "application/json":
                encoding = cls.__DEFAULT_ENCODING

            if encoding:
                _ = text.encode(encoding)  # Validate encoding and validate it can encode the given text
                return encoding

            return cls.__DEFAULT_ENCODING

        except (ValueError, LookupError, UnicodeEncodeError):
            return cls.__DEFAULT_ENCODING


class Response(Adaptor):
    """This class is returned by all engines as a way to unify response type between different libraries."""

    def __init__(self, url: str, text: str, body: bytes, status: int, reason: str, cookies: Dict, headers: Dict, request_headers: Dict,
                 encoding: str = 'utf-8', method: str = 'GET', history: List = None, **adaptor_arguments: Dict):
        automatch_domain = adaptor_arguments.pop('automatch_domain', None)
        self.status = status
        self.reason = reason
        self.cookies = cookies
        self.headers = headers
        self.request_headers = request_headers
        self.history = history or []
        encoding = ResponseEncoding.get_value(encoding, text)
        super().__init__(text=text, body=body, url=automatch_domain or url, encoding=encoding, **adaptor_arguments)
        # For back-ward compatibility
        self.adaptor = self
        # For easier debugging while working from a Python shell
        log.info(f'Fetched ({status}) <{method} {url}> (referer: {request_headers.get("referer")})')

    # def __repr__(self):
    #     return f'<{self.__class__.__name__} [{self.status} {self.reason}]>'


class BaseFetcher:
    __slots__ = ()
    huge_tree: bool = True
    auto_match: Optional[bool] = False
    storage: Any = SQLiteStorageSystem
    keep_cdata: Optional[bool] = False
    storage_args: Optional[Dict] = None
    keep_comments: Optional[bool] = False
    automatch_domain: Optional[str] = None
    parser_keywords: Tuple = ('huge_tree', 'auto_match', 'storage', 'keep_cdata', 'storage_args', 'keep_comments', 'automatch_domain',)  # Left open for the user

    def __init__(self, *args, **kwargs):
        # For backward-compatibility before 0.2.99
        args_str = ", ".join(args) or ''
        kwargs_str = ", ".join(f'{k}={v}' for k, v in kwargs.items()) or ''
        if args_str:
            args_str += ', '

        log.warning(f'This logic is deprecated now, and have no effect; It will be removed with v0.3. Use `{self.__class__.__name__}.configure({args_str}{kwargs_str})` instead before fetching')
        pass

    @classmethod
    def display_config(cls):
        return dict(
            huge_tree=cls.huge_tree,
            keep_comments=cls.keep_comments,
            keep_cdata=cls.keep_cdata,
            auto_match=cls.auto_match,
            storage=cls.storage,
            storage_args=cls.storage_args,
            automatch_domain=cls.automatch_domain,
        )

    @classmethod
    def configure(cls, **kwargs):
        """Set multiple arguments for the parser at once globally

        :param kwargs: The keywords can be any arguments of the following: huge_tree, keep_comments, keep_cdata, auto_match, storage, storage_args, automatch_domain
        """
        for key, value in kwargs.items():
            key = key.strip().lower()
            if hasattr(cls, key):
                if key in cls.parser_keywords:
                    setattr(cls, key, value)
                else:
                    # Yup, no fun allowed LOL
                    raise AttributeError(f'Unknown parser argument: "{key}"; maybe you meant {cls.parser_keywords}?')
            else:
                raise ValueError(f'Unknown parser argument: "{key}"; maybe you meant {cls.parser_keywords}?')

        if not kwargs:
            raise AttributeError(f'You must pass a keyword to configure, current keywords: {cls.parser_keywords}?')

    @classmethod
    def _generate_parser_arguments(cls) -> Dict:
        # Adaptor class parameters
        # I won't validate Adaptor's class parameters here again, I will leave it to be validated later
        parser_arguments = dict(
            huge_tree=cls.huge_tree,
            keep_comments=cls.keep_comments,
            keep_cdata=cls.keep_cdata,
            auto_match=cls.auto_match,
            storage=cls.storage,
            storage_args=cls.storage_args
        )
        if cls.automatch_domain:
            if type(cls.automatch_domain) is not str:
                log.warning('[Ignored] The argument "automatch_domain" must be of string type')
            else:
                parser_arguments.update({'automatch_domain': cls.automatch_domain})

        return parser_arguments


class StatusText:
    """A class that gets the status text of response status code.

        Reference: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status
    """
    _phrases = MappingProxyType({
        100: "Continue",
        101: "Switching Protocols",
        102: "Processing",
        103: "Early Hints",
        200: "OK",
        201: "Created",
        202: "Accepted",
        203: "Non-Authoritative Information",
        204: "No Content",
        205: "Reset Content",
        206: "Partial Content",
        207: "Multi-Status",
        208: "Already Reported",
        226: "IM Used",
        300: "Multiple Choices",
        301: "Moved Permanently",
        302: "Found",
        303: "See Other",
        304: "Not Modified",
        305: "Use Proxy",
        307: "Temporary Redirect",
        308: "Permanent Redirect",
        400: "Bad Request",
        401: "Unauthorized",
        402: "Payment Required",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        406: "Not Acceptable",
        407: "Proxy Authentication Required",
        408: "Request Timeout",
        409: "Conflict",
        410: "Gone",
        411: "Length Required",
        412: "Precondition Failed",
        413: "Payload Too Large",
        414: "URI Too Long",
        415: "Unsupported Media Type",
        416: "Range Not Satisfiable",
        417: "Expectation Failed",
        418: "I'm a teapot",
        421: "Misdirected Request",
        422: "Unprocessable Entity",
        423: "Locked",
        424: "Failed Dependency",
        425: "Too Early",
        426: "Upgrade Required",
        428: "Precondition Required",
        429: "Too Many Requests",
        431: "Request Header Fields Too Large",
        451: "Unavailable For Legal Reasons",
        500: "Internal Server Error",
        501: "Not Implemented",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
        505: "HTTP Version Not Supported",
        506: "Variant Also Negotiates",
        507: "Insufficient Storage",
        508: "Loop Detected",
        510: "Not Extended",
        511: "Network Authentication Required"
    })

    @classmethod
    @lru_cache(maxsize=128)
    def get(cls, status_code: int) -> str:
        """Get the phrase for a given HTTP status code."""
        return cls._phrases.get(status_code, "Unknown Status Code")


def check_if_engine_usable(engine: Callable) -> Union[Callable, None]:
    """This function check if the passed engine can be used by a Fetcher-type class or not.

    :param engine: The engine class itself
    :return: The engine class again if all checks out, otherwise raises error
    :raise TypeError: If engine class don't have fetch method, If engine class have fetch attribute not method, or If engine class have fetch function but it doesn't take arguments
    """
    # if isinstance(engine, type):
    #     raise TypeError("Expected an engine instance, not a class definition of the engine")

    if hasattr(engine, 'fetch'):
        fetch_function = getattr(engine, "fetch")
        if callable(fetch_function):
            if len(inspect.signature(fetch_function).parameters) > 0:
                return engine
            else:
                # raise TypeError("Engine class instance must have a callable method 'fetch' with the first argument used for the url.")
                raise TypeError("Engine class must have a callable method 'fetch' with the first argument used for the url.")
        else:
            # raise TypeError("Invalid engine instance! Engine class must have a callable method 'fetch'")
            raise TypeError("Invalid engine class! Engine class must have a callable method 'fetch'")
    else:
        # raise TypeError("Invalid engine instance! Engine class must have the method 'fetch'")
        raise TypeError("Invalid engine class! Engine class must have the method 'fetch'")


def get_variable_name(var: Any) -> Optional[str]:
    """Get the name of a variable using global and local scopes.
    :param var: The variable to find the name for
    :return: The name of the variable if found, None otherwise
    """
    for scope in [globals(), locals()]:
        for name, value in scope.items():
            if value is var:
                return name
    return None


def check_type_validity(variable: Any, valid_types: Union[List[Type], None], default_value: Any = None, critical: bool = False, param_name: Optional[str] = None) -> Any:
    """Check if a variable matches the specified type constraints.
    :param variable: The variable to check
    :param valid_types: List of valid types for the variable
    :param default_value: Value to return if type check fails
    :param critical: If True, raises TypeError instead of logging error
    :param param_name: Optional parameter name for error messages
    :return: The original variable if valid, default_value if invalid
    :raise TypeError: If critical=True and type check fails
    """
    # Use provided param_name or try to get it automatically
    var_name = param_name or get_variable_name(variable) or "Unknown"

    # Convert valid_types to a list if None
    valid_types = valid_types or []

    # Handle None value
    if variable is None:
        if type(None) in valid_types:
            return variable
        error_msg = f'Argument "{var_name}" cannot be None'
        if critical:
            raise TypeError(error_msg)
        log.error(f'[Ignored] {error_msg}')
        return default_value

    # If no valid_types specified and variable has a value, return it
    if not valid_types:
        return variable

    # Check if variable type matches any of the valid types
    if not any(isinstance(variable, t) for t in valid_types):
        type_names = [t.__name__ for t in valid_types]
        error_msg = f'Argument "{var_name}" must be of type {" or ".join(type_names)}'
        if critical:
            raise TypeError(error_msg)
        log.error(f'[Ignored] {error_msg}')
        return default_value

    return variable
