"""
File: lib_progressBar.py

"""

import time
from functools import wraps
from contextlib import contextmanager

try:
    from tqdm import tqdm

    tqdm_available = True
except ImportError:
    tqdm = None
    tqdm_available = False

progress_bar_enabled = True


def enable_progress_bars():
    """
    Enable progress bars globally.
    """
    global progress_bar_enabled
    progress_bar_enabled = True


def disable_progress_bars():
    """
    Disable progress bars globally.
    """
    global progress_bar_enabled
    progress_bar_enabled = False


progress_stack = []


@contextmanager
def ProgressBarContext(total, desc="Progress"):
    """
    Context manager for a progress bar.

    Args:
        total (int): Total number of iterations.
        desc (str): Description for the progress bar.
    """
    if tqdm_available and progress_bar_enabled:
        with tqdm(total=total, desc=desc, leave=True) as pbar:
            progress_stack.append(pbar)
            try:
                yield pbar
            finally:
                pbar.update(total - pbar.n)  # Ensure progress bar completes
                progress_stack.pop()
    else:
        yield None


def progress_bar(total, desc="Progress"):
    """
    Decorator for adding a progress bar to a function.

    Args:
        total (int): Total number of iterations.
        desc (str): Description for the progress bar.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if tqdm_available and progress_bar_enabled:
                with ProgressBarContext(total=total, desc=desc) as pbar:
                    result = func(*args, **kwargs)
                if progress_stack:
                    progress_stack[-1].update(1)
                return result
            else:
                return func(*args, **kwargs)

        return wrapper

    return decorator


def recursive_progress_bar(total, desc="Recursive Progress"):
    """
    Decorator for adding a progress bar to a recursive function.

    Args:
        total (int): Total number of iterations.
        desc (str): Description for the progress bar.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if tqdm_available and progress_bar_enabled:
                if not progress_stack:
                    with ProgressBarContext(total=total, desc=desc) as pbar:
                        result = func(*args, **kwargs)
                        if pbar:
                            pbar.update(total - pbar.n)
                        return result
                else:
                    pbar = progress_stack[-1]
                    pbar.total += 2  # Increase the overall total by 2
                    pbar.update(1)  # Increase progress by 1 for the call
                    result = func(*args, **kwargs)
                    pbar.update(1)  # Increase progress by 1 for the return
                    return result
            else:
                return func(*args, **kwargs)

        return wrapper

    return decorator


# {{{
# **************************************
# * Testing methods
# **************************************


@progress_bar(total=3, desc="Parent Function Progress")
def parent_function():
    """
    Example function to demonstrate progress bar with nested steps.
    """
    step1()
    step2()
    step3()


@progress_bar(total=2, desc="Step 1 Progress")
def step1():
    """
    Example step function to demonstrate progress bar.
    """
    for _ in range(2):
        time.sleep(1)


@progress_bar(total=1, desc="Step 2 Progress")
def step2():
    """
    Example step function to demonstrate progress bar.
    """
    time.sleep(1)


@progress_bar(total=4, desc="Step 3 Progress")
def step3():
    """
    Example step function to demonstrate progress bar.
    """
    for _ in range(4):
        time.sleep(0.5)


@recursive_progress_bar(total=1, desc="Recursive Function Progress")
def recursive_function(n):
    """
    Example recursive function to demonstrate progress bar.

    Args:
        n (int): Number of recursive calls.
    """
    if n <= 0:
        return
    time.sleep(0.5)
    recursive_function(n - 1)
    time.sleep(0.5)


def test_example_function_with_progress():
    """
    Test function to demonstrate progress bar with a simple loop.
    """
    print("Testing example_function_with_progress...")
    example_function_with_progress(total=10)


@progress_bar(total=10, desc="Example Function with Progress")
def example_function_with_progress(total):
    """
    Example function to demonstrate progress bar with a simple loop.

    Args:
        total (int): Total number of iterations.
    """
    for _ in range(total):
        time.sleep(0.1)


def test_progress_bar():
    """
    Test function to demonstrate progress bar with nested steps.
    """
    print("Testing progress bar with parent function...")
    parent_function()


def test_recursive_function():
    """
    Test function to demonstrate progress bar with a recursive function.
    """
    print("Testing progress bar with recursive function...")
    recursive_function(10)


def test_progress_bar_context():
    """
    Test function to demonstrate progress bar with a context manager.
    """
    print("Testing progress bar with context manager...")
    with ProgressBarContext(total=5, desc="Context Manager Progress") as pbar:
        for _ in range(5):
            time.sleep(0.5)
            if pbar:
                pbar.update(1)


def main():
    """
    Main function to run all tests.
    """
    if tqdm_available and progress_bar_enabled:
        test_example_function_with_progress()
        test_progress_bar()
        test_recursive_function()
        test_progress_bar_context()
    else:
        print("tqdm is not available or progress bars are disabled.")


if __name__ == "__main__":
    main()
