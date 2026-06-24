"""
File: lib_logging.py
"""

import logging
import argparse
from contextlib import contextmanager
from functools import wraps

from ai_toolkit.common_utils.lib_outputColors import colorize_string, print_colored, Colors

"""
Set up the basic configuration for the logging system.
Args:
    level (int): The logging level, e.g., logging.INFO, logging.DEBUG.
Example:
    setup_logging(logging.DEBUG)
"""


def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s : %(filename)s : %(funcName)s : %(lineno)d : %(levelname)s : %(message)s",
    )


"""
Context manager for logging the entry and exit of a code block.
Args:
    name (str): The name of the block for logging purposes.
Example:
    with log_block("process_data"):
        # code block
"""


@contextmanager
def log_block(name):
    logging.info(f"Entering block: {name}", stacklevel=4)
    try:
        yield
    finally:
        logging.info(f"Exiting block: {name}", stacklevel=4)


"""
Decorator for logging function calls with their arguments and return values.
Args:
    func (function): The function to be wrapped for logging.
Returns:
    function: The wrapped function.
Example:
    @log_function
    def add(a, b):
        return a + b
"""


def log_function(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        logging.debug(
            f"Function {func.__name__} called with args: {args} and kwargs: {kwargs}",
            stacklevel=4,
        )
        result = func(*args, **kwargs)
        logging.debug(f"Function {func.__name__} returned {result}", stacklevel=4)
        return result

    return wrapper


# Decorator to handle non-string inputs in logging functions
def handle_non_string_inputs(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Convert all args to strings
        str_args = [str(arg) for arg in args]
        # Convert all key-value pairs in kwargs to strings
        str_kwargs = {k: str(v) for k, v in kwargs.items()}
        return func(*str_args, **str_kwargs)

    return wrapper


"""
Log an informational message with color.
Args:
    message (str): The message to log.
Example:
    log_info("Data processing complete.")
"""


@handle_non_string_inputs
def log_info(message, stacklevel=4):
    colored_message = colorize_string(message, fore_color="white")
    logging.info(colored_message, stacklevel=stacklevel)


"""
Log an error message with color.
Args:
    message (str): The message to log.
Example:
    log_error("Data processing failed.")
"""


@handle_non_string_inputs
def log_error(message, stacklevel=4):
    colored_message = colorize_string(message, fore_color="red")
    logging.error(colored_message, stacklevel=stacklevel)


"""
Log a debug message with color.
Args:
    message (str): The message to log.
Example:
    log_debug("Detailed debugging information.")
"""


@handle_non_string_inputs
def log_debug(message, stacklevel=4):
    colored_message = colorize_string(message, fore_color="gray")
    logging.debug(colored_message, stacklevel=stacklevel)


"""
Output a message without any additional formatting.

Args:
    message (str): The message to output.
"""


@handle_non_string_inputs
def log_out(message):
    print(message)


"""
Parse command-line arguments to set the logging level.

Returns:
    int: The logging level set by the user.
Example:
    --log-level DEBUG
"""


def parse_args():
    parser = argparse.ArgumentParser(description="Set the logging level.")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level (default: INFO)",
    )

    args, _ = parser.parse_known_args()
    level = getattr(logging, args.log_level.upper(), logging.INFO)
    setup_logging(level=level)
    return level
