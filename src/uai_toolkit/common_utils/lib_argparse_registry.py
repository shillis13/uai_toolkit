import argparse
from typing import Callable, List

# Registry storing callbacks that add arguments to a parser
_registered_callbacks: List[Callable[[argparse.ArgumentParser], None]] = []


def register_arguments(callback: Callable[[argparse.ArgumentParser], None]) -> None:
    """Register a callback that adds arguments to a parser."""
    _registered_callbacks.append(callback)


def build_parser(**kwargs) -> argparse.ArgumentParser:
    """Create an ArgumentParser with arguments from all registered callbacks."""
    parser = argparse.ArgumentParser(**kwargs)
    for cb in _registered_callbacks:
        cb(parser)
    return parser


def parse_known_args(args=None, **kwargs):
    """Parse args using a parser built from registered callbacks."""
    parser = build_parser(**kwargs)
    return parser.parse_known_args(args)
