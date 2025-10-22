"""
Utility functions for scheduler
"""

from uuid import UUID


def is_valid_uuid(value: str) -> bool:
    """
    Check if a string is a valid UUID

    Args:
        value: String to validate

    Returns:
        True if valid UUID, False otherwise
    """
    if not value:
        return False

    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
